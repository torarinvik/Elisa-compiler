#!/usr/bin/env python3
"""Native-independent admission controls; no compiler builds or timings."""
import copy
import importlib.util
import json
import multiprocessing
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("shard", Path(__file__).with_name("stage1_shard_cache.py"))
shard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shard)


def process_worker(start, cache, ticket, root, writer, number):
    start.wait()
    root = Path(root)
    for _ in range(8):
        if writer:
            shard.publish(cache, ticket, root / "object", root / "stdout", root / "stderr")
        else:
            output = root / f"reader-{number}.o"
            if shard.restore(cache, ticket, output, root / f"reader-{number}.out", root / f"reader-{number}.err"):
                assert output.read_bytes() == (root / "object").read_bytes()


class ShardCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.options = {key: "none" for key in shard.FIELDS}
        self.options.update(target_triple="x86_64-unknown-linux-gnu", data_layout="e-p:64:64",
                            cpu="generic", features="", opt_pipeline="default<O2>", codegen_opt="0",
                            ownership_version="stable-name-v1", restriction_version="foreign-strip-v1",
                            producer_discovery_version="running-executable-v1",
                            llvm_discovery_version="dladdr-LLVMContextCreate-v1",
                            logical_shard=1, logical_shards=4, coverage_policy="none", pgo_policy="none",
                            resolved_output_policy={"normalized_codegen_args": [], "output_environment": {}})
        self.files = {}
        for name in ("snapshot", "producer", "llvm", "runtime", "profile", "object", "stdout", "stderr"):
            self.files[name] = self.root / name
            self.files[name].write_bytes((name + " contents").encode() if name not in ("stdout", "stderr") else b"")
        self.cache = self.root / "cache"
        self.ticket = self.prepare()
        self.output = self.root / "output.o"
        self.out = self.root / "out.log"
        self.err = self.root / "err.log"

    def prepare(self, options=None):
        return shard.prepare(self.files["snapshot"], self.files["producer"], self.files["llvm"],
                             self.files["runtime"], options or self.options, [self.files["profile"]])

    def publish(self):
        return shard.publish(self.cache, self.ticket, self.files["object"], self.files["stdout"], self.files["stderr"])

    def restore(self):
        return shard.restore(self.cache, self.ticket, self.output, self.out, self.err)

    def test_hit_skip_signal_and_miss(self):
        self.assertFalse(self.restore())
        self.files["stderr"].write_bytes(b"optimization remark\n")
        self.publish()
        self.assertTrue(self.restore())
        self.assertEqual(self.output.read_bytes(), self.files["object"].read_bytes())
        self.assertEqual(self.err.read_bytes(), b"optimization remark\n")
        self.assertEqual(self.out.read_bytes(), b"")

    def test_options_and_actual_artifacts_invalidate(self):
        for key in shard.FIELDS - {"logical_shards", "logical_shard", "opt_pipeline", "codegen_opt", "producer_discovery_version", "llvm_discovery_version", "resolved_output_policy", "coverage_policy", "pgo_policy"}:
            options = dict(self.options)
            options[key] += "changed"
            self.assertNotEqual(self.prepare(options)["key"], self.ticket["key"], key)
        for change in ({"logical_shard": 2}, {"logical_shards": 8}, {"opt_pipeline": "none"}, {"codegen_opt": "2"}, {"coverage_policy": "instrument"}, {"pgo_policy": "use"},
                       {"resolved_output_policy": {"normalized_codegen_args": ["-debug"], "output_environment": {}}},
                       {"resolved_output_policy": {"normalized_codegen_args": [], "output_environment": {"ELISA_DEBUG": "1"}}}):
            self.assertNotEqual(self.prepare(dict(self.options, **change))["key"], self.ticket["key"])
        for name in ("snapshot", "producer", "llvm", "runtime", "profile"):
            old = self.files[name].read_bytes()
            self.files[name].write_bytes(old + b"changed")
            self.assertNotEqual(self.prepare()["key"], self.ticket["key"], name)
            with self.assertRaises(ValueError):
                shard.validate_ticket(self.ticket)
            self.files[name].write_bytes(old)
        self.assertEqual(self.prepare()["key"], self.ticket["key"])

    def test_paths_are_not_identity_or_supplied_digest(self):
        copied = self.root / "copied-producer"
        copied.write_bytes(self.files["producer"].read_bytes())
        ticket = shard.prepare(self.files["snapshot"], copied, self.files["llvm"], self.files["runtime"], self.options, [self.files["profile"]])
        self.assertEqual(ticket["key"], self.ticket["key"])
        forged = copy.deepcopy(self.ticket)
        forged["pins"]["producer"]["identity"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            shard.validate_ticket(forged)
        for value in ({"worker_count": 2}, {"logical_shard": True}, {"logical_shards": 0}, {"llvm_discovery_version": "requested-path"}):
            with self.assertRaises(ValueError):
                self.prepare(dict(self.options, **value))

    def test_corruption_preserves_existing_output_and_recovers(self):
        for name in ("object", "stdout", "stderr", "manifest.json"):
            self.publish()
            self.output.write_bytes(b"prior good output")
            entry = self.cache / self.ticket["key"] / name
            entry.write_bytes(b"corrupt")
            self.assertFalse(self.restore(), name)
            self.assertEqual(self.output.read_bytes(), b"prior good output")
            self.publish()
            self.assertTrue(self.restore())

    def test_malformed_manifest_fields_are_cache_misses(self):
        stamp = self.cache / self.ticket["key"] / "manifest.json"
        mutations = (
            ("missing stream", lambda value: value.pop("stdout")),
            ("unknown field", lambda value: value.update(extra="unknown")),
            ("boolean size", lambda value: value["object"].update(size=True)),
            ("malformed checksum", lambda value: value["stderr"].update(sha256="A" * 64)),
        )
        for label, mutate in mutations:
            with self.subTest(manifest_error=label):
                self.publish()
                manifest = json.loads(stamp.read_text())
                mutate(manifest)
                stamp.write_text(json.dumps(manifest))
                self.output.write_bytes(b"prior good output")
                self.assertFalse(self.restore())
                self.assertEqual(self.output.read_bytes(), b"prior good output")
                self.assertFalse(list(self.root.glob("*.incoming-*")))

    def test_failed_publication_has_no_admissible_partial_bundle(self):
        real_replace = shard.os.replace
        def fail_commit(src, dst):
            if Path(dst) == self.cache / self.ticket["key"]:
                raise OSError("injected atomic commit failure")
            return real_replace(src, dst)
        with patch.object(shard.os, "replace", side_effect=fail_commit):
            with self.assertRaises(OSError):
                self.publish()
        self.assertFalse(self.restore())
        self.assertFalse(list(self.cache.glob(".incoming-*")))

    def test_mid_restore_mutation_is_not_admitted(self):
        self.publish()
        self.output.write_bytes(b"prior")
        real_copy = shard.copy_fingerprint
        changed = False
        def race(src, dst, *, allow_empty=False, limit=shard.MAX_BYTES):
            nonlocal changed
            if Path(src).name == "object" and not changed:
                Path(src).write_bytes(b"racing corrupted bytes")
                changed = True
            return real_copy(src, dst, allow_empty=allow_empty, limit=limit)
        with patch.object(shard, "copy_fingerprint", side_effect=race):
            self.assertFalse(self.restore())
        self.assertEqual(self.output.read_bytes(), b"prior")

    def test_staged_copy_corruption_and_oversized_manifest(self):
        self.publish()
        self.output.write_bytes(b"prior")
        real_copy = shard.copy_fingerprint
        def corrupt_copy(src, dst, *, allow_empty=False, limit=shard.MAX_BYTES):
            result = real_copy(src, dst, allow_empty=allow_empty, limit=limit)
            if Path(src).name == "stderr":
                Path(dst).write_bytes(b"corrupted empty stream copy")
            return result
        with patch.object(shard, "copy_fingerprint", side_effect=corrupt_copy):
            self.assertFalse(self.restore())
        self.assertEqual(self.output.read_bytes(), b"prior")
        (self.cache / self.ticket["key"] / "manifest.json").write_bytes(b" " * 16385)
        self.assertFalse(self.restore())
        self.assertEqual(self.output.read_bytes(), b"prior")
        with self.assertRaises(ValueError):
            self.prepare(dict(self.options, resolved_output_policy={"unknown_flag": True}))

    def test_input_changed_during_compile_cannot_publish(self):
        self.files["snapshot"].write_bytes(b"edited after compile admission")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertFalse((self.cache / self.ticket["key"]).exists())

    def test_concurrent_publication_and_restore_are_complete(self):
        errors = []
        def writer():
            try:
                for _ in range(4):
                    self.publish()
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=writer) for _ in range(3)]
        for thread in threads:
            thread.start()
        for _ in range(5):
            if self.restore():
                self.assertEqual(self.output.read_bytes(), self.files["object"].read_bytes())
        for thread in threads:
            thread.join()
        self.assertFalse(errors)
        self.assertTrue(self.restore())

    def test_cross_process_publication_and_reader_locking(self):
        ctx = multiprocessing.get_context("fork")
        start = ctx.Event()
        workers = [ctx.Process(target=process_worker, args=(start, self.cache, self.ticket, self.root, index < 3, index)) for index in range(5)]
        for worker in workers:
            worker.start()
        start.set()
        for worker in workers:
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join()
                self.fail("cache worker did not terminate")
            self.assertEqual(worker.exitcode, 0)
        self.assertTrue(self.restore())
        self.assertFalse(list(self.cache.glob(".incoming-*")))

    def test_restore_publication_failure_is_fatal_and_object_remains_prior(self):
        self.publish()
        self.output.write_bytes(b"prior object")
        self.out.write_bytes(b"prior stdout")
        real_replace = shard.os.replace
        def fail_stderr(src, dst):
            if Path(dst) == self.err:
                raise OSError("injected diagnostic publication failure")
            return real_replace(src, dst)
        with patch.object(shard.os, "replace", side_effect=fail_stderr):
            with self.assertRaises(OSError):
                self.restore()
        self.assertEqual(self.output.read_bytes(), b"prior object")
        self.assertEqual(self.out.read_bytes(), b"")
        self.assertFalse(list(self.root.glob("*.incoming-*")))

    def test_cli_ticket_hit_miss_and_fatal_status(self):
        helper = Path(shard.__file__)
        request = self.root / "request.json"
        ticket = self.root / "ticket.json"
        request.write_text(json.dumps(dict(snapshot=str(self.files["snapshot"]), producer=str(self.files["producer"]),
                                         loaded_llvm=str(self.files["llvm"]), runtime=str(self.files["runtime"]),
                                         options=self.options, profiles=[str(self.files["profile"])])))
        result = subprocess.run([sys.executable, str(helper), "prepare", "--request", str(request), "--ticket", str(ticket)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        common = ["--ticket", str(ticket), "--cache", str(self.cache), "--object", str(self.output), "--stdout", str(self.out), "--stderr", str(self.err)]
        self.assertEqual(subprocess.run([sys.executable, str(helper), "restore", *common], capture_output=True).returncode, 1)
        self.publish()
        self.assertEqual(subprocess.run([sys.executable, str(helper), "restore", *common], capture_output=True).returncode, 0)
        self.files["producer"].write_bytes(b"changed producer")
        self.assertEqual(subprocess.run([sys.executable, str(helper), "restore", *common], capture_output=True).returncode, 2)

    def test_publication_payload_mutation_and_colliding_output_paths_rejected(self):
        real_copy = shard.synced_copy
        def change_emitted(src, dst, limit=shard.MAX_BYTES):
            real_copy(src, dst, limit)
            if Path(src) == self.files["object"]:
                Path(src).write_bytes(b"compiler still writing object")
        with patch.object(shard, "synced_copy", side_effect=change_emitted):
            with self.assertRaises(ValueError):
                self.publish()
        self.assertFalse(self.restore())
        with self.assertRaises(ValueError):
            shard.restore(self.cache, self.ticket, self.output, self.output, self.err)
        with self.assertRaises(ValueError):
            shard.validate_ticket([])

    def test_batch_shared_reads_independent_of_shard_count(self):
        for count in (1, 64):
            with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
                for index in range(count):
                    ticket = batch.prepare(self.files["snapshot"], dict(self.options, logical_shards=count, logical_shard=index))
                    batch.publish(ticket, self.files["object"], self.files["stdout"], self.files["stderr"])
                metrics = batch.finish()
            self.assertEqual(metrics["shared_artifact_reads"], 8)
            with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
                for index in range(count):
                    ticket = batch.prepare(self.files["snapshot"], dict(self.options, logical_shards=count, logical_shard=index))
                    output = self.root / f"batch-{count}-{index}.o"
                    self.assertTrue(batch.restore(ticket, output, str(output) + ".out", str(output) + ".err"))
                    self.assertFalse(output.exists())  # No pre-attestation output publication.
                metrics = batch.finish()
            self.assertEqual(metrics["shared_artifact_reads"], 8)
            self.assertEqual(metrics["hits"], count)

    def test_batch_changed_shared_identity_discards_hits_and_publications(self):
        self.publish()
        with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
            self.assertTrue(batch.restore(self.ticket, self.output, self.out, self.err))
            fresh = batch.prepare(self.files["snapshot"], dict(self.options, logical_shard=2))
            batch.publish(fresh, self.files["object"], self.files["stdout"], self.files["stderr"])
            self.files["llvm"].write_bytes(b"changed during batch")
            with self.assertRaises(ValueError):
                batch.finish()
        self.assertFalse(self.output.exists())
        self.assertFalse((self.cache / fresh["key"]).exists())
        self.assertFalse(list(self.cache.glob(".batch-*")))

    def test_batch_cli_miss_publish_hit_and_fatal(self):
        helper = Path(shard.__file__)
        request = self.root / "batch-request.json"
        result = self.root / "batch-result.json"
        common = dict(cache=str(self.cache), producer=str(self.files["producer"]), loaded_llvm=str(self.files["llvm"]),
                      runtime=str(self.files["runtime"]), profiles=[str(self.files["profile"])])
        record = dict(snapshot=str(self.files["snapshot"]), options=dict(self.options, logical_shard=0, logical_shards=1), object=str(self.output), stdout=str(self.out), stderr=str(self.err))
        request.write_text(json.dumps(dict(common, shards=[record])))
        command = [sys.executable, str(helper), "batch-restore", "--request", str(request), "--result", str(result)]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
        ticket = json.loads(result.read_text())["shards"][0]["ticket"]
        publication = dict(ticket=ticket, object=str(self.files["object"]), stdout=str(self.files["stdout"]), stderr=str(self.files["stderr"]))
        request.write_text(json.dumps(dict(common, shards=[publication])))
        self.assertEqual(subprocess.run([sys.executable, str(helper), "batch-publish", "--request", str(request), "--result", str(result)], capture_output=True).returncode, 0)
        request.write_text(json.dumps(dict(common, shards=[record])))
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(json.loads(result.read_text())["metrics"]["shared_artifact_reads"], 8)
        self.assertEqual(self.output.read_bytes(), self.files["object"].read_bytes())
        publication["ticket"]["key"] = "0" * 64
        request.write_text(json.dumps(dict(common, shards=[publication])))
        self.assertEqual(subprocess.run([sys.executable, str(helper), "batch-publish", "--request", str(request), "--result", str(result)], capture_output=True).returncode, 2)

    def test_batch_staged_hit_mutation_fails_before_any_publication(self):
        self.publish()
        with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
            self.assertTrue(batch.restore(self.ticket, self.output, self.out, self.err))
            fresh = batch.prepare(self.files["snapshot"], dict(self.options, logical_shard=2))
            batch.publish(fresh, self.files["object"], self.files["stdout"], self.files["stderr"])
            batch.outputs[0][1][0].write_bytes(b"corrupted after restore")
            with self.assertRaises(ValueError):
                batch.finish()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.out.exists())
        self.assertFalse(self.err.exists())
        self.assertFalse((self.cache / fresh["key"]).exists())
        self.assertFalse(list(self.root.glob("*.incoming-*")))

    def test_batch_staged_copy_is_attested_before_cache_publication(self):
        self.publish()
        fresh = None
        with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
            real_copy = shard.copy_fingerprint

            def corrupt_staged_copy(src, dst, *, allow_empty=False, limit=shard.MAX_BYTES):
                result = real_copy(src, dst, allow_empty=allow_empty, limit=limit)
                if Path(src).parent == self.cache / self.ticket["key"] and Path(src).name == "object":
                    Path(dst).write_bytes(b"damaged private staging copy")
                return result

            with patch.object(shard, "copy_fingerprint", side_effect=corrupt_staged_copy):
                self.assertTrue(batch.restore(self.ticket, self.output, self.out, self.err))
            fresh = batch.prepare(self.files["snapshot"], dict(self.options, logical_shard=2))
            batch.publish(fresh, self.files["object"], self.files["stdout"], self.files["stderr"])
            with self.assertRaisesRegex(ValueError, "private restored hit changed before finalization"):
                batch.finish()
        self.assertFalse((self.cache / fresh["key"]).exists())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.out.exists())
        self.assertFalse(self.err.exists())
        self.assertFalse(list(self.root.glob("*.incoming-*")))

    def test_batch_miss_removes_new_destination_directories(self):
        output = self.root / "new-output" / "nested" / "object.o"
        with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
            ticket = batch.prepare(self.files["snapshot"], self.options)
            self.assertFalse(batch.restore(ticket, output, str(output) + ".out", str(output) + ".err"))
            self.assertTrue(batch.finish())
        self.assertFalse(output.parent.parent.exists())
        self.assertFalse(list(self.root.glob("*.incoming-*")))

    def test_batch_abandoned_hit_removes_new_destination_directories(self):
        self.publish()
        output = self.root / "abandoned-output" / "nested" / "object.o"
        with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
            self.assertTrue(batch.restore(self.ticket, output, str(output) + ".out", str(output) + ".err"))
            self.assertTrue(output.parent.exists())
        self.assertFalse(output.parent.parent.exists())
        self.assertFalse(list(self.root.glob("*.incoming-*")))

    def test_batch_staging_is_rechecked_after_cache_publication(self):
        self.publish()
        fresh = None
        with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
            self.assertTrue(batch.restore(self.ticket, self.output, self.out, self.err))
            fresh = batch.prepare(self.files["snapshot"], dict(self.options, logical_shard=2))
            batch.publish(fresh, self.files["object"], self.files["stdout"], self.files["stderr"])
            real_verify = shard.verify_bundle

            def mutate_hit_while_publishing(entry, ticket):
                result = real_verify(entry, ticket)
                if Path(entry) == batch.work / "publication" / ticket["key"]:
                    batch.outputs[0][1][0].write_bytes(b"changed during cache publication")
                return result

            with patch.object(shard, "verify_bundle", side_effect=mutate_hit_while_publishing):
                with self.assertRaisesRegex(ValueError, "changed before destination commit"):
                    batch.finish()
        self.assertTrue((self.cache / fresh["key"]).exists())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.out.exists())
        self.assertFalse(self.err.exists())
        self.assertFalse(list(self.root.glob("*.incoming-*")))

    def test_batch_lifecycle_and_failed_admission_cleanup(self):
        with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
            batch.finish()
            with self.assertRaises(ValueError):
                batch.prepare(self.files["snapshot"], self.options)
            with self.assertRaises(ValueError):
                batch.restore(self.ticket, self.output, self.out, self.err)
            with self.assertRaises(ValueError):
                batch.publish(self.ticket, self.files["object"], self.files["stdout"], self.files["stderr"])
        with self.assertRaises(ValueError):
            batch.finish()
        with self.assertRaises(OSError):
            shard.BatchInvocation(self.cache, self.root / "absent", self.files["llvm"], self.files["runtime"])
        self.assertFalse(list(self.cache.glob(".batch-*")))

    def test_native_status_manifest_and_original_result_publication(self):
        common = dict(cache=str(self.cache), producer=str(self.files["producer"]), loaded_llvm=str(self.files["llvm"]),
                      runtime=str(self.files["runtime"]), profiles=[str(self.files["profile"])])
        records = []
        for index in range(2):
            records.append(dict(snapshot=str(self.files["snapshot"]), options=dict(self.options, logical_shard=index, logical_shards=2),
                                object=str(self.root / f"native-{index}.o"), stdout=str(self.root / f"native-{index}.out"), stderr=str(self.root / f"native-{index}.err")))
        first = self.prepare(records[0]["options"])
        shard.publish(self.cache, first, self.files["object"], self.files["stdout"], self.files["stderr"])
        request = dict(common, shards=records)
        result = shard.batch_request("batch-restore", request)
        self.assertEqual(shard.status_text(result), "ELISA_PREOPT_SHARD_STATUS_V1\n2\nHM\n")
        # Actual native consumer emits only M; helper uses unchanged full ticket.
        for field, name in (("object", "object"), ("stdout", "stdout"), ("stderr", "stderr")):
            Path(records[1][field]).write_bytes(self.files[name].read_bytes())
        receipt = shard.publish_restore_result(request, result)
        self.assertEqual(receipt["published_misses"], 1)
        warm = shard.batch_request("batch-restore", request)
        self.assertEqual(shard.status_text(warm), "ELISA_PREOPT_SHARD_STATUS_V1\n2\nHH\n")
        malformed = copy.deepcopy(request)
        malformed["shards"][1]["options"]["logical_shard"] = 0
        with self.assertRaises(ValueError):
            shard.complete_restore_request(malformed)
        malformed = copy.deepcopy(request)
        malformed["shards"].reverse()
        with self.assertRaises(ValueError):
            shard.complete_restore_request(malformed)
        malformed = copy.deepcopy(request)
        malformed["shards"].pop()
        with self.assertRaises(ValueError):
            shard.complete_restore_request(malformed)
        malformed = copy.deepcopy(request)
        malformed["shards"][1]["options"]["cpu"] = "different"
        with self.assertRaises(ValueError):
            shard.complete_restore_request(malformed)
        for change in ("schema", "hit", "key"):
            malformed = copy.deepcopy(result)
            if change == "schema":
                malformed["schema"] = "unknown"
            elif change == "hit":
                malformed["shards"][0]["hit"] = 1
            else:
                malformed["shards"][0]["ticket"]["key"] = "0" * 64
            with self.assertRaises(ValueError):
                shard.status_text(malformed)
        changed = copy.deepcopy(request)
        changed["shards"][0]["options"]["cpu"] = "changed"
        changed["shards"][1]["options"]["cpu"] = "changed"
        with self.assertRaises(ValueError):
            shard.publish_restore_result(changed, result)

    def test_native_status_cli_and_immutable_publication_result(self):
        helper = Path(shard.__file__)
        request = self.root / "native-request.json"
        result = self.root / "native-restore.json"
        status = self.root / "native-status.txt"
        receipt = self.root / "native-publish.json"
        item = dict(snapshot=str(self.files["snapshot"]), options=dict(self.options, logical_shard=0, logical_shards=1),
                    object=str(self.output), stdout=str(self.out), stderr=str(self.err))
        request.write_text(json.dumps(dict(cache=str(self.cache), producer=str(self.files["producer"]), loaded_llvm=str(self.files["llvm"]),
                                          runtime=str(self.files["runtime"]), profiles=[str(self.files["profile"])], shards=[item])))
        command = [sys.executable, str(helper), "batch-restore", "--request", str(request), "--result", str(result), "--status", str(status)]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
        self.assertEqual(status.read_text(), "ELISA_PREOPT_SHARD_STATUS_V1\n1\nM\n")
        original = result.read_bytes()
        self.output.write_bytes(self.files["object"].read_bytes())
        self.out.write_bytes(b"")
        self.err.write_bytes(b"")
        publication = [sys.executable, str(helper), "batch-publish-result", "--request", str(request), "--restore-result", str(result), "--result", str(receipt)]
        self.assertEqual(subprocess.run(publication, capture_output=True).returncode, 0)
        self.assertEqual(result.read_bytes(), original)
        self.assertEqual(json.loads(receipt.read_text())["published_misses"], 1)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(status.read_text(), "ELISA_PREOPT_SHARD_STATUS_V1\n1\nH\n")
        publication[-1] = str(result)
        self.assertEqual(subprocess.run(publication, capture_output=True).returncode, 2)

    def test_batch_snapshot_reads_once_each_boundary(self):
        args = (self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"])
        for warm in (False, True):
            with shard.BatchInvocation(*args) as batch:
                ticket = batch.prepare(self.files["snapshot"], self.options)
                hit = batch.restore(ticket, self.output, self.out, self.err)
                self.assertEqual(hit, warm)
                for _ in range(8):
                    batch.validate(ticket)
                if not hit:
                    batch.publish(ticket, self.files["object"], self.files["stdout"], self.files["stderr"])
                self.assertEqual(batch.metrics["snapshot_reads"], 1)
                self.assertEqual(batch.finish()["snapshot_reads"], 2)
        other = self.root / "identical-snapshot"
        other.write_bytes(self.files["snapshot"].read_bytes())
        with shard.BatchInvocation(*args) as batch:
            ticket = batch.prepare(self.files["snapshot"], self.options)
            malicious = copy.deepcopy(ticket)
            malicious["snapshot"]["path"] = str(other)
            self.assertEqual(shard.ticket_key(malicious), ticket["key"])
            with self.assertRaises(ValueError):
                batch.validate(malicious)
        for path in (self.output, self.out, self.err):
            path.unlink()
        with shard.BatchInvocation(*args) as batch:
            ticket = batch.prepare(self.files["snapshot"], self.options)
            self.assertTrue(batch.restore(ticket, self.output, self.out, self.err))
            self.files["snapshot"].write_bytes(b"changed after hit")
            with self.assertRaises(ValueError):
                batch.finish()
        self.assertTrue(all(not path.exists() for path in (self.output, self.out, self.err)))

    def test_mapped_image_pins_admission_and_finalization(self):
        pins = {"producer": shard.fingerprint(self.files["producer"])["sha256"],
                "loaded_llvm": shard.fingerprint(self.files["llvm"])["sha256"]}
        args = (self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"])
        for bad in ({}, dict(pins, producer="A" * 64), dict(pins, loaded_llvm="0" * 64), dict(pins, extra="0" * 64)):
            with self.assertRaises(ValueError):
                shard.BatchInvocation(*args, mapped_image_digests=bad)
        with shard.BatchInvocation(*args, mapped_image_digests=pins) as batch:
            ticket = batch.prepare(self.files["snapshot"], self.options)
            batch.publish(ticket, self.files["object"], self.files["stdout"], self.files["stderr"])
            self.files["llvm"].write_bytes(b"changed mapped file")
            with self.assertRaises(ValueError):
                batch.finish()
        self.assertFalse((self.cache / ticket["key"]).exists())
        self.assertFalse(self.output.exists())

    def test_mapped_pins_changed_after_hit_publish_no_outputs(self):
        pins = {"producer": shard.fingerprint(self.files["producer"])["sha256"],
                "loaded_llvm": shard.fingerprint(self.files["llvm"])["sha256"]}
        args = (self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"])
        with shard.BatchInvocation(*args, mapped_image_digests=pins) as batch:
            ticket = batch.prepare(self.files["snapshot"], self.options)
            batch.publish(ticket, self.files["object"], self.files["stdout"], self.files["stderr"])
            batch.finish()
        with shard.BatchInvocation(*args, mapped_image_digests=pins) as batch:
            ticket = batch.prepare(self.files["snapshot"], self.options)
            self.assertTrue(batch.restore(ticket, self.output, self.out, self.err))
            self.files["producer"].write_bytes(b"replacement producer")
            with self.assertRaises(ValueError):
                batch.finish()
        self.assertTrue(all(not path.exists() for path in (self.output, self.out, self.err)))

    def test_mapped_pins_native_mixed_and_all_hit(self):
        pins = {"producer": shard.fingerprint(self.files["producer"])["sha256"],
                "loaded_llvm": shard.fingerprint(self.files["llvm"])["sha256"]}
        items = [dict(snapshot=str(self.files["snapshot"]), options=dict(self.options, logical_shard=i, logical_shards=2),
                      object=str(self.root / f"mapped-{i}.o"), stdout=str(self.root / f"mapped-{i}.out"),
                      stderr=str(self.root / f"mapped-{i}.err")) for i in range(2)]
        request = dict(cache=str(self.cache), producer=str(self.files["producer"]), loaded_llvm=str(self.files["llvm"]),
                       runtime=str(self.files["runtime"]), profiles=[], shards=items, mapped_image_digests=pins)
        cold = shard.batch_request("batch-restore", request)
        for item in items:
            Path(item["object"]).write_bytes(b"compiled object")
            Path(item["stdout"]).write_bytes(b"")
            Path(item["stderr"]).write_bytes(b"")
        missing = copy.deepcopy(request)
        missing.pop("mapped_image_digests")
        with self.assertRaises(ValueError):
            shard.publish_restore_result(missing, cold)
        shard.publish_restore_result(request, cold)
        warm = shard.batch_request("batch-restore", request)
        self.assertEqual(shard.status_text(warm), "ELISA_PREOPT_SHARD_STATUS_V1\n2\nHH\n")
        self.assertEqual(shard.publish_restore_result(request, warm)["published_misses"], 0)
        shutil_path = self.cache / warm["shards"][1]["ticket"]["key"] / "object"
        shutil_path.write_bytes(b"corrupt")
        mixed = shard.batch_request("batch-restore", request)
        self.assertEqual(shard.status_text(mixed), "ELISA_PREOPT_SHARD_STATUS_V1\n2\nHM\n")
        self.assertEqual(shard.publish_restore_result(request, mixed)["published_misses"], 1)
        for item in items:
            Path(item["object"]).unlink()
        invalid = copy.deepcopy(request)
        invalid["mapped_image_digests"]["producer"] = "0" * 64
        with self.assertRaises(ValueError):
            shard.batch_request("batch-restore", invalid)
        self.assertTrue(all(not Path(item["object"]).exists() for item in items))
        with self.assertRaises(ValueError):
            shard.publish_restore_result(invalid, mixed)
        malformed = copy.deepcopy(request)
        malformed["mapped_image_digests"] = None
        with self.assertRaises(ValueError):
            shard.complete_restore_request(malformed)

    def test_empty_object_and_empty_recipe_rejected(self):
        self.files["object"].write_bytes(b"")
        with self.assertRaises(ValueError):
            self.publish()
        for key in ("target_triple", "data_layout", "ownership_version", "restriction_version"):
            with self.assertRaises(ValueError):
                self.prepare(dict(self.options, **{key: ""}))


if __name__ == "__main__":
    unittest.main()
