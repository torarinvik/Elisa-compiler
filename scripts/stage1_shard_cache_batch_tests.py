from __future__ import annotations
from stage1_shard_cache_test_support import *


class ShardCacheBatchTests(CacheTestFixture):
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
            self.assertEqual(len(list(self.root.glob("*.incoming-*"))), 3)
            for staged in batch.outputs[0][1]:
                self.assertEqual(staged.stat().st_mode & 0o777, 0o600)
            fresh = batch.prepare(self.files["snapshot"], dict(self.options, logical_shard=2))
            batch.publish(fresh, self.files["object"], self.files["stdout"], self.files["stderr"])
            self.files["llvm"].write_bytes(b"changed during batch")
            with self.assertRaises(ValueError):
                batch.finish()
        self.assertFalse(self.output.exists())
        self.assertFalse((self.cache / fresh["key"]).exists())
        self.assertFalse(list(self.cache.glob(".batch-*")))

    def test_batch_restore_keeps_staging_private_then_publishes_original_modes(self):
        expected_modes = {"object": 0o640, "stdout": 0o604, "stderr": 0o600}
        for name, mode in expected_modes.items():
            self.files[name].chmod(mode)
        self.publish()
        with shard.BatchInvocation(self.cache, self.files["producer"], self.files["llvm"], self.files["runtime"], [self.files["profile"]]) as batch:
            self.assertTrue(batch.restore(self.ticket, self.output, self.out, self.err))
            for staged in batch.outputs[0][1]:
                self.assertEqual(staged.stat().st_mode & 0o777, 0o600)
            batch.finish()
        for restored, name in ((self.output, "object"), (self.out, "stdout"), (self.err, "stderr")):
            self.assertEqual(restored.stat().st_mode & 0o777, expected_modes[name])

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
            self.assertFalse(output.parent.parent.exists())
            self.assertFalse(list(self.root.glob("*.incoming-*")))
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
