#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Auxiliary runtime comparison for GENERATED code. Use cross_language.sh for qualified
# compiler-throughput, Zig/Rust, and runtime comparisons.
# After the first correctness preflight, timed samples wait for 60 seconds under the shared
# load threshold; point checks remain around each sample.
#   test/bench/codegen_perf/run.sh <outdir> [bench ...]
# Env: ELISACORE_BIN (stage0), REPEAT (default 7), SKIP_S0=1, SKIP_C=1, CALLGRIND=1,
#      S1_BIN (call this stage1 product directly instead of the wrapper, e.g. a gen2 candidate),
#      ELISA_RUNTIME_OBJ (runtime object to link stage1 products against), BENCH_TIMEOUT_SECONDS.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/../../.." && pwd)"
OUT="${1:?outdir}"; shift
mkdir -p "$OUT"; OUT="$(cd -- "$OUT" && pwd -P)"
if [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "output directory is not empty: $OUT (choose a fresh directory to prevent stale results)" >&2
  exit 2
fi
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
S0="${ELISACORE_BIN:-}"
REPEAT="${REPEAT:-7}"
BENCH_TIMEOUT_SECONDS="${BENCH_TIMEOUT_SECONDS:-900}"
[[ "$REPEAT" =~ ^[1-9][0-9]*$ ]] || { echo "REPEAT must be a positive integer" >&2; exit 2; }
[[ "$BENCH_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "BENCH_TIMEOUT_SECONDS must be a positive integer" >&2; exit 2; }
[[ -s "$RUNTIME" ]] || { echo "missing runtime object: $RUNTIME" >&2; exit 2; }
if [[ -n "${CALLGRIND:-}" ]]; then command -v valgrind >/dev/null || { echo "CALLGRIND=1 requires valgrind" >&2; exit 2; }; fi
benches=("$@")
if [[ ${#benches[@]} -eq 0 ]]; then
  while IFS= read -r source; do benches+=("${source%.elisa}"); done < <(cd "$HERE" && printf '%s\n' *.elisa | sort)
fi
[[ ${#benches[@]} -gt 0 ]] || { echo "no benchmark sources found" >&2; exit 2; }
for benchmark in "${benches[@]}"; do
  [[ "$benchmark" =~ ^[A-Za-z0-9_]+$ ]] || { echo "invalid benchmark name: $benchmark" >&2; exit 2; }
  [[ -f "$HERE/$benchmark.elisa" ]] || { echo "missing Elisa source: $HERE/$benchmark.elisa" >&2; exit 2; }
  if [[ -z "${SKIP_C:-}" ]]; then
    [[ -f "$HERE/$benchmark.c" ]] || { echo "missing C source: $HERE/$benchmark.c" >&2; exit 2; }
  fi
done

mark_incomplete_run() {
  local status=$?
  if [[ -n "${BENCH_LOCK_PID:-}" ]]; then
    kill "$BENCH_LOCK_PID" 2>/dev/null || true
    wait "$BENCH_LOCK_PID" 2>/dev/null || true
    unset BENCH_LOCK_PID
  fi
  if (( status != 0 )) && [[ ! -f "$OUT/ABORTED.txt" ]] && [[ ! -f "$OUT/AUXILIARY_COMPLETE" ]]; then
    printf 'ABORTED — runner exited with status %d before completion.\nAny partial measurements are unusable.\n' "$status" >"$OUT/ABORTED.txt" || true
  fi
  return "$status"
}
trap mark_incomplete_run EXIT

# Share the host lease with cross_language.sh and incremental_fact_lookup/paired.py.
BENCH_LOCK_PATH="${ELISA_BENCH_LOCK_PATH:-/tmp/elisa-cross-language-benchmark.lock}"
BENCH_LOCK_READY="$OUT/.benchmark-lock-ready"
mkfifo "$BENCH_LOCK_READY"
python3 - "$BENCH_LOCK_PATH" "$$" <<'PY' >"$BENCH_LOCK_READY" &
import fcntl
import os
import sys
import time

fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("busy", flush=True)
    raise SystemExit(3)
print("locked", flush=True)
parent_pid = int(sys.argv[2])
while os.getppid() == parent_pid:
    time.sleep(0.5)
PY
BENCH_LOCK_PID=$!
if ! IFS= read -r BENCH_LOCK_STATUS <"$BENCH_LOCK_READY"; then
  rm -f "$BENCH_LOCK_READY"
  echo "could not acquire the compiler benchmark host lock" >&2
  exit 2
fi
rm -f "$BENCH_LOCK_READY"
if [[ "$BENCH_LOCK_STATUS" != locked ]]; then
  wait "$BENCH_LOCK_PID" 2>/dev/null || true
  unset BENCH_LOCK_PID
  echo "another compiler benchmark holds the host lock at $BENCH_LOCK_PATH" >&2
  exit 2
fi

SYSTEM="$(uname -s)"
HOST_QUALIFICATION="$OUT/host_qualification.json"
if [[ "$SYSTEM" == Darwin ]]; then
  python3 - "$HOST_QUALIFICATION" <<'PY'
import json, platform, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"system": "Darwin", "machine": platform.machine()}, sort_keys=True) + "\n")
PY
elif [[ "$SYSTEM" == Linux ]]; then
  QUALIFICATION_SOURCE="${ELISA_BENCH_HOST_QUALIFICATION:-}"
  [[ -n "$QUALIFICATION_SOURCE" ]] || {
    echo "Linux timing requires ELISA_BENCH_HOST_QUALIFICATION from this host's cross_language.sh run" >&2
    exit 2
  }
  python3 - "$QUALIFICATION_SOURCE" "$HOST_QUALIFICATION" <<'PY'
import json, os, platform, sys
from pathlib import Path
record = json.loads(Path(sys.argv[1]).read_text())
if not isinstance(record, dict) or record.get("system", "").lower() != "linux" or record.get("qualified") is not True:
    raise SystemExit("Linux host qualification is missing or failed")
if record.get("machine") != platform.machine():
    raise SystemExit("Linux host qualification machine does not match this host")
try:
    allowed = len(os.sched_getaffinity(0))
except (AttributeError, OSError) as error:
    raise SystemExit(f"cannot verify current Linux CPU affinity: {error}") from error
if record.get("allowed_cpu_count") != allowed:
    raise SystemExit("Linux host qualification affinity count does not match this process")
try:
    if os.readlink("/proc/self/ns/cgroup") != os.readlink("/proc/1/ns/cgroup"):
        raise SystemExit("cannot use a qualification snapshot from a hidden cgroup namespace")
except OSError as error:
    raise SystemExit(f"cannot verify current Linux cgroup namespace: {error}") from error
rows = record.get("cgroup_quota_sources")
if not isinstance(rows, list) or not rows:
    raise SystemExit("Linux host qualification has no cgroup quota provenance")
quotas = []
for row in rows:
    if not isinstance(row, dict):
        raise SystemExit("Linux host qualification has a malformed cgroup quota row")
    quota_path = Path(row.get("quota_path", ""))
    try:
        if "period_path" in row:
            quota = int(quota_path.read_text().strip())
            period = int(Path(row["period_path"]).read_text().strip())
        else:
            quota_text, period_text = quota_path.read_text().split()[:2]
            quota = quota_text if quota_text == "max" else int(quota_text)
            period = int(period_text)
    except (OSError, ValueError, IndexError, TypeError) as error:
        raise SystemExit(f"cannot verify current cgroup quota at {quota_path}: {error}") from error
    if quota != row.get("quota") or period != row.get("period"):
        raise SystemExit(f"Linux cgroup quota changed since qualification: {quota_path}")
    cpus = None if quota == "max" or (isinstance(quota, int) and quota < 0) else quota / period
    expected_cpus = row.get("cpus")
    if (cpus is None and expected_cpus is not None) or (cpus is not None and (not isinstance(expected_cpus, (int, float)) or abs(cpus - expected_cpus) > 1e-12)):
        raise SystemExit(f"Linux cgroup quota provenance mismatch: {quota_path}")
    if cpus is not None:
        quotas.append(cpus)
current_quota = min(quotas) if quotas else None
expected_quota = record.get("effective_cgroup_cpu_quota")
if (current_quota is None) != (expected_quota is None) or (current_quota is not None and abs(current_quota - expected_quota) > 1e-12):
    raise SystemExit("Linux host qualification cgroup capacity does not match this host")
Path(sys.argv[2]).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
PY
else
  echo "unsupported benchmark host: $SYSTEM" >&2
  exit 2
fi

load_gate() {
  local stage="$1"
  python3 - "$ROOT" "$OUT" "$HOST_QUALIFICATION" "$SYSTEM" "$stage" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from bench_load_gate import LoadGateError, check_load_gate, load_average
try:
    check_load_gate(load_average(), sys.argv[5], Path(sys.argv[2]), sys.argv[4], Path(sys.argv[3]), require_live_linux=True)
except LoadGateError as error:
    print(f"timing load gate failed: {error}", file=sys.stderr)
    raise SystemExit(2)
PY
}

sustained_load_gate() {
  local stage="$1"
  python3 - "$ROOT" "$OUT" "$HOST_QUALIFICATION" "$SYSTEM" "$stage" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from bench_load_gate import LoadGateError, wait_for_sustained_load_gate
try:
    wait_for_sustained_load_gate(
        Path(sys.argv[2]), sys.argv[4], Path(sys.argv[3]),
        stage=sys.argv[5], require_live_linux=True,
    )
except LoadGateError as error:
    print(f"sustained timing load gate failed: {error}", file=sys.stderr)
    raise SystemExit(2)
PY
}

variants=()
if [[ -z "${SKIP_C:-}" ]]; then variants+=(c); fi
if [[ -z "${SKIP_S0:-}" && -n "$S0" ]]; then variants+=(s0); fi
variants+=(s1)

preflight() { python3 - "$BENCH_TIMEOUT_SECONDS" "$OUT" "$1" "${variants[@]}" <<'PY'
import hashlib, json, os, signal, subprocess, sys
from pathlib import Path
timeout, out, benchmark = int(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
variants = sys.argv[4:]
observed = {}
for variant in variants:
    executable = out / f"{benchmark}.{variant}"
    proc = subprocess.Popen([str(executable)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        proc.communicate()
        raise SystemExit(f"correctness preflight exceeded {timeout}s timeout: {executable}") from error
    if proc.returncode < 0:
        raise SystemExit(f"correctness preflight terminated by signal {-proc.returncode}: {executable}")
    if proc.returncode != 0:
        raise SystemExit(f"correctness preflight exited with status {proc.returncode}: {executable}")
    observed[variant] = (proc.returncode, stdout, stderr)
    (out / f"{benchmark}.{variant}.stdout").write_bytes(stdout)
    (out / f"{benchmark}.{variant}.stderr").write_bytes(stderr)
baseline = "c" if "c" in observed else ("s0" if "s0" in observed else "s1")
expected_status, expected_stdout, _ = observed[baseline]
for variant, (status, stdout, _) in observed.items():
    if status != expected_status or stdout != expected_stdout:
        raise SystemExit(f"correctness mismatch for {benchmark}/{variant} against {baseline}: exit={status}, stdout_sha256={hashlib.sha256(stdout).hexdigest()}")
record = {
    "baseline": baseline,
    "exit_status": expected_status,
    "stdout_sha256": hashlib.sha256(expected_stdout).hexdigest(),
    "stdout_bytes": len(expected_stdout),
    "variants": {
        variant: {
            "exit_status": status,
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        }
        for variant, (status, stdout, stderr) in observed.items()
    },
}
(out / f"{benchmark}.correctness.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
PY
}

best() { python3 - "$ROOT" "$OUT" "$HOST_QUALIFICATION" "$SYSTEM" "$BENCH_TIMEOUT_SECONDS" "$1" "$2" "$REPEAT" <<'PY'
import hashlib, json, os, resource, signal, subprocess, sys
from pathlib import Path
root, out, qualification = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
system, timeout, expected_path, executable, repeat = sys.argv[4], int(sys.argv[5]), Path(sys.argv[6]), sys.argv[7], int(sys.argv[8])
expected = json.loads(expected_path.read_text())
sys.path.insert(0, str(root / "scripts"))
from bench_load_gate import LoadGateError, check_load_gate, load_average
variant = Path(executable).name.rsplit(".", 1)[-1]
variant_expected = expected["variants"][variant]
def gate(stage):
    try: check_load_gate(load_average(), stage, out, system, qualification, require_live_linux=True)
    except LoadGateError as error: raise SystemExit(f"timing load gate failed: {error}") from error
def run(command):
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        proc.communicate()
        raise SystemExit(f"timed program exceeded {timeout}s timeout: {command}") from error
    return proc.returncode, stdout, stderr
times=[]
for sample in range(repeat):
    gate(f"before runtime sample {expected_path.stem}/{Path(executable).name}/{sample + 1}")
    before=resource.getrusage(resource.RUSAGE_CHILDREN)
    status, stdout, stderr=run([executable])
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    gate(f"after runtime sample {expected_path.stem}/{Path(executable).name}/{sample + 1}")
    if status != expected["exit_status"] or hashlib.sha256(stdout).hexdigest() != expected["stdout_sha256"] or hashlib.sha256(stderr).hexdigest() != variant_expected["stderr_sha256"]:
        raise SystemExit(f"timed output/exit mismatch for {executable}, sample {sample+1}")
    times.append((after.ru_utime-before.ru_utime)+(after.ru_stime-before.ru_stime))
print(f"{min(times):.4f} rc={expected['exit_status']}")
PY
}
irs() { python3 - "$BENCH_TIMEOUT_SECONDS" "$1" "$2" <<'PY'
import hashlib, json, os, re, signal, subprocess, sys
from pathlib import Path
timeout, expected_path, executable = int(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
expected = json.loads(expected_path.read_text())
proc = subprocess.Popen(["valgrind", "--tool=callgrind", "--callgrind-out-file=/dev/null", executable], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
try:
    stdout, stderr = proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired as error:
    try: os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError: pass
    proc.communicate()
    raise SystemExit(f"callgrind exceeded {timeout}s timeout: {executable}") from error
if proc.returncode != expected["exit_status"] or hashlib.sha256(stdout).hexdigest() != expected["stdout_sha256"]:
    raise SystemExit(f"callgrind output/exit mismatch for {executable}")
match = re.search(rb"Collected\s+([0-9,]+)", stderr)
if not match:
    raise SystemExit(f"callgrind did not report instructions for {executable}")
print(match.group(1).decode("ascii").replace(",", ""))
PY
}
printf '%-14s %-8s %10s %6s %14s\n' bench variant cpu_s rc instr
TIMED_ADMISSION_PASSED=0
for b in "${benches[@]}"; do
  src="$HERE/$b.elisa"
  load_gate "before builds for $b"
  if [[ -n "${S1_BIN:-}" ]]; then s1=("$S1_BIN" -emit obj); else s1=(bash "$ROOT/scripts/elisac_stage1.sh"); fi
  if ! "${s1[@]}" -O2 -o "$OUT/$b.s1.o" "$src" >"$OUT/$b.s1.log" 2>&1; then
    echo "$b: stage1 compile failed (see $OUT/$b.s1.log)" >&2; exit 2
  fi
  if ! clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$OUT/$b.s1" "$OUT/$b.s1.o" "$RUNTIME" >>"$OUT/$b.s1.log" 2>&1; then
    echo "$b: stage1 link failed (see $OUT/$b.s1.log)" >&2; exit 2
  fi
  if [[ -z "${SKIP_S0:-}" && -n "$S0" ]]; then
    if ! "$S0" -emit obj -O2 -o "$OUT/$b.s0.o" "$src" >"$OUT/$b.s0.log" 2>&1; then
      echo "$b: stage0 compile failed (see $OUT/$b.s0.log)" >&2; exit 2
    fi
    if ! clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$OUT/$b.s0" "$OUT/$b.s0.o" "$RUNTIME" >>"$OUT/$b.s0.log" 2>&1; then
      echo "$b: stage0 link failed (see $OUT/$b.s0.log)" >&2; exit 2
    fi
    # (Always with the runtime object: on Linux the clang shim ignores unresolved symbols,
    # so a runtime-less link "succeeds" and the program calls address 0.)
  fi
  if [[ -z "${SKIP_C:-}" ]] && ! clang -O2 -o "$OUT/$b.c" "$HERE/$b.c" 2>"$OUT/$b.c.log"; then
    echo "$b: C build failed (see $OUT/$b.c.log)" >&2; exit 2
  fi
  load_gate "after builds for $b"
  for v in "${variants[@]}"; do
    [[ -x "$OUT/$b.$v" ]] || { echo "missing executable for $b/$v" >&2; exit 2; }
  done
  preflight "$b"
  load_gate "after correctness preflight for $b"
  if (( TIMED_ADMISSION_PASSED == 0 )); then
    sustained_load_gate "before the first timed sample"
    TIMED_ADMISSION_PASSED=1
  fi
  for v in "${variants[@]}"; do
    r="$(best "$OUT/$b.correctness.json" "$OUT/$b.$v")"; ir="-"
    if [[ -n "${CALLGRIND:-}" ]]; then
      load_gate "before callgrind for $b/$v"
      ir="$(irs "$OUT/$b.correctness.json" "$OUT/$b.$v")"
      load_gate "after callgrind for $b/$v"
    fi
    printf '%-14s %-8s %10s %6s %14s\n' "$b" "$v" "${r% *}" "${r#* }" "$ir"
  done
done
date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ' >"$OUT/AUXILIARY_COMPLETE"
echo "Auxiliary generated-code runtime comparison complete: $OUT"
