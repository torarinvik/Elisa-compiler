import csv
import hashlib
import json
import math
import os
import platform
import resource
import shlex
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

import benchmark_fingerprint
import benchmark_preflight

out = Path(sys.argv[1])
preflight_only = os.environ.pop("ELISA_BENCH_PREFLIGHT_ONLY", "0") == "1"
repeat = int(sys.argv[2])
timeout_seconds = int(sys.argv[3])
source_dir = Path(sys.argv[4])
root = Path(sys.argv[5])
sys.path.insert(0, str(root / "scripts"))
sys.path.insert(0, str(source_dir))
from process_counter import (
    counters_available as retired_counters_available,
    method_description as counter_method_description,
    new_report_path as new_counter_report_path,
    read_report as read_counter_report,
    unavailable_counter,
    wrap_command as wrap_with_counter,
)
from bench_load_gate import (
    LOAD_FRACTION,
    LoadGateError,
    check_load_gate,
    load_average,
    wait_for_sustained_load_gate,
)
elisa_bin, runtime, clang, rustc, zig = sys.argv[6:11]
elisa_bin, runtime, clang, rustc, zig = (str(Path(path).resolve()) for path in (elisa_bin, runtime, clang, rustc, zig))
run_id = sys.argv[11]
expected_fingerprint_path = sys.argv[12]
compile_only = sys.argv[13] == "1"
runtime_repeat = int(sys.argv[14])
cleared_loader_allocator_names = sorted(filter(None, sys.argv[15].split(",")))
cleared_elisacore_names = sorted(filter(None, sys.argv[16].split()))
elisa_overflow_flag, rust_overflow_checks, zig_optimize = sys.argv[17:20]
runtime_profile_mode, runtime_profile_opt_level, runtime_profile_overflow = sys.argv[20:23]
cpu_flag_count = int(sys.argv[23])
cpu_flags = sys.argv[24:24 + cpu_flag_count]
benches = sys.argv[24 + cpu_flag_count:]
COUNTER_METHOD = counter_method_description()
COUNTERS_AVAILABLE = retired_counters_available()
if COUNTERS_AVAILABLE != (COUNTER_METHOD == "macOS /usr/bin/time -l"):
    raise SystemExit("retired-instruction counter availability changed during runner startup")
variants = ("elisa", "c", "rust", "zig")
dead_strip = shlex.split(os.environ.get("ELISA_LD_DEAD_STRIP", ""))
link_flags = shlex.split(os.environ.get("ELISA_LINK_EXE_FLAGS", ""))
clang_linker = os.environ.get("ELISA_BENCH_LD64_LLD", "")
clang_linker_flags = [f"-fuse-ld={clang_linker}"] if clang_linker else []
log_root = out / "build-samples"
child_env = os.environ.copy()
for name in list(child_env):
    if name.startswith(("ELISA_STAGE1_", "ELISA_DISABLE_MEMORY_", "ELISA_INCREMENTAL_", "ELISA_DBG_", "ELISA_EXPLAIN_", "ELISACORE_")) or name in ("ELISA_SEMANTIC_SERIAL", "ELISA_DEBUG_NODE_COUNT"):
        child_env.pop(name, None)
child_env["ELISA_STAGE1_BIN"] = elisa_bin
child_env["ELISA_STAGE1_ROOT"] = str(root.resolve())
child_env["ELISA_STAGE1_SELF"] = str(Path(elisa_bin).resolve())
child_env["ELISA_LLVM_BIN_DIR"] = os.environ.get("ELISA_LLVM_BIN_DIR", str(Path(clang).resolve().parent))
child_env["ELISA_CLANG"] = str(Path(clang).resolve())
child_env["ELISA_RUNTIME_OBJ"] = runtime
child_env["ELISA_STAGE1_CACHE"] = "0"
child_env["ELISA_STAGE1_JOBS"] = "1"
if sys.platform.startswith("linux"):
    child_env["ELISA_HOST_LINUX"] = "1"
if hasattr(os, "uname") and os.uname().machine == "x86_64":
    child_env["ELISA_HOST_X86_64"] = "1"
compile_samples = []
build_samples = []
counter_samples = []
times = {
    metric: {
        bench: {
            variant: {"wall": [], "cpu": [], "instructions": [], "cycles": [], "counter_status": []}
            for variant in variants
        }
        for bench in benches
    }
    for metric in ("compile", "build")
}

def enforce_load_gate(load, stage):
    try:
        check_load_gate(load, stage, out, platform.system(), out / "host_qualification.json", require_live_linux=True)
    except LoadGateError as error:
        raise SystemExit(str(error)) from error

expected_checksums = {
    "matmul": "-432360",
    "sieve": "19937370",
    "darray_sum": "751804663071387784",
    "darray_count_sum": "751804663071387784",
    "darray_growth": "3759023315128811",
    "darray_counted_fill": "7999998000000",
    "packed_side_table_write": "4295032832",
    "packed_side_table_read": "551911718912",
}
expected_exit_statuses = {
    "matmul": 113,
    "sieve": 189,
    "darray_sum": 152,
    "darray_count_sum": 152,
    "darray_growth": 72,
    "darray_counted_fill": 8,
    "packed_side_table_write": 148,
    "packed_side_table_read": 193,
}

def mark_aborted(kind, reason):
    (out / "ABORTED.txt").write_text(
        f"ABORTED — {kind}.\n{reason}\n"
        "Any partial outputs and measurements in this run are unusable.\n"
    )
    raise SystemExit(reason)

def host_platform_profile(*args, **kwargs):
    return benchmark_fingerprint.host_platform_profile(globals(), *args, **kwargs)

def comparator_toolchain_identity(*args, **kwargs):
    return benchmark_fingerprint.comparator_toolchain_identity(globals(), *args, **kwargs)

def benchmark_helper_hashes(*args, **kwargs):
    return benchmark_fingerprint.benchmark_helper_hashes(globals(), *args, **kwargs)

ENVIRONMENT_INPUT_NAMES = (
    "PATH", "HOME", "TMPDIR", "TMP", "TEMP",
    "SDKROOT", "DEVELOPER_DIR", "MACOSX_DEPLOYMENT_TARGET", "LLVM_CONFIG",
    "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH", "LIBRARY_PATH",
    "CCC_OVERRIDE_OPTIONS", "CLANG_CONFIG_FILE",
    "ZIG_LIB_DIR", "ZIG_GLOBAL_CACHE_DIR", "ZIG_LOCAL_CACHE_DIR",
    "RUSTUP_HOME", "RUSTUP_TOOLCHAIN", "CARGO_HOME", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
    "RUSTC_WRAPPER", "CFLAGS", "CPPFLAGS", "CXXFLAGS", "LDFLAGS", "CC", "CXX", "AR", "LD",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
)

def environment_input_hashes(environment, names=ENVIRONMENT_INPUT_NAMES):
    return {
        name: {
            "present": name in environment,
            "sha256": hashlib.sha256(os.fsencode(environment[name])).hexdigest() if name in environment else None,
        }
        for name in names
    }

def run_environment_input_hashes(*args, **kwargs):
    return benchmark_fingerprint.run_environment_input_hashes(globals(), *args, **kwargs)

def parity_environment_input_hashes(*args, **kwargs):
    return benchmark_fingerprint.parity_environment_input_hashes(globals(), *args, **kwargs)

def parse_toolchain_manifest(*args, **kwargs):
    return benchmark_fingerprint.parse_toolchain_manifest(globals(), *args, **kwargs)

def shared_runtime_source_manifest(*args, **kwargs):
    return benchmark_fingerprint.shared_runtime_source_manifest(globals(), *args, **kwargs)

def write_canonical_workload_fingerprint(*args, **kwargs):
    return benchmark_fingerprint.write_canonical_workload_fingerprint(globals(), *args, **kwargs)

def run_once(*args, **kwargs):
    return benchmark_preflight.run_once(globals(), *args, **kwargs)

def correctness_preflight(*args, **kwargs):
    return benchmark_preflight.correctness_preflight(globals(), *args, **kwargs)

def current_source_manifest(*args, **kwargs):
    return benchmark_preflight.current_source_manifest(globals(), *args, **kwargs)

def assert_build_sources_unchanged(*args, **kwargs):
    return benchmark_preflight.assert_build_sources_unchanged(globals(), *args, **kwargs)

# Run and compare every untimed executable before any compiler/build sample starts.
assert_build_sources_unchanged("before correctness preflight")
correctness_before_timing = correctness_preflight("before timed compiler/build samples")
assert_build_sources_unchanged("after correctness preflight")
canonical_fingerprint = write_canonical_workload_fingerprint(correctness_before_timing)
assert_build_sources_unchanged("before timed compiler/build samples")
print(f"Canonical workload fingerprint: {canonical_fingerprint}")
if preflight_only:
    (out / "PREFLIGHT_COMPLETE").write_text(
        "exact correctness preflight and canonical fingerprint complete\n"
    )
    print("Preflight-only run complete. No timed benchmark samples were started.", flush=True)
    raise SystemExit(0)
print(
    "Waiting for the load gate to hold for 60 seconds before timed samples.",
    flush=True,
)
try:
    wait_for_sustained_load_gate(
        out,
        platform.system(),
        out / "host_qualification.json",
        require_live_linux=True,
    )
except LoadGateError as error:
    raise SystemExit(str(error)) from error

def zig_cache_args(bench, phase, sample):
    base = log_root / "zig-cache-samples" / run_id / bench / f"{phase}-{sample:02d}"
    local = base / "local"
    global_cache = base / "global"
    local.mkdir(parents=True, exist_ok=True)
    global_cache.mkdir(parents=True, exist_ok=True)
    return ["--cache-dir", str(local), "--global-cache-dir", str(global_cache)]

def run(args, log, deadline, bench, variant, phase, log_path, counter_context):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError(f"{bench}/{variant} {phase} exceeded {timeout_seconds}s; see {log_path}")
    report_path = new_counter_report_path(out)
    launch_args = wrap_with_counter(args, report_path)
    try:
        proc = subprocess.Popen(
            launch_args, cwd=root, env=child_env, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        if report_path is not None:
            report_path.unlink(missing_ok=True)
        raise RuntimeError(f"could not start {bench}/{variant} {phase}: {error}") from error
    try:
        status = proc.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        if report_path is not None:
            report_path.unlink(missing_ok=True)
        raise RuntimeError(f"{bench}/{variant} {phase} exceeded {timeout_seconds}s; see {log_path}") from error
    if status != 0:
        if report_path is not None:
            report_path.unlink(missing_ok=True)
        raise RuntimeError(f"{bench}/{variant} {phase} failed with status {status}; see {log_path}")
    counter = read_counter_report(report_path) if report_path is not None else unavailable_counter()
    if report_path is not None:
        report_path.unlink(missing_ok=True)
    metric, sample, launch_order, child = counter_context
    counter_samples.append((
        metric, bench, sample, launch_order, variant, child,
        counter.instructions_retired, counter.cycles_elapsed,
        counter.child_cpu_seconds, counter.status,
    ))
    return counter

def sample_compile(bench, variant, sample, launch_order):
    src = source_dir / bench
    build_dir = out / bench
    log_path = log_root / bench / f"{variant}-object-{sample:02d}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    compile_dir = build_dir / f"compile-{variant}-{sample:02d}"
    compile_dir.mkdir(parents=True, exist_ok=False)
    obj = compile_dir / f"{variant}.o"
    cache_args = zig_cache_args(bench, "object", sample) if variant == "zig" else []
    load_before = load_average()
    enforce_load_gate(load_before, f"before compile sample {bench}/{variant}/{sample}")
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter_ns()
    with log_path.open("w") as log:
        deadline = time.monotonic() + timeout_seconds
        if variant == "elisa":
            args = [elisa_bin, "-emit", "obj", "-O3", elisa_overflow_flag, "-o", str(obj), str(src.with_suffix(".elisa"))]
        elif variant == "c":
            args = [clang, "-O3", *cpu_flags, "-c", "-o", str(obj), str(src.with_suffix(".c"))]
        elif variant == "rust":
            args = [rustc, "--edition=2021", "-C", "opt-level=3", "-C", "target-cpu=native", "-C", f"overflow-checks={rust_overflow_checks}", "--emit=obj", "--out-dir", str(compile_dir), str(src.with_suffix(".rs"))]
        else:
            args = [zig, "build-obj", str(src.with_suffix(".zig")), "-O", zig_optimize, "-mcpu=native", "-lc", f"-femit-bin={obj}", *cache_args]
        counter = run(
            args, log, deadline, bench, variant, "object compilation", log_path,
            ("compile", sample, launch_order, "object_compilation"),
        )
    wall = (time.perf_counter_ns() - started) / 1e9
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    fallback_cpu = (usage_after.ru_utime - usage_before.ru_utime) + (usage_after.ru_stime - usage_before.ru_stime)
    cpu = counter.child_cpu_seconds if counter.child_cpu_seconds is not None else fallback_cpu
    load_after = load_average()
    enforce_load_gate(load_after, f"after compile sample {bench}/{variant}/{sample}")
    if variant == "rust":
        rust_objects = list(compile_dir.glob("*.o"))
        if not rust_objects or any(not path.is_file() or path.stat().st_size == 0 for path in rust_objects):
            raise RuntimeError(f"{bench}/{variant} object compilation produced no object files; see {log_path}")
    elif not obj.is_file() or obj.stat().st_size == 0:
        raise RuntimeError(f"{bench}/{variant} object compilation produced no nonempty object; see {log_path}")
    return (
        wall, cpu, load_before, load_after,
        counter.instructions_retired, counter.cycles_elapsed, counter.status,
    )

def sample_build(bench, variant, sample, launch_order):
    src = source_dir / bench
    build_dir = out / bench
    binary = build_dir / variant
    obj = build_dir / "elisa-build.o"
    # The preflight executable is still present here. Remove old outputs before timing so a
    # command that returns success without producing a fresh artifact cannot pass validation.
    binary.unlink(missing_ok=True)
    if variant == "elisa":
        obj.unlink(missing_ok=True)
    log_path = log_root / bench / f"{variant}-executable-{sample:02d}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cache_args = zig_cache_args(bench, "executable", sample) if variant == "zig" else []
    load_before = load_average()
    enforce_load_gate(load_before, f"before build sample {bench}/{variant}/{sample}")
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter_ns()
    child_counters = []
    with log_path.open("w") as log:
        deadline = time.monotonic() + timeout_seconds
        if variant == "elisa":
            child_counters.append(run(
                [elisa_bin, "-emit", "obj", "-O3", elisa_overflow_flag, "-o", str(obj), str(src.with_suffix(".elisa"))],
                log, deadline, bench, variant, "object compilation", log_path,
                ("build", sample, launch_order, "object_compilation"),
            ))
            child_counters.append(run(
                [clang, *clang_linker_flags, *dead_strip, "-o", str(binary), str(obj), runtime, *link_flags],
                log, deadline, bench, variant, "link", log_path,
                ("build", sample, launch_order, "link"),
            ))
        elif variant == "c":
            child_counters.append(run(
                [clang, *clang_linker_flags, "-O3", *cpu_flags, "-o", str(binary), str(src.with_suffix(".c"))],
                log, deadline, bench, variant, "executable build", log_path,
                ("build", sample, launch_order, "executable_build"),
            ))
        elif variant == "rust":
            child_counters.append(run(
                [rustc, "--edition=2021", "-C", "opt-level=3", "-C", "target-cpu=native", "-C", f"overflow-checks={rust_overflow_checks}", "-o", str(binary), str(src.with_suffix(".rs"))],
                log, deadline, bench, variant, "executable build", log_path,
                ("build", sample, launch_order, "executable_build"),
            ))
        else:
            child_counters.append(run(
                [zig, "build-exe", str(src.with_suffix(".zig")), "-O", zig_optimize, "-mcpu=native", "-lc", f"-femit-bin={binary}", *cache_args],
                log, deadline, bench, variant, "executable build", log_path,
                ("build", sample, launch_order, "executable_build"),
            ))
    wall = (time.perf_counter_ns() - started) / 1e9
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    fallback_cpu = (usage_after.ru_utime - usage_before.ru_utime) + (usage_after.ru_stime - usage_before.ru_stime)
    child_cpu_values = [counter.child_cpu_seconds for counter in child_counters]
    cpu = sum(child_cpu_values) if all(value is not None for value in child_cpu_values) else fallback_cpu
    counters_available = bool(child_counters) and all(counter.status == "available" for counter in child_counters)
    instructions = sum(counter.instructions_retired for counter in child_counters) if counters_available else None
    cycles = sum(counter.cycles_elapsed for counter in child_counters) if counters_available else None
    counter_status = "available" if counters_available else "unavailable"
    load_after = load_average()
    enforce_load_gate(load_after, f"after build sample {bench}/{variant}/{sample}")
    if not binary.is_file() or binary.stat().st_size == 0 or not binary.stat().st_mode & 0o111:
        raise RuntimeError(f"{bench}/{variant} build did not produce an executable; see {log_path}")
    return wall, cpu, load_before, load_after, instructions, cycles, counter_status

def csv_samples(path, header, samples):
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for row in samples:
            writer.writerow((
                *row[:4], f"{row[4]:.6f}", f"{row[5]:.6f}",
                "" if row[6] is None else str(row[6]),
                "" if row[7] is None else str(row[7]),
                row[8],
                *("" if value is None else f"{value:.2f}" for value in row[9:]),
            ))

for bench in benches:
    for sample in range(repeat):
        offset = sample % len(variants)
        order = variants[offset:] + variants[:offset]
        for metric, action, samples in (
            ("compile", sample_compile, compile_samples),
            ("build", sample_build, build_samples),
        ):
            for launch_order, variant in enumerate(order, 1):
                wall, cpu, load_before, load_after, instructions, cycles, counter_status = action(
                    bench, variant, sample + 1, launch_order
                )
                times[metric][bench][variant]["wall"].append(wall)
                times[metric][bench][variant]["cpu"].append(cpu)
                times[metric][bench][variant]["instructions"].append(instructions)
                times[metric][bench][variant]["cycles"].append(cycles)
                times[metric][bench][variant]["counter_status"].append(counter_status)
                samples.append((
                    bench, sample + 1, launch_order, variant, wall, cpu,
                    instructions, cycles, counter_status, *load_before, *load_after,
                ))

# Timed executable builds replace the preflight binaries; verify those outputs too,
# including when runtime timing is disabled.
correctness_after_build_samples = correctness_preflight("after timed compiler/build samples")
if correctness_after_build_samples != correctness_before_timing:
    mark_aborted("correctness preflight failed", "program outputs changed after compiler/build sampling")
(out / "executables.after-build.sha256").write_text("".join(
    f"{hashlib.sha256((out / bench / variant).read_bytes()).hexdigest()}  {bench}/{variant}\n"
    for bench in benches
    for variant in variants
))
executable_manifest_bytes = (out / "executables.after-build.sha256").read_bytes()
(out / "correctness_preflight.json").write_text(json.dumps({
    "schema": "cross-language-correctness-v1",
    "before_timing": correctness_before_timing,
    "after_build_samples": correctness_after_build_samples,
    "executable_manifest": "executables.after-build.sha256",
    "executable_manifest_sha256": hashlib.sha256(executable_manifest_bytes).hexdigest(),
}, indent=2, sort_keys=True) + "\n")

load_header = (
    "benchmark", "sample", "launch_order", "variant", "wall_seconds", "child_cpu_seconds",
    "instructions_retired", "cycles_elapsed", "counter_status",
    "load1_before", "load5_before", "load15_before", "load1_after", "load5_after", "load15_after",
)
compile_samples_path = out / "compile_samples.csv"
build_samples_path = out / "build_samples.csv"
csv_samples(compile_samples_path, load_header, compile_samples)
csv_samples(build_samples_path, load_header, build_samples)

counter_samples_path = out / "counter_samples.csv"
with counter_samples_path.open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow((
        "metric", "benchmark", "sample", "launch_order", "variant", "child",
        "instructions_retired", "cycles_elapsed", "child_cpu_seconds", "counter_status",
    ))
    for row in counter_samples:
        writer.writerow((
            *row[:6],
            "" if row[6] is None else str(row[6]),
            "" if row[7] is None else str(row[7]),
            "" if row[8] is None else f"{row[8]:.6f}",
            row[9],
        ))

def median_counter(values):
    if not values or any(value is None for value in values):
        return ""
    return str(int(statistics.median(values)))

def counter_status_for(values):
    return "available" if values and all(value is not None for value in values) else "unavailable"

for metric, results_name in (("compile", "compile_results.csv"), ("build", "build_results.csv")):
    result_path = out / results_name
    with result_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow((
            "benchmark", "variant", "best_wall_seconds", "median_wall_seconds",
            "best_child_cpu_seconds", "median_child_cpu_seconds",
            "median_instructions_retired", "median_cycles_elapsed", "counter_status", "repeat_count",
        ))
        for bench in benches:
            for variant in variants:
                wall = times[metric][bench][variant]["wall"]
                cpu = times[metric][bench][variant]["cpu"]
                instructions = times[metric][bench][variant]["instructions"]
                cycles = times[metric][bench][variant]["cycles"]
                status = "available" if (
                    counter_status_for(instructions) == "available"
                    and counter_status_for(cycles) == "available"
                ) else "unavailable"
                writer.writerow((
                    bench, variant, f"{min(wall):.6f}", f"{statistics.median(wall):.6f}",
                    f"{min(cpu):.6f}", f"{statistics.median(cpu):.6f}",
                    median_counter(instructions), median_counter(cycles), status, len(wall),
                ))

RATIO_FIELDS = (
    ("elisa_over_rust_median_wall", "rust", "wall"),
    ("elisa_over_rust_median_child_cpu", "rust", "cpu"),
    ("elisa_over_rust_median_instructions_retired", "rust", "instructions"),
    ("elisa_over_rust_median_cycles_elapsed", "rust", "cycles"),
    ("elisa_over_zig_median_wall", "zig", "wall"),
    ("elisa_over_zig_median_child_cpu", "zig", "cpu"),
    ("elisa_over_zig_median_instructions_retired", "zig", "instructions"),
    ("elisa_over_zig_median_cycles_elapsed", "zig", "cycles"),
)
diagnostic_only_benches = {"packed_side_table_read"}
comparison_benches = [bench for bench in benches if bench not in diagnostic_only_benches]

def ratio_record(bench, metric_times):
    result = {}
    for field, comparator, axis in RATIO_FIELDS:
        elisa_values = metric_times[bench]["elisa"][axis]
        comparator_values = metric_times[bench][comparator][axis]
        if axis in ("instructions", "cycles") and (
            not elisa_values or not comparator_values
            or any(value is None for value in elisa_values + comparator_values)
        ):
            result[field] = None
            continue
        elisa_median = statistics.median(elisa_values)
        comparator_median = statistics.median(comparator_values)
        if elisa_median <= 0 or comparator_median <= 0:
            raise RuntimeError(f"cannot compute positive median ratio for {bench}/{comparator}/{axis}")
        result[field] = elisa_median / comparator_median
    return result

def write_ratio_results(metric, metric_times):
    path = out / f"{metric}_ratios.csv"
    records = [ratio_record(bench, metric_times) for bench in comparison_benches]
    geometric_means = {}
    for field, _, axis in RATIO_FIELDS:
        values = [record[field] for record in records]
        geometric_means[field] = (
            math.exp(sum(math.log(value) for value in values) / len(values))
            if values and all(value is not None for value in values)
            else None
        )
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("benchmark", *(field for field, _, _ in RATIO_FIELDS), "counter_status"))
        for bench, record in zip(comparison_benches, records):
            status = "available" if all(
                record[field] is not None
                for field, _, axis in RATIO_FIELDS if axis in ("instructions", "cycles")
            ) else "unavailable"
            writer.writerow((
                bench,
                *("" if record[field] is None else f"{record[field]:.6f}" for field, _, _ in RATIO_FIELDS),
                status,
            ))
        geometric_status = "available" if all(
            geometric_means[field] is not None
            for field, _, axis in RATIO_FIELDS if axis in ("instructions", "cycles")
        ) else "unavailable"
        writer.writerow((
            "geometric_mean",
            *("" if geometric_means[field] is None else f"{geometric_means[field]:.6f}" for field, _, _ in RATIO_FIELDS),
            geometric_status,
        ))
    return path, comparison_benches, records, geometric_means

def print_ratio_summary(title, compared_benches, records, geometric_means):
    print(f"\n{title} Elisa/comparator median ratios (<1.0 means Elisa is faster)")
    print(f"{'benchmark':<20} {'Rust wall':>11} {'Rust CPU':>11} {'Rust instr':>11} {'Rust cycles':>11} {'Zig wall':>11} {'Zig CPU':>11} {'Zig instr':>11} {'Zig cycles':>11}")
    print("Diagnostic-only workloads omitted from ratios and geometric mean: " + ", ".join(sorted(diagnostic_only_benches)))
    for bench, record in zip(compared_benches, records):
        values = [record[field] for field, _, _ in RATIO_FIELDS]
        print(f"{bench:<20} " + " ".join(f"{value:>11.3f}" if value is not None else f"{'n/a':>11}" for value in values))
    values = [geometric_means[field] for field, _, _ in RATIO_FIELDS]
    print(f"{'geometric mean':<20} " + " ".join(f"{value:>11.3f}" if value is not None else f"{'n/a':>11}" for value in values))

compile_ratio_path, compile_comparison_benches, compile_ratio_records, compile_ratio_means = write_ratio_results("compile", times["compile"])
build_ratio_path, build_comparison_benches, build_ratio_records, build_ratio_means = write_ratio_results("build", times["build"])

def print_summary(metric, title):
    print(f"\n{title} (median wall seconds / child CPU seconds)")
    print(f"{'benchmark':<12} {'Elisa':>21} {'C':>21} {'Rust':>21} {'Zig':>21}")
    for bench in benches:
        values = [f"{statistics.median(times[metric][bench][variant]['wall']):.6f}/{statistics.median(times[metric][bench][variant]['cpu']):.6f}" for variant in variants]
        print(f"{bench:<12} " + " ".join(f"{value:>21}" for value in values))

print_summary("compile", "Object-only compiler time")
print_summary("build", "End-to-end executable build time")
print_ratio_summary("Object-only compile", compile_comparison_benches, compile_ratio_records, compile_ratio_means)
print_ratio_summary("Executable build", build_comparison_benches, build_ratio_records, build_ratio_means)
print(f"Object compile samples/results: {compile_samples_path} / {out / 'compile_results.csv'}")
print(f"Executable build samples/results: {build_samples_path} / {out / 'build_results.csv'}")
print(f"Compile ratios: {compile_ratio_path}")
print(f"Build ratios:   {build_ratio_path}")
