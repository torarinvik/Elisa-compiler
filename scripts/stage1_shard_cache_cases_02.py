from __future__ import annotations
from stage1_shard_cache_test_support import *


class ShardCacheCases2(CacheTestFixture):
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


