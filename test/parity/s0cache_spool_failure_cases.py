"""Exercise Stage0 cache spool failures and bounded replay."""
import contextlib
import io
import os
import pathlib
import sys
import tempfile
import time
import types


def check_spool_failures(s0cache_module):
    with tempfile.TemporaryDirectory(prefix="s0cache-selector-fifo-") as temp:
        selector_fifo = pathlib.Path(temp) / "tool"
        os.mkfifo(selector_fifo)
        assert not s0cache_module.is_native_tool_image(str(selector_fifo)), "FIFO tool selector was accepted"

    class SeekFailureSpool:
        def __init__(self):
            self.file = tempfile.TemporaryFile(mode="w+b")

        def fileno(self):
            return self.file.fileno()

        def seek(self, *_args):
            raise OSError("injected spool seek failure")

        def close(self):
            self.file.close()

    with tempfile.TemporaryFile(mode="w+b") as saved_stderr:
        saved_stderr.write(b"captured stderr\n")
        saved_stderr.flush()
        output_spool = SeekFailureSpool()
        proc = types.SimpleNamespace(
            stdout_data=b"captured stdout\n",
            stderr_data=b"captured stderr\n",
            output_capture_complete=True,
            output_capture_reason=None,
            output_spools=(output_spool, saved_stderr, [False, False]),
            returncode=37,
        )
        stdout_bytes, stderr_bytes = io.BytesIO(), io.BytesIO()
        stdout_text = io.TextIOWrapper(stdout_bytes, encoding="utf-8")
        stderr_text = io.TextIOWrapper(stderr_bytes, encoding="utf-8")
        with contextlib.redirect_stdout(stdout_text), contextlib.redirect_stderr(stderr_text):
            s0cache_module.replay_spooled_output(proc)
        assert stdout_bytes.getvalue() == b"captured stdout\n"
        assert stderr_bytes.getvalue() == b"captured stderr\n"
        assert proc.returncode == 37, "spool replay failure replaced the compiler status"
        assert not proc.output_capture_complete, "spool replay failure remained cacheable"
        assert proc.output_capture_reason == "spool-replay"

    # A short but readable spool must replay the retained tail, both after the
    # child exits and when the live drain crosses the cache output bound.
    short_stdout = tempfile.TemporaryFile(mode="w+b", buffering=0)
    short_stdout.write(b"captured ")
    full_stderr = tempfile.TemporaryFile(mode="w+b", buffering=0)
    full_stderr.write(b"captured stderr\n")
    post_exit = types.SimpleNamespace(
        stdout_data=bytearray(b"captured stdout\n"),
        stderr_data=bytearray(b"captured stderr\n"),
        output_capture_complete=True,
        output_capture_reason=None,
        output_spools=(short_stdout, full_stderr, [False, False]),
    )
    stdout_bytes, stderr_bytes = io.BytesIO(), io.BytesIO()
    stdout_text = io.TextIOWrapper(stdout_bytes, encoding="utf-8")
    stderr_text = io.TextIOWrapper(stderr_bytes, encoding="utf-8")
    with contextlib.redirect_stdout(stdout_text), contextlib.redirect_stderr(stderr_text):
        s0cache_module.replay_spooled_output(post_exit)
    assert stdout_bytes.getvalue() == b"captured stdout\n"
    assert stderr_bytes.getvalue() == b"captured stderr\n"
    assert not post_exit.output_capture_complete
    assert post_exit.output_capture_reason == "spool-replay"

    class MemoryPipe:
        def __init__(self, data):
            self.data = data

        def read1(self, _size):
            data, self.data = self.data, b""
            return data

        def close(self):
            pass

    # If starting the second pipe reader fails, the wrapper must kill and reap the
    # compiler and join the first reader instead of leaving background work behind.
    with tempfile.TemporaryDirectory(prefix="s0cache-reader-start-failure-") as temp:
        root = pathlib.Path(temp)
        child = root / "noisy-child.py"
        pid_file = root / "child.pid"
        child.write_text(
            "import os\n"
            "open(os.environ['PID_FILE'], 'w').write(str(os.getpid()))\n"
            "while True:\n"
            "    os.write(1, b'O' * 65536)\n"
            "    os.write(2, b'E' * 65536)\n"
        )
        original_threading = s0cache_module.s0cache_spool.threading
        started_readers = []

        class FailSecondThread(original_threading.Thread):
            starts = 0

            def start(self):
                type(self).starts += 1
                if type(self).starts == 2:
                    deadline = time.monotonic() + 2
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.005)
                    raise RuntimeError("injected second-reader start failure")
                super().start()
                started_readers.append(self)

        s0cache_module.s0cache_spool.threading = types.SimpleNamespace(Thread=FailSecondThread)
        env = os.environ.copy()
        env["PID_FILE"] = str(pid_file)
        stdout_text = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        stderr_text = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        try:
            with contextlib.redirect_stdout(stdout_text), contextlib.redirect_stderr(stderr_text):
                try:
                    s0cache_module.run_spooled(sys.executable, [str(child)], env)
                except RuntimeError as error:
                    assert str(error) == "injected second-reader start failure"
                else:
                    raise AssertionError("reader startup failure was not propagated")
        finally:
            s0cache_module.s0cache_spool.threading = original_threading
        assert started_readers and all(not reader.is_alive() for reader in started_readers)
        child_pid = int(pid_file.read_text())
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("compiler process survived reader startup failure")

    class PartialSink:
        def __init__(self):
            self.output = bytearray()

        def write(self, data):
            chunk = bytes(data[:2])
            self.output.extend(chunk)
            return len(chunk)

        def flush(self):
            pass

    partial_sink = PartialSink()
    partial_capture_state = ["output-limit"]
    s0cache_module._drain_child_stream(
        MemoryPipe(b"abcdef"), None, partial_sink,
        partial_capture_state, [True], [4], bytearray(b"abcd"),
    )
    assert partial_sink.output == b"abcdef"
    assert partial_capture_state[0] == "output-limit"

    class TruncatedOnReplaySpool:
        def __init__(self):
            self.file = tempfile.TemporaryFile(mode="w+b", buffering=0)

        def write(self, data):
            return self.file.write(data)

        def fileno(self):
            self.file.truncate(max(0, self.file.tell() - 1))
            return self.file.fileno()

        def seek(self, *args):
            return self.file.seek(*args)

        def read(self, *args):
            return self.file.read(*args)

        def close(self):
            self.file.close()

    saved_output_limit = s0cache_module.s0cache_spool.CACHE_TEXT_MAX_BYTES
    s0cache_module.s0cache_spool.CACHE_TEXT_MAX_BYTES = 4
    live_spool = TruncatedOnReplaySpool()
    try:
        live_sink = io.BytesIO()
        live_capture_state = [None]
        live_replayed = [False]
        live_size = [0]
        live_prefix = bytearray()
        s0cache_module._drain_child_stream(
            MemoryPipe(b"abcdef"), live_spool, live_sink,
            live_capture_state, live_replayed, live_size, live_prefix,
        )
        assert live_sink.getvalue() == b"abcdef"
        assert live_prefix == b"abcd"
        assert live_capture_state[0] == "spool-replay"
        assert live_replayed[0]
    finally:
        live_spool.close()
        s0cache_module.s0cache_spool.CACHE_TEXT_MAX_BYTES = saved_output_limit

