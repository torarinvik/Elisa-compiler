from __future__ import annotations
from stage1_shard_cache_test_support import *


class ShardCachePublicationTests(CacheTestFixture):
    def test_input_changed_during_compile_cannot_publish(self):
        self.files["snapshot"].write_bytes(b"edited after compile admission")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertFalse((self.cache / self.ticket["key"]).exists())

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

    def test_empty_object_and_empty_recipe_rejected(self):
        self.files["object"].write_bytes(b"")
        with self.assertRaises(ValueError):
            self.publish()
        for key in ("target_triple", "data_layout", "ownership_version", "restriction_version"):
            with self.assertRaises(ValueError):
                self.prepare(dict(self.options, **{key: ""}))
