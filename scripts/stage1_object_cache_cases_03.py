from __future__ import annotations
from stage1_object_cache_test_support import *


class ObjectCacheCases3(CacheTestFixture):
    def test_admitted_replay_io_failure_is_not_a_cache_miss(self):
        class FailingStream(io.BytesIO):
            def write(self, data):
                raise OSError("diagnostic sink failed")

        out, err = self.source.parent / "stdout", self.source.parent / "stderr"
        out.write_bytes(b"compile result\n")
        err.write_bytes(b"compile warning\n")
        for failing in ("stderr", "stdout"):
            with self.subTest(failing=failing):
                self.assertTrue(cache.publish(self.entry, self.source, "key", out, err))
                stdout = FailingStream() if failing == "stdout" else io.BytesIO()
                stderr = FailingStream() if failing == "stderr" else io.BytesIO()
                with self.assertRaisesRegex(OSError, "diagnostic sink failed"):
                    cache.restore(self.entry, self.output, "key", stdout=stdout, stderr=stderr)
                self.assertEqual(self.output.read_bytes(), self.source.read_bytes())
                self.assertEqual(stderr.getvalue(), err.read_bytes() if failing == "stdout" else b"")
                self.assertEqual(stdout.getvalue(), b"")
                self.assertFalse(list(self.output.parent.glob("*.incoming.*")))


    def test_bad_diagnostics_never_publish_or_replay(self):
        for name in ("stdout", "stderr"):
            for missing in (False, True):
                with self.subTest(name=name, missing=missing):
                    self.publish()
                    stream = Path(str(self.entry) + "." + name)
                    if missing:
                        stream.unlink()
                    else:
                        stream.write_bytes(b"corrupted diagnostics")
                    stdout, stderr = io.BytesIO(), io.BytesIO()
                    self.assertFalse(cache.restore(self.entry, self.output, "key", stdout=stdout, stderr=stderr))
                    self.assertEqual(self.output.read_bytes(), b"previous valid output")
                    self.assertEqual((stdout.getvalue(), stderr.getvalue()), (b"", b""))
                    self.assertFalse(list(self.output.parent.glob("*.incoming.*")))


    def test_oversized_diagnostics_preserve_previous_entry(self):
        self.publish()
        err = self.source.parent / "stderr"
        err.write_bytes(b"large warning")
        with patch.object(cache, "MAX_DIAGNOSTIC_BYTES", 1):
            self.assertFalse(cache.publish(self.entry, self.source, "key", stderr=err))
        self.assertTrue(cache.restore(self.entry, self.output, "key"))
        self.assertFalse(list(self.entry.parent.glob("*.incoming.*")))


    def test_oversized_object(self):
        self.publish()
        with patch.object(cache, "MAX_OBJECT_BYTES", 1):
            self.refused()


