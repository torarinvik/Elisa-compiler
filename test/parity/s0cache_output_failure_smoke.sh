#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 - "$ROOT/tools/s0cache" <<'PY'
import os
import pathlib
import subprocess
import sys
import tempfile

wrapper = pathlib.Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix="s0cache-output-failure-") as temp:
    root = pathlib.Path(temp)
    compiler = root / "fake-stage0"
    calls = root / "calls"
    compiler.write_text(
        "#!/usr/bin/env python3\n"
        "import hashlib, json, os, pathlib, shutil, sys\n"
        "with open(os.environ['FAKE_CALLS'], 'a') as f: f.write('call\\n')\n"
        "if os.environ.get('FAKE_NO_CERT') != '1' and os.environ.get('ELISACORE_CACHE_CERTIFICATE'):\n"
        "    solver = pathlib.Path(shutil.which('z3')).resolve()\n"
        "    digest = hashlib.sha256(solver.read_bytes()).hexdigest()\n"
        "    cert = {'version': 3, 'pid': os.getpid(), 'dependencies': [{'path': str(solver), 'sha256': digest}]}\n"
        "    pathlib.Path(os.environ['ELISACORE_CACHE_CERTIFICATE']).write_text(json.dumps(cert))\n"
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
        "REPO_ROOT": str(root),
        "FAKE_CALLS": str(calls),
        "FAKE_EXIT": "1",
    })
    # This selector is special: even an empty value changes Core's retained-server
    # routing, and s0cache bypasses whenever it is present.
    env.pop("ELISACORE_RETAINED_SERVER", None)
    for name in (
        "ELISA_BACKEND_PARITY_OUT", "ELISA_PARSER_PARITY_OUT", "ELISA_SEMANTIC_PARITY_OUT",
        "ELISA_SEMANTIC_INTERNAL_PARITY_OUT", "ELISACORE_EMIT_LL", "ELISA_KEEP_TEST_BINARY",
        "ELISACORE_DUMP_MODULE_ON_VERIFY_FAILURE", "ELISACORE_KEEP_TEST_TEMP",
        "ELISACORE_BUILD_TIMING", "ELISACORE_TEST_TIMING", "ELISACORE_CACHE_DEBUG",
        "ELISACORE_TEST_CACHE_DEBUG", "ELISACORE_TEST_PHASE_DEBUG", "ELISACORE_CPUPROFILE",
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

print("s0cache preserves output state and avoids path and marker corruption")
PY
