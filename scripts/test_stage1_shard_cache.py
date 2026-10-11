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
        real_copy = shard.synced_copy
        changed = False
        def race(src, dst, limit=shard.MAX_BYTES):
            nonlocal changed
            if Path(src).name == "object" and not changed:
                Path(src).write_bytes(b"racing corrupted bytes")
                changed = True
            return real_copy(src, dst, limit)
        with patch.object(shard, "synced_copy", side_effect=race):
            self.assertFalse(self.restore())
        self.assertEqual(self.output.read_bytes(), b"prior")

    def test_staged_copy_corruption_and_oversized_manifest(self):
        self.publish()
        self.output.write_bytes(b"prior")
        real_copy = shard.synced_copy
        def corrupt_copy(src, dst, limit=shard.MAX_BYTES):
            real_copy(src, dst, limit)
            if Path(src).name == "stderr":
                Path(dst).write_bytes(b"corrupted empty stream copy")
        with patch.object(shard, "synced_copy", side_effect=corrupt_copy):
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

    def test_empty_object_and_empty_recipe_rejected(self):
        self.files["object"].write_bytes(b"")
        with self.assertRaises(ValueError):
            self.publish()
        for key in ("target_triple", "data_layout", "ownership_version", "restriction_version"):
            with self.assertRaises(ValueError):
                self.prepare(dict(self.options, **{key: ""}))


if __name__ == "__main__":
    unittest.main()
