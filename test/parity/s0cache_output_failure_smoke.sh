#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 - "$ROOT/tools/s0cache" <<'PY'
import os
import pathlib
import contextlib
import importlib.machinery
import importlib.util
import io
import subprocess
import sys
import tempfile
import time
import types

wrapper = pathlib.Path(sys.argv[1])

# Exercise the replay fallback directly with an injectable spool seek failure.
loader = importlib.machinery.SourceFileLoader("s0cache_test_module", str(wrapper))
spec = importlib.util.spec_from_loader(loader.name, loader)
s0cache_module = importlib.util.module_from_spec(spec)
loader.exec_module(s0cache_module)

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
    original_threading = s0cache_module.threading
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

    s0cache_module.threading = types.SimpleNamespace(Thread=FailSecondThread)
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
        s0cache_module.threading = original_threading
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

saved_output_limit = s0cache_module.CACHE_TEXT_MAX_BYTES
s0cache_module.CACHE_TEXT_MAX_BYTES = 4
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
    s0cache_module.CACHE_TEXT_MAX_BYTES = saved_output_limit

with tempfile.TemporaryDirectory(prefix="s0cache-output-failure-") as temp:
    root = pathlib.Path(temp)
    compiler = root / "fake-stage0"
    calls = root / "calls"
    compiler.write_text(
        "#!/usr/bin/env python3\n"
        "import hashlib, json, os, pathlib, sys\n"
        "with open(os.environ['FAKE_CALLS'], 'a') as f: f.write('call\\n')\n"
        "if os.environ.get('FAKE_NO_CERT') != '1' and os.environ.get('ELISACORE_CACHE_CERTIFICATE'):\n"
        "    solver = pathlib.Path(sys.argv[0]).resolve()\n"
        "    digest = hashlib.sha256(solver.read_bytes()).hexdigest()\n"
        "    pid = True if os.environ.get('FAKE_CERT_BOOL_PID') == '1' else os.getpid()\n"
        "    cert = {'version': 3, 'pid': pid, 'dependencies': [{'path': str(solver), 'sha256': digest}]}\n"
        "    pathlib.Path(os.environ['ELISACORE_CACHE_CERTIFICATE']).write_text(json.dumps(cert))\n"
        "if os.environ.get('FAKE_LARGE_OUTPUT'):\n"
        "    size = int(os.environ['FAKE_LARGE_OUTPUT'])\n"
        "    sys.stdout.buffer.write(b'O' * size)\n"
        "    sys.stderr.buffer.write(b'E' * size)\n"
        "if os.environ.get('FAKE_EDIT_SOURCE') == '1':\n"
        "    pathlib.Path(sys.argv[-1]).write_text('modified during compiler run\\n')\n"
        "if os.environ.get('FAKE_STDOUT_SOURCE') == '1':\n"
        "    sys.stdout.buffer.write(pathlib.Path(sys.argv[-1]).read_bytes())\n"
        "if os.environ.get('FAKE_STDOUT_MARKER') == '1':\n"
        "    sys.stdout.buffer.write(b'literal\\x00s0cache:in\\x00and\\x00s0cache:dir\\x00')\n"
        "if os.environ.get('FAKE_WRITE_OUTPUT') == '1':\n"
        "    args = sys.argv[1:]\n"
        "    source = pathlib.Path(sys.argv[-1]).resolve()\n"
        "    payload = b'new artifact'\n"
        "    if os.environ.get('FAKE_EMBED_PATHS') == '1':\n"
        "        payload = b'input=' + str(source).encode() + b'\\x00s0cache:in\\x00dir=' + str(source.parent).encode() + b'\\x00s0cache:dir\\x00'\n"
        "    if '-o' in args:\n"
        "        output = args[args.index('-o') + 1]\n"
        "    else:\n"
        "        output = next((arg[3:] for arg in args if arg.startswith('-o=')), str(source.with_suffix('.o')))\n"
        "    pathlib.Path(output).write_bytes(payload)\n"
        "sys.exit(int(os.environ.get('FAKE_EXIT', '1')))\n"
    )
    compiler.chmod(0o755)
    source = root / "input.elisa"
    source.write_text("def rejected() -> i64:\n    return 0\n")
    cache = root / "cache"
    env = os.environ.copy()
    env.update({
        "ELISA_S0_REAL": str(compiler),
        "ELISA_S0_CACHE_DIR": str(cache),
        "ELISA_S0_CACHE": "1",
        "ELISA_S0_CACHE_STATS": str(root / "stats"),
        "ELISA_LD": "",
        "ELISACORE_CODEGEN_JOBS": "1",
        "REPO_ROOT": str(root),
        "PATH": os.pathsep.join(filter(None, ("/usr/bin", "/bin", os.environ.get("PATH", "")))),
        "FAKE_CALLS": str(calls),
        "FAKE_EXIT": "1",
    })
    # This selector is special: even an empty value changes Core's retained-server
    # routing, and s0cache bypasses whenever it is present.
    env.pop("ELISACORE_RETAINED_SERVER", None)
    env.pop("ELISACORE_CACHE_CERTIFICATE", None)
    for name in (
        "ELISA_BACKEND_PARITY_OUT", "ELISA_PARSER_PARITY_OUT", "ELISA_SEMANTIC_PARITY_OUT",
        "ELISA_SEMANTIC_INTERNAL_PARITY_OUT", "ELISACORE_EMIT_LL", "ELISA_KEEP_TEST_BINARY",
        "ELISACORE_DUMP_MODULE_ON_VERIFY_FAILURE", "ELISACORE_KEEP_TEST_TEMP",
        "ELISACORE_BUILD_TIMING", "ELISACORE_TEST_TIMING", "ELISACORE_CACHE_DEBUG",
        "ELISACORE_TEST_CACHE_DEBUG", "ELISACORE_TEST_PHASE_DEBUG",
        "ELISACORE_PARTITION_DECLINE_DEBUG", "ELISACORE_CPUPROFILE",
        "ELISACORE_MEMPROFILE", "ELISACORE_BLOCKPROFILE", "ELISACORE_GOROUTINEPROFILE",
        "ELISACORE_RETAINED_FAST_PREPARE", "ELISACORE_RETAINED_PROFILE_DIR",
        "ELISACORE_RETAINED_HEAPPROFILE",
        "ELISA_SMT_RLIMIT_LOG", "ELISA_SMT_TRACE", "ELISA_SMT_PREAMBLE_SHADOW",
        "ELISA_REGION_FIXPOINT_SHADOW", "ELISA_TRACKED_SHARE_CHECK",
        "ELISA_INCREMENTAL_SHADOW", "ELISA_INCREMENTAL_SHADOW_REPORT",
        "ELISA_STAGE1_INCREMENTAL_CACHE_REPORT", "ELISA_STAGE1_LINE_MAP_OUTPUT",
    ):
        env[name] = ""

    stale = root / "stale.o"
    stale.write_bytes(b"old artifact")
    first = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", "-o", str(stale), str(source)],
        env=env, check=False,
    )
    assert first.returncode == 1
    assert stale.read_bytes() == b"old artifact", "rejection changed the preexisting output"

    absent = root / "absent.o"
    second = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", "-o", str(absent), str(source)],
        env=env, check=False,
    )
    assert second.returncode == 1
    assert not absent.exists(), "rejection replayed the stale artifact to a new output path"
    assert calls.read_text().splitlines() == ["call", "call"], "output rejection was replayed from cache"

    bad_cache_root = root / "cache-root-file"
    bad_cache_root.write_text("not a directory")
    bad_env = env.copy()
    bad_env["ELISA_S0_CACHE_DIR"] = str(bad_cache_root)
    third = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "tokens", str(source)],
        env=bad_env, check=False,
    )
    assert third.returncode == 1
    assert calls.read_text().splitlines() == ["call", "call", "call"], "cache-root error stopped the real compiler"

    include_source = root / "include-root.elisa"
    include_source.write_text('def root():\n    pass\n  {$include "child.elisa"}  \n')
    include_child = root / "child.elisa"
    for child_text in ("first dependency\n", "changed dependency\n"):
        include_child.write_text(child_text)
        included = subprocess.run(
            [sys.executable, str(wrapper), "-emit", "tokens", str(include_source)],
            env=env, check=False,
        )
        assert included.returncode == 1
    assert calls.read_text().splitlines() == ["call"] * 5, "trimmed Pascal include was omitted from the cache key"

    success_env = env.copy()
    success_env["FAKE_EXIT"] = "0"
    missing = root / "missing-success.o"
    for _ in range(2):
        success = subprocess.run(
            [sys.executable, str(wrapper), "-emit", "obj", "-o", str(missing), str(source)],
            env=success_env, check=False,
        )
        assert success.returncode == 0
        assert not missing.exists(), "successful no-artifact response changed the output"
    assert calls.read_text().splitlines() == ["call"] * 7, "success without an artifact was incorrectly cached"

    stale_success = root / "stale-success.o"
    stale_success.write_bytes(b"old successful-path artifact")
    for _ in range(2):
        success = subprocess.run(
            [sys.executable, str(wrapper), "-emit", "obj", "-o", str(stale_success), str(source)],
            env=success_env, check=False,
        )
        assert success.returncode == 0
        assert stale_success.read_bytes() == b"old successful-path artifact"
    assert calls.read_text().splitlines() == ["call"] * 9, "unchanged preexisting output was incorrectly cached"

    artifact_env = success_env.copy()
    artifact_env["FAKE_WRITE_OUTPUT"] = "1"
    artifact_env["FAKE_EMBED_PATHS"] = "1"
    cached = root / "cached.o"
    expected_artifact = (
        b"input=" + str(source.resolve()).encode() + b"\x00s0cache:in\x00dir="
        + str(source.parent.resolve()).encode() + b"\x00s0cache:dir\x00"
    )
    first_success = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", "-o", str(cached), str(source)],
        env=artifact_env, check=False,
    )
    assert first_success.returncode == 0 and cached.read_bytes() == expected_artifact
    cached.unlink()
    replayed_success = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", "-o", str(cached), str(source)],
        env=artifact_env, check=False,
    )
    assert replayed_success.returncode == 0 and cached.read_bytes() == expected_artifact
    assert calls.read_text().splitlines() == ["call"] * 10, "successful artifact was not safely cached"

    other_source = root / "other.elisa"
    other_source.write_text(source.read_text())
    other_output = root / "other.o"
    other_expected = (
        b"input=" + str(other_source.resolve()).encode() + b"\x00s0cache:in\x00dir="
        + str(other_source.parent.resolve()).encode() + b"\x00s0cache:dir\x00"
    )
    other_result = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", "-o", str(other_output), str(other_source)],
        env=artifact_env, check=False,
    )
    assert other_result.returncode == 0 and other_output.read_bytes() == other_expected
    assert calls.read_text().splitlines() == ["call"] * 11, "binary result ignored its source path identity"

    implicit_source = root / "implicit.elisa"
    implicit_source.write_text(source.read_text())
    implicit_output = implicit_source.with_suffix(".o")
    implicit_expected = (
        b"input=" + str(implicit_source.resolve()).encode() + b"\x00s0cache:in\x00dir="
        + str(implicit_source.parent.resolve()).encode() + b"\x00s0cache:dir\x00"
    )
    implicit_first = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", str(implicit_source)],
        env=artifact_env, check=False,
    )
    assert implicit_first.returncode == 0 and implicit_output.read_bytes() == implicit_expected
    implicit_output.unlink()
    implicit_replay = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", str(implicit_source)],
        env=artifact_env, check=False,
    )
    assert implicit_replay.returncode == 0 and implicit_output.read_bytes() == implicit_expected
    assert calls.read_text().splitlines() == ["call"] * 12, "implicit binary output was not restored from cache"

    equals_source = root / "equals.elisa"
    equals_source.write_text(source.read_text())
    equals_output = root / "equals.o"
    equals_expected = (
        b"input=" + str(equals_source.resolve()).encode() + b"\x00s0cache:in\x00dir="
        + str(equals_source.parent.resolve()).encode() + b"\x00s0cache:dir\x00"
    )
    equals_first = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", "-o=" + str(equals_output), str(equals_source)],
        env=artifact_env, check=False,
    )
    assert equals_first.returncode == 0 and equals_output.read_bytes() == equals_expected
    equals_output.unlink()
    equals_replay = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", "-o=" + str(equals_output), str(equals_source)],
        env=artifact_env, check=False,
    )
    assert equals_replay.returncode == 0 and equals_output.read_bytes() == equals_expected
    assert calls.read_text().splitlines() == ["call"] * 13, "-o= output was not restored from cache"

    literal_dir = root / "literal-one"
    other_literal_dir = root / "literal-two"
    literal_dir.mkdir()
    other_literal_dir.mkdir()
    literal = ("def value() -> sview:\n    return \"" + str(literal_dir.resolve()) + "\"\n").encode()
    literal_source = literal_dir / "probe.elisa"
    other_literal_source = other_literal_dir / "probe.elisa"
    literal_source.write_bytes(literal)
    other_literal_source.write_bytes(literal)
    literal_env = env.copy()
    literal_env["FAKE_EXIT"] = "0"
    literal_env["FAKE_STDOUT_SOURCE"] = "1"
    literal_first = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "tokens", str(literal_source)],
        env=literal_env, check=False, capture_output=True,
    )
    assert literal_first.returncode == 0 and literal_first.stdout == literal
    literal_replay = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "tokens", str(literal_source)],
        env=literal_env, check=False, capture_output=True,
    )
    assert literal_replay.returncode == 0 and literal_replay.stdout == literal
    assert calls.read_text().splitlines() == ["call"] * 14, "path normalization changed a source literal on replay"
    other_literal = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "tokens", str(other_literal_source)],
        env=literal_env, check=False, capture_output=True,
    )
    assert other_literal.returncode == 0 and other_literal.stdout == literal
    assert calls.read_text().splitlines() == ["call"] * 15, "literal path source reused another directory's textual result"

    marker_env = env.copy()
    marker_env["FAKE_EXIT"] = "0"
    marker_env["FAKE_STDOUT_MARKER"] = "1"
    marker_source = root / "marker.elisa"
    marker_source.write_text(source.read_text())
    for _ in range(2):
        marker_result = subprocess.run(
            [sys.executable, str(wrapper), "-emit", "tokens", str(marker_source)],
            env=marker_env, check=False, capture_output=True,
        )
        assert marker_result.returncode == 0
        assert marker_result.stdout == b"literal\x00s0cache:in\x00and\x00s0cache:dir\x00"
    assert calls.read_text().splitlines() == ["call"] * 17, "literal placeholder marker was replayed as a path"

    safety_cache = root / "safety-cache"
    safety_env = env.copy()
    safety_env["ELISA_S0_CACHE_DIR"] = str(safety_cache)
    safety_env["FAKE_EXIT"] = "0"
    safety_source = root / "safety.elisa"
    safety_source.write_text(source.read_text())
    initial_safety = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "tokens", str(safety_source)],
        env=safety_env, check=False, timeout=3,
    )
    assert initial_safety.returncode == 0
    assert calls.read_text().splitlines() == ["call"] * 18
    safety_entries = [
        entry
        for shard in safety_cache.iterdir()
        if shard.is_dir() and len(shard.name) == 2
        for entry in shard.iterdir()
        if entry.is_dir()
    ]
    assert len(safety_entries) == 1
    safety_entry = safety_entries[0]

    (safety_entry / "rc").write_text("256")
    safety_env["FAKE_EXIT"] = "1"
    invalid_status = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "tokens", str(safety_source)],
        env=safety_env, check=False, timeout=3,
    )
    assert invalid_status.returncode == 1
    assert calls.read_text().splitlines() == ["call"] * 19, "invalid cached status was treated as success"

    (safety_entry / "out").unlink()
    os.mkfifo(safety_entry / "out")
    special_file = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "tokens", str(safety_source)],
        env=safety_env, check=False, timeout=3,
    )
    assert special_file.returncode == 1
    assert calls.read_text().splitlines() == ["call"] * 20, "special cache payload was read instead of bypassed"

    # A compiler that cannot certify its answer (including an older binary)
    # must run again, even when it otherwise produces a cacheable response.
    uncertified_source = root / "uncertified.elisa"
    uncertified_source.write_text("uncertified fixture\n")
    uncertified_env = env.copy()
    uncertified_env.update(FAKE_NO_CERT="1", FAKE_EXIT="0")
    before = len(calls.read_text().splitlines())
    for _ in range(2):
        result = subprocess.run([sys.executable, str(wrapper), "-emit", "tokens",
                                 str(uncertified_source)], env=uncertified_env,
                                capture_output=True, check=False)
        assert result.returncode == 0
    assert len(calls.read_text().splitlines()) == before + 2, "uncertified result was cached"

    # A changed native environment must select a different result even when
    # the input and compiler binary are unchanged.
    native_source = root / "native-environment.elisa"
    native_source.write_text("native environment fixture\n")
    native_env = env.copy()
    native_env.update(FAKE_EXIT="0", FAKE_WRITE_OUTPUT="1", C_INCLUDE_PATH="first-include")
    before = len(calls.read_text().splitlines())
    args = [sys.executable, str(wrapper), "-emit", "obj", "-o", str(root / "native.o"), str(native_source)]
    assert subprocess.run(args, env=native_env, check=False).returncode == 0
    assert subprocess.run(args, env=native_env, check=False).returncode == 0
    native_env["C_INCLUDE_PATH"] = "second-include"
    assert subprocess.run(args, env=native_env, check=False).returncode == 0
    assert len(calls.read_text().splitlines()) == before + 2, "native environment change reused cache"

    partition_debug_cache = root / "partition-debug-cache"
    partition_debug_env = env.copy()
    partition_debug_env.update(
        ELISA_S0_CACHE_DIR=str(partition_debug_cache),
        FAKE_EXIT="0",
    )
    partition_debug_source = root / "partition-debug.elisa"
    partition_debug_source.write_text("partition debug fixture\n")
    before = len(calls.read_text().splitlines())
    debug_args = [sys.executable, str(wrapper), "-emit", "tokens", str(partition_debug_source)]
    assert subprocess.run(debug_args, env=partition_debug_env, check=False).returncode == 0
    partition_debug_env["ELISACORE_PARTITION_DECLINE_DEBUG"] = "1"
    assert subprocess.run(debug_args, env=partition_debug_env, check=False).returncode == 0
    assert len(calls.read_text().splitlines()) == before + 2, "partition debug output was served from cache"
    assert (root / "stats").read_text().splitlines()[-1] == (
        "bypass\ttokens\tenv:ELISACORE_PARTITION_DECLINE_DEBUG"
    )

    # A JSON boolean is not an integer process id and must not certify a response.
    bool_pid_source = root / "bool-pid.elisa"
    bool_pid_source.write_text("bool pid certificate fixture\n")
    bool_pid_env = env.copy()
    bool_pid_env.update(FAKE_CERT_BOOL_PID="1", FAKE_EXIT="0")
    before = len(calls.read_text().splitlines())
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(wrapper), "-emit", "tokens", str(bool_pid_source)],
            env=bool_pid_env, check=False, capture_output=True,
        )
        assert result.returncode == 0
    assert len(calls.read_text().splitlines()) == before + 2, "boolean certificate PID was accepted"

    # If a source changes while the child runs, its result must not be stored
    # under the earlier content key, even if the original bytes later return.
    changing_source = root / "changing-source.elisa"
    original_source_text = "source snapshot fixture\n"
    changing_source.write_text(original_source_text)
    changing_env = env.copy()
    changing_env.update(FAKE_EDIT_SOURCE="1", FAKE_EXIT="0")
    before = len(calls.read_text().splitlines())
    first_changed = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "tokens", str(changing_source)],
        env=changing_env, check=False, capture_output=True,
    )
    assert first_changed.returncode == 0
    assert changing_source.read_text() == "modified during compiler run\n"
    changing_source.write_text(original_source_text)
    changing_env.pop("FAKE_EDIT_SOURCE")
    second_changed = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "tokens", str(changing_source)],
        env=changing_env, check=False, capture_output=True,
    )
    assert second_changed.returncode == 0
    assert len(calls.read_text().splitlines()) == before + 2, "changed source was cached under an earlier snapshot"

    # Output larger than the cache bound is replayed exactly from disk and is
    # recomputed on the next call, without materializing either full stream.
    large_source = root / "large-output.elisa"
    large_source.write_text("large output fixture\n")
    large_env = env.copy()
    large_size = (16 << 20) + 1
    large_env.update(FAKE_LARGE_OUTPUT=str(large_size), FAKE_EXIT="0")
    before = len(calls.read_text().splitlines())

    def assert_repeated_bytes(stream, byte, size):
        stream.seek(0)
        total = 0
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            assert chunk == byte * len(chunk)
            total += len(chunk)
        assert total == size

    for _ in range(2):
        with tempfile.TemporaryFile() as large_stdout, tempfile.TemporaryFile() as large_stderr:
            result = subprocess.run(
                [sys.executable, str(wrapper), "-emit", "tokens", str(large_source)],
                env=large_env, check=False, stdout=large_stdout, stderr=large_stderr,
            )
            assert result.returncode == 0
            assert_repeated_bytes(large_stdout, b"O", large_size)
            assert_repeated_bytes(large_stderr, b"E", large_size)
    assert len(calls.read_text().splitlines()) == before + 2, "oversized output was incorrectly cached"

    # The wrapper cannot infer Go's runtime.NumCPU default exactly on every
    # host. Object-mode calls without a valid explicit count must reach Core,
    # whose inner object cache keys the resolved worker count.
    default_jobs_source = root / "default-codegen-jobs.elisa"
    default_jobs_source.write_text("default worker count fixture\n")
    invalid_jobs_source = root / "invalid-codegen-jobs.elisa"
    invalid_jobs_source.write_text("invalid worker count fixture\n")
    for label, source_path, setting in (
        ("unset", default_jobs_source, None),
        ("overflow", invalid_jobs_source, str(sys.maxsize + 1)),
    ):
        jobs_env = env.copy()
        if setting is None:
            jobs_env.pop("ELISACORE_CODEGEN_JOBS", None)
        else:
            jobs_env["ELISACORE_CODEGEN_JOBS"] = setting
        jobs_env.update(FAKE_EXIT="0", FAKE_WRITE_OUTPUT="1")
        output_path = root / (label + "-codegen-jobs.o")
        before = len(calls.read_text().splitlines())
        result = subprocess.run(
            [sys.executable, str(wrapper), "-emit", "obj", "-o", str(output_path), str(source_path)],
            env=jobs_env, check=False,
        )
        assert result.returncode == 0 and output_path.read_bytes() == b"new artifact"
        assert len(calls.read_text().splitlines()) == before + 1, "implicit worker count skipped Core"
        assert (root / "stats").read_text().splitlines()[-1] == (
            "bypass\tobj\timplicit-codegen-jobs"
        )

    launcher_source = root / "linker-launcher.elisa"
    launcher_source.write_text("linker launcher fixture\n")
    for index, command in enumerate(("env /custom/ld", "ccache ld", "custom-ld")):
        launcher_env = env.copy()
        launcher_env.update(ELISA_LD=command, FAKE_EXIT="0", FAKE_WRITE_OUTPUT="1")
        output_path = root / ("linker-launcher-%d.o" % index)
        before = len(calls.read_text().splitlines())
        result = subprocess.run(
            [sys.executable, str(wrapper), "-emit", "obj", "-o", str(output_path), str(launcher_source)],
            env=launcher_env, check=False,
        )
        assert result.returncode == 0 and output_path.read_bytes() == b"new artifact"
        assert len(calls.read_text().splitlines()) == before + 1, "linker launcher skipped Core"
        assert (root / "stats").read_text().splitlines()[-1] == (
            "bypass\tobj\telisa-ld-override"
        )

    script_linker_bin = root / "script-linker-bin"
    script_linker_bin.mkdir()
    script_linker = script_linker_bin / "ld"
    script_linker.write_text("#!/bin/sh\nexit 0\n")
    script_linker.chmod(0o755)
    script_linker_env = env.copy()
    script_linker_env.update(ELISA_LD="", FAKE_EXIT="0", FAKE_WRITE_OUTPUT="1",
                             PATH=str(script_linker_bin) + os.pathsep + env["PATH"])
    script_linker_output = root / "script-default-ld.o"
    before = len(calls.read_text().splitlines())
    script_linker_result = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", "-o", str(script_linker_output), str(launcher_source)],
        env=script_linker_env, check=False,
    )
    assert script_linker_result.returncode == 0 and script_linker_output.read_bytes() == b"new artifact"
    assert len(calls.read_text().splitlines()) == before + 1, "default linker script skipped Core"
    assert (root / "stats").read_text().splitlines()[-1] == (
        "bypass\tobj\tlinker-wrapper"
    )

    compiled_linker_bin = root / "compiled-linker-bin"
    compiled_linker_bin.mkdir()
    compiled_linker = compiled_linker_bin / "ld"
    compiled_linker.write_bytes(b"\x7fELF" + b"\x00" * 12)
    compiled_linker.chmod(0o755)
    compiled_linker_env = env.copy()
    compiled_linker_env.update(ELISA_LD="", FAKE_EXIT="0", FAKE_WRITE_OUTPUT="1",
                               PATH=str(compiled_linker_bin) + os.pathsep + env["PATH"])
    compiled_linker_output = root / "compiled-default-ld.o"
    before = len(calls.read_text().splitlines())
    compiled_linker_result = subprocess.run(
        [sys.executable, str(wrapper), "-emit", "obj", "-o", str(compiled_linker_output), str(launcher_source)],
        env=compiled_linker_env, check=False,
    )
    assert compiled_linker_result.returncode == 0 and compiled_linker_output.read_bytes() == b"new artifact"
    assert len(calls.read_text().splitlines()) == before + 1, "default PATH launcher skipped Core"
    assert (root / "stats").read_text().splitlines()[-1] == (
        "bypass\tobj\tlinker-wrapper"
    )

print("s0cache preserves output state and avoids path and marker corruption")
PY
