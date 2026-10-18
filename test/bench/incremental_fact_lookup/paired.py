#!/usr/bin/env python3
"""Exploratory paired full-process warm incremental checks; never cold compile timing."""
import argparse
import atexit
import csv
import fcntl
import hashlib
import json
import math
import os
import platform
import re
import resource
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("parent_root", type=Path)
parser.add_argument("parent_binary", type=Path)
parser.add_argument("candidate_root", type=Path)
parser.add_argument("candidate_binary", type=Path)
parser.add_argument("corpus", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--pairs", type=int, default=7)
parser.add_argument("--timeout-seconds", type=int, default=900,
                    help="per-compiler-process timeout; kills its process group")
args = parser.parse_args()
if args.pairs < 1: parser.error("pairs must be positive")
if args.timeout_seconds < 1: parser.error("timeout-seconds must be positive")
# Share the cross-language runner's host lease so independent timing suites cannot
# overlap while both individually pass the load gate.
host_lock_path = Path(os.environ.get("ELISA_BENCH_LOCK_PATH") or "/tmp/elisa-cross-language-benchmark.lock")
host_lock_fd = os.open(host_lock_path, os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(host_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    os.close(host_lock_fd)
    parser.error(f"another compiler benchmark holds the host lock at {host_lock_path}")
args.output = args.output.resolve()
args.output.mkdir(parents=True, exist_ok=True)
if any(args.output.iterdir()):
    parser.error(f"output directory is not empty: {args.output}")
run_completed = False

def mark_incomplete_run():
    if run_completed or (args.output / "COMPLETE").exists() or (args.output / "ABORTED.txt").exists():
        return
    try:
        (args.output / "ABORTED.txt").write_text(
            "ABORTED — runner exited before completing the paired experiment.\n"
            "Any partial outputs and measurements from this run are unusable.\n"
        )
    except OSError as error:
        print(f"could not write ABORTED.txt: {error}", file=sys.stderr)

atexit.register(mark_incomplete_run)
products = {"parent": (args.parent_root.resolve(), args.parent_binary.resolve()), "candidate": (args.candidate_root.resolve(), args.candidate_binary.resolve())}
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def checked(command): return subprocess.check_output(command, text=True).strip()
def platform_environment(root):
    env = os.environ.copy()
    env.pop("ELISA_PLATFORM_SOURCED", None)
    if sys_platform_is_darwin():
        for key in ("LLVM_CONFIG", "ELISA_LLVM_BIN_DIR", "ELISA_LLVM_LIBDIR", "ELISA_LLVM_LIBS", "ELISA_CLANG"):
            env.pop(key, None)
    result = subprocess.run(
        ["bash", "-c", 'source "$1/scripts/platform.sh" && env -0', "_", str(root)],
        env=env,
        capture_output=True,
        check=True,
    )
    for entry in result.stdout.split(b"\0"):
        if b"=" in entry:
            key, value = entry.split(b"=", 1)
            env[key.decode()] = value.decode()
    return env

def sys_platform_is_darwin():
    return platform.system() == "Darwin"

def inputs(root, env, binary):
    return subprocess.check_output(
        [
            "python3",
            str(root / "scripts/stage1_provenance.py"),
            "inputs",
            str(root),
            str(Path(str(binary) + ".provenance.json")),
        ],
        text=True,
        env=env,
    ).strip()
def linked_llvm(binary):
    rows = checked(["otool", "-L", str(binary)]).splitlines()
    return Path(next(row.strip().split(" (", 1)[0] for row in rows if "libLLVM" in row)).resolve()
pins, fingerprints, libraries = {}, {}, {}
# Resolve one Homebrew toolchain from the benchmark checkout. The parent source tree may
# carry an older platform.sh, but both products must be checked against the same current LLVM.
benchmark_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(benchmark_root / "scripts"))
counter_helper = benchmark_root / "test/bench/codegen_perf"
sys.path.insert(0, str(counter_helper))
from bench_load_gate import (
    LoadGateError,
    check_load_gate,
    load_average,
    wait_for_sustained_load_gate,
)
from process_counter import (
    METHOD_DESCRIPTION as COUNTER_METHOD,
    new_report_path,
    read_report,
    wrap_command,
)

system = platform.system()
host_qualification = args.output / "host_qualification.json"
if system == "Darwin":
    host_qualification.write_text(json.dumps({
        "system": "Darwin",
        "machine": platform.machine(),
        "qualified": False,
        "reason": "macOS paired timings are exploratory",
    }, indent=2, sort_keys=True) + "\n")
else:
    parser.error(
        f"the paired incremental runner is exploratory macOS-only; use "
        f"cross_language.sh for qualified Linux timing (current platform: {system})"
    )

selected_toolchain_env = platform_environment(benchmark_root)
toolchain_envs = {arm: selected_toolchain_env.copy() for arm in products}
for arm, (root, binary) in products.items():
    subprocess.run(["python3", str(root / "scripts/stage1_provenance.py"), "check-exact", str(root), str(binary)], check=True, env=toolchain_envs[arm])
    fingerprints[arm] = inputs(root, toolchain_envs[arm], binary)
    libraries[arm] = linked_llvm(binary)
    for path in [binary, Path(str(binary) + ".provenance.json")]: pins[str(path)] = digest(path)
if libraries['parent'] != libraries['candidate']:
    raise RuntimeError(f"parent/candidate LLVM libraries differ: {libraries}")
pins[str(libraries['parent'])] = digest(libraries['parent'])
manifest = json.loads((args.corpus / "manifest.json").read_text())
pins[str((args.corpus / 'manifest.json').resolve())] = digest(args.corpus / 'manifest.json')
for workload in manifest['workloads']:
    for filename in workload['sha256']:
        path = (args.corpus / workload['directory'] / filename).resolve()
        pins[str(path)] = digest(path)
for path in {
    Path(__file__).resolve(),
    benchmark_root / "scripts/platform.sh",
    benchmark_root / "scripts/bench_load_gate.py",
    benchmark_root / "scripts/stage1_provenance.py",
    counter_helper / "process_counter.py",
    host_qualification,
    *(root / "scripts/platform.sh" for root, _ in products.values()),
    *(root / "scripts/stage1_provenance.py" for root, _ in products.values()),
}:
    resolved = path.resolve()
    pins[str(resolved)] = digest(resolved)
metadata = {
    "status": "exploratory paired full-process warm sidecar-backed incremental checks; not cold compile timing",
    "incremental_reuse_scope": "durable semantic snapshot/fact reuse across fresh ordinary CLI processes; not in-memory query-graph reuse across a persistent compile-server session",
    "fresh_process_per_sample": True,
    "platform": platform.platform(),
    "pairs": args.pairs,
    "benchmark_host_lock": str(host_lock_path),
    "host_qualification": str(host_qualification),
    "host_qualification_sha256": digest(host_qualification),
    "runner_sha256": digest(Path(__file__).resolve()),
    "compiler_process_timeout_seconds": args.timeout_seconds,
    "retired_instruction_counter": COUNTER_METHOD,
    "retired_instruction_counter_scope": "launched compiler process PID, queried with proc_pid_rusage; child tools are excluded",
    "cpu_seconds_scope": "compiler command and terminated descendants, from wait4 user and system time",
    "elisa_force_contracts_inherited": "set" if "ELISACORE_FORCE_CONTRACTS" in os.environ else "unset",
    "elisa_force_contracts_effective": "unset for prime and measured invocations",
    "source_inputs": fingerprints,
    "pinned_input_sha256": pins,
    "corpus": manifest,
}
(args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

def run_compiler(command, env, cwd, *, measure_counters=False):
    report_path = new_report_path(args.output) if measure_counters else None
    measured_command = wrap_command(command, report_path)
    try:
        started = time.perf_counter_ns()
        proc = subprocess.Popen(
            measured_command, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired as error:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(command, args.timeout_seconds, stdout, stderr) from error
        wall_seconds = (time.perf_counter_ns() - started) / 1e9
        result = subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode, command, stdout, stderr)
        return result, read_report(report_path), report_path is not None, wall_seconds
    finally:
        if report_path is not None:
            report_path.unlink(missing_ok=True)

rows = []
report_pattern = re.compile(r"^incremental-ga-cache:.*$", re.MULTILINE)

def enforce_load_gate(stage, *, preflight=False):
    load = load_average()
    try:
        check_load_gate(
            load, stage, args.output, system, host_qualification,
            preflight=preflight,
        )
    except LoadGateError as error:
        raise SystemExit(str(error)) from error
    return load

# This correctness preflight invokes both compiler products on every workload. A passing
# admission check only permits that preparation to begin; exact parity and a second load
# check are still required before any timed pair.
enforce_load_gate("before correctness preflight builds", preflight=True)

def correctness_evidence(workload, source, original, edited, cache_directory, arm):
    root, binary = products[arm]
    env = toolchain_envs[arm].copy()
    for key in ['ELISA_STAGE1_PERMISSIVE', 'ELISA_STAGE1_TIMINGS', 'ELISA_INCREMENTAL_SHADOW', 'ELISA_INCREMENTAL_SHADOW_REPORT', 'ELISA_SEMANTIC_SERIAL', 'ELISACORE_FORCE_CONTRACTS']:
        env.pop(key, None)
    env['ELISA_STAGE1_INCREMENTAL_CACHE_DIR'] = str(cache_directory)
    env['ELISA_STAGE1_INCREMENTAL_CACHE_REPORT'] = '1'
    command = [str(binary), '-emit', 'check', str(source)]
    source.write_bytes(original)
    enforce_load_gate(f"before correctness prime {workload['directory']}/{arm}")
    primed, _, _, _ = run_compiler(command, env, root)
    enforce_load_gate(f"after correctness prime {workload['directory']}/{arm}")
    prime_stderr = primed.stderr.decode()
    prime_reports = report_pattern.findall(prime_stderr)
    prime_clean = report_pattern.sub('', prime_stderr)
    prior_files = list(Path(cache_directory).glob('*.elisa-semantic'))
    if len(prior_files) != 1:
        raise RuntimeError(f"expected one semantic cache snapshot for {arm}, found {prior_files}")
    prior_hash = hashlib.sha256(prior_files[0].read_bytes()).hexdigest()
    source.write_bytes(edited)
    enforce_load_gate(f"before correctness sample {workload['directory']}/{arm}")
    result, _, _, _ = run_compiler(command, env, root)
    enforce_load_gate(f"after correctness sample {workload['directory']}/{arm}")
    stderr = result.stderr.decode()
    reports = report_pattern.findall(stderr)
    if len(reports) != 1 or 'prior=valid' not in reports[0] or 'published=yes' not in reports[0]:
        raise RuntimeError(f"{workload['directory']}/{arm} incremental preflight report mismatch: {reports}")
    expected_matches = 1 if 'supported_helpers' in workload else workload['helpers']
    if not re.search(r' matched=' + str(expected_matches) + r' visited=' + str(workload['functions']) + r' ', reports[0]):
        raise RuntimeError(f"{workload['directory']}/{arm} incremental preflight coverage mismatch: {reports}")
    clean = report_pattern.sub('', stderr)
    return {
        "stdout": result.stdout,
        "stderr_without_report": clean,
        "reports": reports,
        "prime_stdout": primed.stdout,
        "prime_stderr_without_report": prime_clean,
        "prime_reports": prime_reports,
        "prior_snapshot_sha256": prior_hash,
        "prime_exit_status": primed.returncode,
        "edited_exit_status": result.returncode,
    }

preflight = {}
# This phase establishes exact output/diagnostic/cache parity and records no timings. The
# host-load gate below controls admission to the paired experiment after correctness passes.
with tempfile.TemporaryDirectory(prefix="elisa-incremental-preflight-", dir=args.output) as temporary:
    preflight_root = Path(temporary)
    for workload in manifest['workloads']:
        name = workload['directory']
        source_directory = args.corpus / name
        original = (source_directory / 'program.elisa').read_bytes()
        edited = (source_directory / 'program.body-edit.elisa').read_bytes()
        for filename, expected in workload['sha256'].items():
            if digest(source_directory / filename) != expected:
                raise RuntimeError(f"corpus checksum mismatch before preflight: {name}/{filename}")
        source = preflight_root / name / 'program.elisa'
        source.parent.mkdir(parents=True)
        evidence = {}
        for arm in ('parent', 'candidate'):
            evidence[arm] = correctness_evidence(
                workload, source, original, edited, preflight_root / name / ("cache-" + arm), arm
            )
        passed = evidence['parent'] == evidence['candidate']
        preflight[name] = {
            "passed": passed,
            "arms": {
                arm: {
                    "stdout_sha256": hashlib.sha256(item["stdout"]).hexdigest(),
                    "stderr_without_report_sha256": hashlib.sha256(item["stderr_without_report"].encode()).hexdigest(),
                    "reports": item["reports"],
                    "prime_stdout_sha256": hashlib.sha256(item["prime_stdout"]).hexdigest(),
                    "prime_stderr_without_report_sha256": hashlib.sha256(item["prime_stderr_without_report"].encode()).hexdigest(),
                    "prime_reports": item["prime_reports"],
                    "prior_snapshot_sha256": item["prior_snapshot_sha256"],
                    "prime_exit_status": item["prime_exit_status"],
                    "edited_exit_status": item["edited_exit_status"],
                }
                for arm, item in evidence.items()
            },
        }
        (args.output / f"{name}.correctness_preflight.json").write_text(json.dumps(preflight[name], indent=2) + "\n")
        if not passed:
            raise SystemExit(f"parent/candidate correctness preflight mismatch for {name}; no timings were started")
(args.output / "correctness_preflight.json").write_text(json.dumps(preflight, indent=2, sort_keys=True) + "\n")
for path, expected in pins.items():
    if digest(Path(path)) != expected:
        raise SystemExit(f"pinned input changed during correctness preflight: {path}")
for arm, (root, binary) in products.items():
    if inputs(root, toolchain_envs[arm]) != fingerprints[arm]:
        raise SystemExit(f"Stage1 source or toolchain inputs changed during correctness preflight: {arm}")

# Establish exact parent/candidate output, diagnostics, cache snapshots, and cache reports
# before any timed sample. Priming runs are also load-gated so they cannot push the host
# above the admitted threshold before a measured compile starts.
print("Waiting for the load gate to hold for 60 seconds before timed pairs.", flush=True)
try:
    wait_for_sustained_load_gate(
        args.output,
        system,
        host_qualification,
        stage="before the first timed pair",
    )
except LoadGateError as error:
    raise SystemExit(str(error)) from error
for workload in manifest['workloads']:
    name = workload['directory']
    source_directory = args.corpus / name
    original = (source_directory / 'program.elisa').read_bytes()
    edited = (source_directory / 'program.body-edit.elisa').read_bytes()
    directory = args.output / name
    directory.mkdir(exist_ok=True)
    source = directory / 'program.elisa'
    for pair in range(args.pairs):
        evidence = {}
        for arm in (['parent', 'candidate'] if pair % 2 == 0 else ['candidate', 'parent']):
            root, binary = products[arm]
            env = toolchain_envs[arm].copy()
            for key in ['ELISA_STAGE1_PERMISSIVE', 'ELISA_STAGE1_TIMINGS', 'ELISA_INCREMENTAL_SHADOW', 'ELISA_INCREMENTAL_SHADOW_REPORT', 'ELISA_SEMANTIC_SERIAL', 'ELISACORE_FORCE_CONTRACTS']:
                env.pop(key, None)
            cache_directory = directory / ('cache-' + arm)
            env['ELISA_STAGE1_INCREMENTAL_CACHE_DIR'] = str(cache_directory)
            env['ELISA_STAGE1_INCREMENTAL_CACHE_REPORT'] = '1'
            command = [str(binary), '-emit', 'check', str(source)]
            enforce_load_gate(f"before priming {name}/{arm}/{pair + 1}")
            source.write_bytes(original)
            primed, _, _, _ = run_compiler(command, env, root)
            enforce_load_gate(f"after priming {name}/{arm}/{pair + 1}")
            (directory / f'{arm}-{pair}-prime.stderr').write_bytes(primed.stderr)
            prior_files = list(cache_directory.glob('*.elisa-semantic'))
            if len(prior_files) != 1:
                raise RuntimeError(f"expected one semantic cache snapshot for {arm}, found {prior_files}")
            prior_bytes = prior_files[0].read_bytes()
            prior_hash = hashlib.sha256(prior_bytes).hexdigest()
            (directory / f'{arm}-{pair}-prior.elisa-semantic').write_bytes(prior_bytes)
            source.write_bytes(edited)
            load_before = enforce_load_gate(f"before timed sample {name}/{arm}/{pair + 1}")
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            result, counter, counter_wrapped, wall = run_compiler(command, env, root, measure_counters=True)
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            load_after = enforce_load_gate(f"after timed sample {name}/{arm}/{pair + 1}")
            stderr = result.stderr.decode()
            reports = report_pattern.findall(stderr)
            if len(reports) != 1 or 'prior=valid' not in reports[0] or 'published=yes' not in reports[0]:
                raise RuntimeError(f"{name}/{arm} timed cache report mismatch: {reports}")
            expected_matches = 1 if 'supported_helpers' in workload else workload['helpers']
            if not re.search(r' matched=' + str(expected_matches) + r' visited=' + str(workload['functions']) + r' ', reports[0]):
                raise RuntimeError(f"{name}/{arm} timed cache coverage mismatch: {reports}")
            clean = report_pattern.sub('', stderr)
            evidence[arm] = (result.stdout, clean, reports, prior_hash)
            (directory / f'{arm}-{pair}.stderr').write_bytes(result.stderr)
            (directory / f'{arm}-{pair}.stdout').write_bytes(result.stdout)
            process_tree_cpu_seconds = counter.process_tree_cpu_seconds
            if process_tree_cpu_seconds is None and not counter_wrapped:
                process_tree_cpu_seconds = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
            rows.append({
                "workload": name,
                "pair": pair,
                "arm": arm,
                "wall_seconds": wall,
                "compiler_real_seconds": counter.command_real_seconds,
                "cpu_seconds": process_tree_cpu_seconds,
                "retired_instructions": counter.instructions_retired,
                "cycles_elapsed": counter.cycles_elapsed,
                "counter_status": counter.status,
                "load_before": load_before[0],
                "load_after": load_after[0],
                "report": reports[0],
                "prior_snapshot_sha256": prior_hash,
            })
        if evidence['parent'] != evidence['candidate']:
            raise RuntimeError(f"parent/candidate timed evidence mismatch for {name}, pair {pair + 1}: {evidence}")
    print('completed ' + name, flush=True)
for path, expected in pins.items():
    if digest(Path(path)) != expected:
        raise RuntimeError(f"pinned input changed during timing: {path}")
for arm, (root, binary) in products.items():
    if inputs(root, toolchain_envs[arm]) != fingerprints[arm]:
        raise RuntimeError(f"Stage1 source or toolchain inputs changed during timing: {arm}")
with (args.output / 'samples.csv').open('w', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
summaries = {}
def paired_metric_summary(samples, field, label):
    pairs = []
    for pair in range(args.pairs):
        parent = next(row[field] for row in samples if row["pair"] == pair and row["arm"] == "parent")
        candidate = next(row[field] for row in samples if row["pair"] == pair and row["arm"] == "candidate")
        if (
            not isinstance(parent, (int, float))
            or isinstance(parent, bool)
            or not isinstance(candidate, (int, float))
            or isinstance(candidate, bool)
            or parent <= 0
            or candidate <= 0
        ):
            return {
                "status": "unavailable",
                f"median_parent_{label}": None,
                f"median_candidate_{label}": None,
                f"median_paired_{label}_ratio_parent_over_candidate": None,
                f"geomean_paired_{label}_ratio_parent_over_candidate": None,
                f"candidate_{label}_wins": None,
            }
        pairs.append((parent, candidate, parent / candidate))
    ratios = [ratio for _, _, ratio in pairs]
    return {
        "status": "available",
        f"median_parent_{label}": statistics.median(parent for parent, _, _ in pairs),
        f"median_candidate_{label}": statistics.median(candidate for _, candidate, _ in pairs),
        f"median_paired_{label}_ratio_parent_over_candidate": statistics.median(ratios),
        f"geomean_paired_{label}_ratio_parent_over_candidate": math.exp(sum(map(math.log, ratios)) / len(ratios)),
        f"candidate_{label}_wins": sum(ratio > 1 for ratio in ratios),
    }

for workload in manifest['workloads']:
    name = workload['directory']
    samples = [row for row in rows if row['workload'] == name]
    ratios = [next(r['wall_seconds'] for r in samples if r['pair'] == pair and r['arm'] == 'parent') / next(r['wall_seconds'] for r in samples if r['pair'] == pair and r['arm'] == 'candidate') for pair in range(args.pairs)]
    summaries[name] = {
        "median_paired_wall_speedup_parent_over_candidate": statistics.median(ratios),
        "geomean_paired_wall_speedup_parent_over_candidate": math.exp(sum(map(math.log, ratios)) / len(ratios)),
        "candidate_wins": sum(r > 1 for r in ratios),
        "compiler_real_seconds": paired_metric_summary(samples, "compiler_real_seconds", "compiler_real_seconds"),
        "retired_instructions": paired_metric_summary(samples, "retired_instructions", "retired_instructions"),
        "cycles": paired_metric_summary(samples, "cycles_elapsed", "cycles"),
    }
(args.output / 'summary.json').write_text(json.dumps(summaries, indent=2) + "\n")
(args.output / 'COMPLETE').write_text("paired experiment completed\n")
run_completed = True
