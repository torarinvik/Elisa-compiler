#!/usr/bin/env bash
# Cross-language compiler and runtime comparison for the arithmetic, DArray,
# and packed side-table workloads listed below.
# See README.cross-language.md for flags, checksum semantics, and known allocator differences.
set -euo pipefail

# Optional cross-run parity gate. Keep the reference path out of compiler and workload
# subprocess environments; it is passed only to this harness's Python coordinator below.
EXPECTED_CANONICAL_FINGERPRINT="${ELISA_BENCH_EXPECT_CANONICAL_FINGERPRINT:-}"
unset ELISA_BENCH_EXPECT_CANONICAL_FINGERPRINT

# Remove inherited DYLD_*/LD_* overrides and allocator tuning before any
# compiler, linker, preflight executable, or timed executable is launched. Keep
# bare LD intact for linker selection.
# Keep inherited variable names for the run manifest without recording values.
BENCH_ENV_OVERRIDES_CLEARED=()
for env_name in \
  "${!DYLD_@}" "${!LD_@}" GLIBC_TUNABLES \
  "${!MALLOC_@}" "${!Malloc@}" "${!JEMALLOC_@}" "${!TCMALLOC_@}" "${!MIMALLOC_@}"; do
  [[ -n "$env_name" ]] || continue
  if printenv "$env_name" >/dev/null 2>&1; then
    BENCH_ENV_OVERRIDES_CLEARED+=("$env_name")
    unset "$env_name"
  fi
done

# Compare the ordinary native compiler path. Remove inherited feature, ABI, and
# instrumentation switches before building; keep only the product override, the
# explicit host-target guard, and the controls we pin below.
unset ELISA_SEMANTIC_SERIAL ELISA_INCREMENTAL_SHADOW
INHERITED_ELISACORE_NAMES="${!ELISACORE_@}"
for env_name in "${!ELISACORE_@}"; do
  unset "$env_name"
done
unset ELISA_DEBUG_NODE_COUNT
unset ELISA_PLATFORM_SOURCED
unset ELISA_LLVM_BIN_DIR ELISA_LLVM_LIBDIR ELISA_LLVM_LIBS
unset ELISA_LD_DEAD_STRIP ELISA_LINK_EXE_FLAGS
unset ELISA_BENCH_LD64_LLD
unset ELISA_AR ELISA_CLANG ELISA_CLANG_TOOL ELISA_LD ELISA_LLVM_NM ELISA_LLVM_OBJCOPY
unset ELISA_NPROC ELISA_BREW_BIN ELISA_PYTHON314_BIN ELISA_PYTHON314_CONFIG
unset ELISA_PYTHON312_BIN ELISA_PYTHON312_CONFIG
for env_name in "${!ELISA_STAGE1_@}"; do
  case "$env_name" in
    ELISA_STAGE1_BIN|ELISA_STAGE1_TRIPLE|ELISA_STAGE1_CACHE|ELISA_STAGE1_JOBS) ;;
    *) unset "$env_name" ;;
  esac
done
for env_name in "${!ELISA_HOST_@}" "${!ELISA_DISABLE_MEMORY_@}" "${!ELISA_INCREMENTAL_@}"; do
  unset "$env_name"
done
for env_name in "${!ELISA_DBG_@}" "${!ELISA_EXPLAIN_@}"; do
  unset "$env_name"
done
export ELISA_STAGE1_CACHE=0
export ELISA_STAGE1_JOBS=1

case "$(uname -s)" in
  Darwin)
    BREW="$(command -v brew || true)"
    [[ -n "$BREW" ]] || { echo "Homebrew is required to select the stable LLVM toolchain on macOS" >&2; exit 2; }
    export HOMEBREW_NO_AUTO_UPDATE=1
    LLVM_PREFIX="$("$BREW" --prefix llvm 2>/dev/null)" || { echo "Homebrew LLVM is not installed" >&2; exit 2; }
    LLVM_CONFIG="$LLVM_PREFIX/bin/llvm-config"
    [[ -x "$LLVM_CONFIG" ]] || { echo "Homebrew LLVM is missing llvm-config: $LLVM_CONFIG" >&2; exit 2; }
    export LLVM_CONFIG
    ;;
  Linux) ;;
  *) echo "cross-language child CPU timing supports macOS and Linux only" >&2; exit 2 ;;
esac

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/../../.." && pwd)"
. "$ROOT/scripts/platform.sh"

OUT="${1:-${OUTDIR:-$ROOT/build/codegen-perf-cross-language}}"
mkdir -p "$OUT"
OUT="$(cd -- "$OUT" && pwd -P)"
if [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "output directory is not empty: $OUT (choose a fresh directory so failed runs cannot leave stale result CSVs)" >&2
  exit 2
fi
mark_incomplete_run() {
  local status=$?
  if [[ -n "${BENCH_LOCK_PID:-}" ]]; then
    kill "$BENCH_LOCK_PID" 2>/dev/null || true
    wait "$BENCH_LOCK_PID" 2>/dev/null || true
    unset BENCH_LOCK_PID
  fi
  if (( status != 0 )) && [[ ! -f "$OUT/ABORTED.txt" ]] && [[ ! -f "$OUT/COMPLETE" ]] && [[ ! -f "$OUT/COMPILE_COMPLETE" ]] && [[ ! -f "$OUT/PREFLIGHT_COMPLETE" ]]; then
    printf 'ABORTED — runner exited with status %d before completion.\nAny partial outputs and measurements from this run are unusable.\n' "$status" >"$OUT/ABORTED.txt" || true
  fi
  return "$status"
}
trap mark_incomplete_run EXIT
BENCH_LOCK_PATH="${ELISA_BENCH_LOCK_PATH:-/tmp/elisa-cross-language-benchmark.lock}"
BENCH_LOCK_PID=""
INHERITED_BENCH_LOCK_FD="${ELISA_BENCH_LOCK_FD:-}"
if [[ -n "$INHERITED_BENCH_LOCK_FD" ]]; then
  python3 - "$INHERITED_BENCH_LOCK_FD" "$BENCH_LOCK_PATH" <<'PY'
import fcntl
import os
import sys

try:
    fd = int(sys.argv[1])
    held = os.fstat(fd)
    expected = os.stat(sys.argv[2])
except (OSError, ValueError) as error:
    raise SystemExit(f"invalid inherited benchmark lock: {error}")
if (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
    raise SystemExit("inherited benchmark lock does not refer to the configured host lock")
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError as error:
    raise SystemExit(f"inherited benchmark lock is not held by this descriptor: {error}")
PY
  [[ "$INHERITED_BENCH_LOCK_FD" =~ ^[0-9]+$ ]] || { echo "invalid inherited benchmark lock descriptor" >&2; exit 2; }
  eval "exec ${INHERITED_BENCH_LOCK_FD}>&-"
  unset ELISA_BENCH_LOCK_FD
else
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
  BENCH_LOCK_STATUS=""
  if ! IFS= read -r BENCH_LOCK_STATUS <"$BENCH_LOCK_READY"; then
    rm -f "$BENCH_LOCK_READY"
    echo "could not acquire the host-wide cross-language benchmark lock" >&2
    exit 2
  fi
  rm -f "$BENCH_LOCK_READY"
  if [[ "$BENCH_LOCK_STATUS" != locked ]]; then
    wait "$BENCH_LOCK_PID" 2>/dev/null || true
    unset BENCH_LOCK_PID
    printf 'ABORTED — another cross-language benchmark holds the host lock at %s.\nNo benchmark builds or timed samples were started.\n' "$BENCH_LOCK_PATH" >"$OUT/ABORTED.txt"
    echo "another cross-language benchmark holds the host lock; retry after it completes" >&2
    exit 2
  fi
fi
RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
HOST_QUALIFICATION="$OUT/host_qualification.json"
python3 - "$HOST_QUALIFICATION" "$(uname -s)" <<'PY'
import json
import hashlib
import os
import platform
import re
import sys
from pathlib import Path

output = Path(sys.argv[1])
system = sys.argv[2]
result = {
    "system": system,
    "machine": platform.machine(),
    "qualified": False,
    "allowed_cpu_count": None,
    "allowed_cpu_ids": None,
    "effective_cgroup_cpu_quota": None,
    "cgroup_quota_sources": [],
    "cgroup_membership_lines": [],
    "cgroup_mountinfo_sha256": None,
    "cgroup_namespace": None,
    "reason": "Mac timing is exploratory; the project qualification target is a 64-core x86_64 Linux host",
}

def unescape_mount(value):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)

def mapped_cgroup_dir(cgroup_path, mount_root, mount_point):
    cgroup_path = Path(cgroup_path)
    mount_root = Path(mount_root)
    try:
        relative = cgroup_path.relative_to(mount_root)
    except ValueError:
        return None
    return Path(mount_point) / relative

if system == "Linux":
    issues = []
    try:
        allowed_cpu_ids = sorted(os.sched_getaffinity(0))
        allowed = len(allowed_cpu_ids)
    except (AttributeError, OSError):
        allowed_cpu_ids = None
        allowed = os.cpu_count() or 0
        issues.append("could not read the process CPU affinity mask")
    result["allowed_cpu_count"] = allowed
    result["allowed_cpu_ids"] = allowed_cpu_ids

    memberships = []
    try:
        membership_lines = Path("/proc/self/cgroup").read_text().splitlines()
        result["cgroup_membership_lines"] = membership_lines
        for line in membership_lines:
            _, controllers, path = line.split(":", 2)
            if not controllers:
                memberships.append(("v2", path))
            elif "cpu" in controllers.split(","):
                memberships.append(("v1", path))
    except (OSError, ValueError) as error:
        issues.append(f"could not parse /proc/self/cgroup: {error}")

    mounts = []
    try:
        mountinfo_text = Path("/proc/self/mountinfo").read_text()
        result["cgroup_mountinfo_sha256"] = hashlib.sha256(mountinfo_text.encode()).hexdigest()
        for line in mountinfo_text.splitlines():
            if " - " not in line:
                continue
            before, after = line.split(" - ", 1)
            before_fields = before.split()
            after_fields = after.split()
            if len(before_fields) < 5 or len(after_fields) < 3:
                continue
            fs_type = after_fields[0]
            options = set(after_fields[2].split(","))
            if fs_type == "cgroup2":
                mounts.append(("v2", unescape_mount(before_fields[3]), unescape_mount(before_fields[4])))
            elif fs_type == "cgroup" and "cpu" in options:
                mounts.append(("v1", unescape_mount(before_fields[3]), unescape_mount(before_fields[4])))
    except OSError as error:
        issues.append(f"could not read /proc/self/mountinfo: {error}")

    try:
        self_cgroup_ns = os.readlink("/proc/self/ns/cgroup")
        init_cgroup_ns = os.readlink("/proc/1/ns/cgroup")
        result["cgroup_namespace"] = {"self": self_cgroup_ns, "init": init_cgroup_ns}
        if self_cgroup_ns != init_cgroup_ns:
            issues.append("the process is in a separate cgroup namespace, so outer CPU quotas may be hidden")
    except OSError as error:
        issues.append(f"could not compare process and init cgroup namespaces: {error}")

    quotas = []
    for kind, cgroup_path in memberships:
        matched_mounts = [mount for mount in mounts if mount[0] == kind]
        if not matched_mounts:
            issues.append(f"no mounted {kind} CPU controller matches /proc/self/cgroup")
            continue
        values_found = False
        for _, mount_root, mount_point in matched_mounts:
            if Path(mount_root) != Path("/"):
                issues.append(f"{kind} CPU controller mount root {mount_root} hides possible outer quota ancestors")
            candidate = mapped_cgroup_dir(cgroup_path, mount_root, mount_point)
            if candidate is None or not candidate.exists():
                continue
            mount_path = Path(mount_point)
            current = candidate
            while True:
                quota_path = current / ("cpu.max" if kind == "v2" else "cpu.cfs_quota_us")
                period_path = current / "cpu.cfs_period_us"
                try:
                    if kind == "v2" and quota_path.is_file():
                        quota_text, period_text = quota_path.read_text().split()[:2]
                        values_found = True
                        if quota_text != "max":
                            quota, period = int(quota_text), int(period_text)
                            if period <= 0:
                                issues.append(f"invalid cgroup v2 CPU period at {quota_path}")
                            else:
                                cpus = quota / period
                                quotas.append(cpus)
                                result["cgroup_quota_sources"].append({"quota_path": str(quota_path), "quota": quota, "period": period, "cpus": cpus})
                        else:
                            result["cgroup_quota_sources"].append({"quota_path": str(quota_path), "quota": "max", "period": int(period_text), "cpus": None})
                    elif kind == "v1" and quota_path.is_file() and period_path.is_file():
                        quota = int(quota_path.read_text().strip())
                        period = int(period_path.read_text().strip())
                        values_found = True
                        if quota >= 0:
                            if period <= 0:
                                issues.append(f"invalid cgroup v1 CPU period at {period_path}")
                            else:
                                cpus = quota / period
                                quotas.append(cpus)
                                result["cgroup_quota_sources"].append({"quota_path": str(quota_path), "period_path": str(period_path), "quota": quota, "period": period, "cpus": cpus})
                        else:
                            result["cgroup_quota_sources"].append({"quota_path": str(quota_path), "period_path": str(period_path), "quota": quota, "period": period, "cpus": None})
                except (OSError, ValueError, IndexError) as error:
                    issues.append(f"could not read CPU quota at {quota_path}: {error}")
                if current == mount_path or mount_path not in current.parents:
                    break
                current = current.parent
        if not values_found:
            issues.append(f"no readable CPU quota files found for {kind} cgroup {cgroup_path}")

    if not memberships:
        issues.append("/proc/self/cgroup exposes no v1 CPU or v2 membership")
    quota = min(quotas) if quotas else None
    result["effective_cgroup_cpu_quota"] = quota
    if platform.machine() != "x86_64":
        issues.append("the qualified host architecture is x86_64")
    if allowed < 64:
        issues.append(f"only {allowed} CPUs are allowed by affinity; at least 64 are required")
    if quota is not None and quota < 64:
        issues.append(f"effective cgroup CPU quota is {quota:.2f}; at least 64 are required")
    result["qualified"] = not issues
    result["reason"] = "; ".join(issues) if issues else "64 or more CPUs are available and no cgroup quota is below 64"

output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
if system == "Linux" and not result["qualified"]:
    print(f"Linux host is not eligible for a qualified comparison: {result['reason']}", file=sys.stderr)
    raise SystemExit(2)
PY
if ! python3 "$ROOT/scripts/bench_load_gate.py" preflight "$OUT" "$HOST_QUALIFICATION" "$(uname -s)" --require-live; then
  exit 2
fi
REPEAT="${REPEAT:-5}"
[[ "$REPEAT" =~ ^[1-9][0-9]*$ ]] || { echo "REPEAT must be a positive integer" >&2; exit 2; }
BUILD_REPEAT="${BUILD_REPEAT:-$REPEAT}"
[[ "$BUILD_REPEAT" =~ ^[1-9][0-9]*$ ]] || { echo "BUILD_REPEAT must be a positive integer" >&2; exit 2; }
COMPILE_ONLY="${COMPILE_ONLY:-0}"
[[ "$COMPILE_ONLY" == 0 || "$COMPILE_ONLY" == 1 ]] || { echo "COMPILE_ONLY must be 0 or 1" >&2; exit 2; }
PREFLIGHT_ONLY="${ELISA_BENCH_PREFLIGHT_ONLY:-0}"
[[ "$PREFLIGHT_ONLY" == 0 || "$PREFLIGHT_ONLY" == 1 ]] || { echo "ELISA_BENCH_PREFLIGHT_ONLY must be 0 or 1" >&2; exit 2; }
unset ELISA_BENCH_PREFLIGHT_ONLY
BENCH_TIMEOUT_SECONDS="${BENCH_TIMEOUT_SECONDS:-900}"
[[ "$BENCH_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "BENCH_TIMEOUT_SECONDS must be a positive integer" >&2; exit 2; }
BENCH_PROFILE="${BENCH_PROFILE:-fast}"
case "$BENCH_PROFILE" in
  fast)
    ELISA_OVERFLOW_FLAG="-foverflow=wrap"
    RUST_OVERFLOW_CHECKS="off"
    ZIG_OPTIMIZE="ReleaseFast"
    ;;
  safe)
    ELISA_OVERFLOW_FLAG="-foverflow=trap"
    RUST_OVERFLOW_CHECKS="on"
    ZIG_OPTIMIZE="ReleaseSafe"
    ;;
  *) echo "BENCH_PROFILE must be fast or safe" >&2; exit 2 ;;
esac

ELISA_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
RUNTIME_BUILD_DESCRIPTION="selected runtime object (overflow mode not inferred)"
RUNTIME_PROFILE_MODE="selected-runtime-object"
RUNTIME_PROFILE_OPT_LEVEL="<not-inferred>"
RUNTIME_PROFILE_OVERFLOW="<not-inferred>"
CLANG="${CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
RUSTC="${RUSTC:-$(command -v rustc || true)}"
ZIG="${ZIG:-$(command -v zig || true)}"

[[ -x "$ELISA_BIN" ]] || { echo "missing Elisa stage1 product: $ELISA_BIN" >&2; exit 2; }
[[ -s "$ELISA_BIN.provenance.json" ]] || { echo "missing Stage1 provenance: $ELISA_BIN.provenance.json" >&2; exit 2; }
command -v "$CLANG" >/dev/null || { echo "missing clang: $CLANG" >&2; exit 2; }
[[ -n "$RUSTC" ]] && command -v "$RUSTC" >/dev/null || { echo "rustc is required" >&2; exit 2; }
[[ -n "$ZIG" ]] && command -v "$ZIG" >/dev/null || { echo "zig is required" >&2; exit 2; }
CLANG="$(command -v "$CLANG")"
if [[ "$(uname -s)" == Darwin ]]; then
  SELECTED_CLANG_REALPATH="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$ELISA_LLVM_BIN_DIR/clang")"
  REQUESTED_CLANG_REALPATH="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$CLANG")"
  if [[ "$REQUESTED_CLANG_REALPATH" != "$SELECTED_CLANG_REALPATH" ]]; then
    echo "CLANG must be the clang from the selected newest Homebrew LLVM ($SELECTED_CLANG_REALPATH), got $REQUESTED_CLANG_REALPATH" >&2
    exit 2
  fi
  CLANG="$SELECTED_CLANG_REALPATH"
fi
CLANG_LINK_FLAGS=()
LD64_LLD=""
CLANG_LINKER_DESCRIPTION="platform default"
if [[ "$(uname -s)" == Darwin ]]; then
  LLD_PREFIX="$("$BREW" --prefix lld 2>/dev/null || true)"
  [[ -n "$LLD_PREFIX" && -x "$LLD_PREFIX/bin/ld64.lld" ]] || {
    echo "Homebrew LLD is required for macOS executable-link comparisons; install the lld formula" >&2
    exit 2
  }
  # Keep the `ld64.lld` basename so the LLD multicall binary selects its Mach-O
  # driver; resolving this symlink would pass the generic `lld` basename to Clang.
  LD64_LLD="$LLD_PREFIX/bin/ld64.lld"
  [[ -x "$LD64_LLD" ]] || { echo "selected Homebrew LLD is not executable: $LD64_LLD" >&2; exit 2; }
  CLANG_LINK_FLAGS=("-fuse-ld=$LD64_LLD")
  CLANG_LINKER_DESCRIPTION="Homebrew ld64.lld"
  export ELISA_BENCH_LD64_LLD="$LD64_LLD"
fi
export ELISA_CLANG="$CLANG"
python3 "$ROOT/scripts/stage1_provenance.py" check-exact "$ROOT" "$ELISA_BIN" || {
  echo "Stage1 product does not match the compiler sources or selected LLVM toolchain; reseed it from this checkout" >&2
  exit 2
}
if [[ "$BENCH_PROFILE" == safe ]]; then
  if [[ -n "${ELISA_RUNTIME_OBJ:-}" ]]; then
    echo "BENCH_PROFILE=safe builds a checked Elisa runtime under the output directory; unset ELISA_RUNTIME_OBJ" >&2
    exit 2
  fi
  RUNTIME="$OUT/runtime/elisacore_runtime.o"
  RUNTIME_PROFILE_MODE="rebuilt-from-source"
  RUNTIME_PROFILE_OPT_LEVEL="${ELISA_RUNTIME_OPT_LEVEL:--O2}"
  RUNTIME_PROFILE_OVERFLOW="trap"
  mkdir -p "$(dirname "$RUNTIME")"
  if ! ELISA_STAGE1_BIN="$ELISA_BIN" ELISA_RUNTIME_OBJ="$RUNTIME" ELISA_RUNTIME_OVERFLOW=trap \
    bash "$ROOT/scripts/build_runtime_object.sh" >"$OUT/runtime-build.log" 2>&1; then
    cat "$OUT/runtime-build.log" >&2
    exit 2
  fi
  RUNTIME_BUILD_DESCRIPTION="rebuilt with -foverflow=$RUNTIME_PROFILE_OVERFLOW at $RUNTIME_PROFILE_OPT_LEVEL"
fi
[[ -s "$RUNTIME" ]] || { echo "missing Elisa runtime object: $RUNTIME" >&2; exit 2; }
export ELISA_RUNTIME_OBJ="$RUNTIME"
RUSTC="$(command -v "$RUSTC")"
ZIG="$(command -v "$ZIG")"
LLVM_CONFIG="$(command -v "$LLVM_CONFIG")"
RUSTC_VERSION_VERBOSE="$("$RUSTC" --version --verbose)"
RUSTC_REAL_PATH="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$RUSTC")"
RUSTUP_RUSTC=""
if command -v rustup >/dev/null 2>&1; then
  case "$RUSTC" in
    */.cargo/bin/rustc)
      RUSTUP_RUSTC="$(rustup which rustc 2>/dev/null || true)"
      if [[ -n "$RUSTUP_RUSTC" && -x "$RUSTUP_RUSTC" ]] && [[ "$("$RUSTUP_RUSTC" --version --verbose 2>/dev/null || true)" == "$RUSTC_VERSION_VERBOSE" ]]; then
        RUSTC_REAL_PATH="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$RUSTUP_RUSTC")"
      else
        RUSTUP_RUSTC=""
      fi
      ;;
  esac
fi
tool_sha256() { python3 - "$1" <<'PY'
import hashlib
import sys
from pathlib import Path
print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
}

write_tool_manifest() {
  local manifest="$1"
  shift
  python3 - "$manifest" "$@" <<'PY'
import hashlib
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
rows = []
for raw_path in sys.argv[2:]:
    path = Path(raw_path)
    if not path.is_file():
        raise SystemExit(f"toolchain input is missing: {path}")
    rows.append((hashlib.sha256(path.read_bytes()).hexdigest(), str(path)))
manifest.write_text("".join(f"{digest}  {path}\n" for digest, path in sorted(rows)))
PY
}
ELISA_LLVM_LIBRARY="$(python3 - "$ELISA_BIN" <<'PY'
import shutil
import subprocess
import sys

if sys.platform == "darwin":
    args = ["otool", "-L", sys.argv[1]]
elif sys.platform.startswith("linux"):
    args = ["ldd", sys.argv[1]]
else:
    args = []

if not args or not shutil.which(args[0]):
    print("unknown")
else:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if "libLLVM" not in line:
                continue
            if "=>" in line:
                path = line.split("=>", 1)[1].strip()
                if path.startswith("/"):
                    print(path.split(" (", 1)[0])
                else:
                    print("unknown")
                break
            path = line.strip().split(" (compatibility version", 1)[0]
            if path.startswith("/"):
                print(path)
                break
            else:
                print("unknown")
                break
        else:
            print("static-or-not-listed")
    except (OSError, subprocess.CalledProcessError):
        print("unknown")
PY
)"
ELISA_LLVM_LIBRARY_REALPATH="unknown"
ELISA_LLVM_STATIC_LIBS=()
case "$ELISA_LLVM_LIBRARY" in
  unknown)
    echo "cannot identify the LLVM library linked into $ELISA_BIN" >&2
    exit 2
    ;;
  static-or-not-listed)
    static_libs_text="$("$LLVM_CONFIG" --link-static --libfiles 2>/dev/null || true)"
    IFS=' ' read -r -a ELISA_LLVM_STATIC_LIBS <<< "$static_libs_text"
    if [[ "${#ELISA_LLVM_STATIC_LIBS[@]}" -eq 0 ]]; then
      echo "cannot identify the static LLVM archives for $ELISA_BIN" >&2
      exit 2
    fi
    for static_lib in "${ELISA_LLVM_STATIC_LIBS[@]}"; do
      if [[ ! -f "$static_lib" ]]; then
        echo "static LLVM archive is missing: $static_lib" >&2
        exit 2
      fi
    done
    ELISA_LLVM_LIBRARY_REALPATH="static-archives"
    ;;
  *)
    if [[ ! -f "$ELISA_LLVM_LIBRARY" ]]; then
      echo "linked LLVM library is missing: $ELISA_LLVM_LIBRARY" >&2
      exit 2
    fi
    ELISA_LLVM_LIBRARY_REALPATH="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$ELISA_LLVM_LIBRARY")"
    ;;
esac
python3 - "$ELISA_BIN.provenance.json" "$LLVM_CONFIG" "$ELISA_LLVM_LIBRARY_REALPATH" "${#ELISA_LLVM_STATIC_LIBS[@]}" "${ELISA_LLVM_STATIC_LIBS[@]}" <<'PY'
import json
import shlex
import subprocess
import sys
from pathlib import Path

manifest_path, llvm_config, linked_library, static_count, *static_args = sys.argv[1:]
toolchain = json.loads(Path(manifest_path).read_text()).get("llvm_toolchain")
if not isinstance(toolchain, dict):
    raise SystemExit("Stage1 provenance does not record its LLVM toolchain")
mode = toolchain.get("link_mode")
if linked_library == "static-archives":
    if mode != "static":
        raise SystemExit(f"Stage1 provenance says LLVM link mode is {mode!r}, but no shared LLVM library is linked")
    recorded = toolchain.get("static_archives")
    if not isinstance(recorded, list) or not recorded:
        raise SystemExit("Stage1 provenance does not record the static LLVM archives")
    actual_paths = {str(Path(path).resolve()) for path in static_args[:int(static_count)]}
    recorded_paths = {str(Path(item["path"]).resolve()) for item in recorded if isinstance(item, dict) and "path" in item}
    if not actual_paths or actual_paths != recorded_paths:
        raise SystemExit("Stage1 static LLVM archives do not match the archives selected by llvm-config")
else:
    if mode != "dynamic":
        raise SystemExit(f"Stage1 provenance says LLVM link mode is {mode!r}, but a shared LLVM library is linked")
    try:
        result = subprocess.run(
            [llvm_config, "--link-shared", "--libfiles"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"could not query selected shared LLVM library: {error}") from error
    selected = {
        str(Path(path).resolve())
        for path in shlex.split(result.stdout)
        if path.endswith((".dylib", ".so")) or ".so." in path
    }
    if len(selected) != 1:
        raise SystemExit(f"llvm-config did not identify exactly one shared LLVM library: {sorted(selected)}")
    linked = str(Path(linked_library).resolve())
    if linked not in selected:
        raise SystemExit(f"Stage1 links {linked}, but selected llvm-config resolves to {sorted(selected)}")
    libdir = Path(subprocess.run(
        [llvm_config, "--libdir"], capture_output=True, text=True, check=True
    ).stdout.strip()).resolve()
    if Path(linked).parent != libdir:
        raise SystemExit(f"linked LLVM library {linked} is outside selected LLVM libdir {libdir}")
    recorded_libraries = toolchain.get("dynamic_libraries")
    if not isinstance(recorded_libraries, list) or linked not in {
        str(Path(item["path"]).resolve()) for item in recorded_libraries
        if isinstance(item, dict) and "path" in item
    }:
        raise SystemExit("Stage1 provenance does not fingerprint its selected dynamic LLVM library")
PY
[[ -z "${ELISA_STAGE1_TRIPLE:-}" ]] || {
  echo "ELISA_STAGE1_TRIPLE is set; unset it so all variants target the host" >&2
  exit 2
}

HOST_ARCH="$(uname -m)"
CLANG_CPU_FLAGS=()
case "$HOST_ARCH" in
  x86_64|i?86) CLANG_CPU_FLAGS=(-march=native) ;;
  aarch64|arm64) CLANG_CPU_FLAGS=(-mcpu=native) ;;
  *) echo "unsupported host architecture for a native CPU comparison: $HOST_ARCH" >&2; exit 2 ;;
esac

benches=(matmul sieve darray_sum darray_count_sum darray_growth darray_counted_fill packed_side_table_write packed_side_table_read)
toolchain_inputs=(
  "$ELISA_BIN"
  "$ELISA_BIN.provenance.json"
  "$RUNTIME"
  "$CLANG"
  "$RUSTC"
  "$RUSTC_REAL_PATH"
  "$ZIG"
  "$LLVM_CONFIG"
)
if [[ -n "$LD64_LLD" ]]; then
  toolchain_inputs+=("$LD64_LLD")
fi
if [[ -f "$ELISA_LLVM_LIBRARY" ]]; then
  toolchain_inputs+=("$ELISA_LLVM_LIBRARY" "$ELISA_LLVM_LIBRARY_REALPATH")
fi
if [[ "${#ELISA_LLVM_STATIC_LIBS[@]}" -gt 0 ]]; then
  toolchain_inputs+=("${ELISA_LLVM_STATIC_LIBS[@]}")
fi
write_tool_manifest "$OUT/toolchain.before.sha256" "${toolchain_inputs[@]}"
python3 - "$ELISA_BIN.provenance.json" "$OUT/toolchain.before.sha256" <<'PY'
import json
import sys
from pathlib import Path

provenance = json.loads(Path(sys.argv[1]).read_text())
toolchain = provenance.get("llvm_toolchain")
if not isinstance(toolchain, dict):
    raise SystemExit("Stage1 provenance does not contain an LLVM toolchain fingerprint")
current = {}
for line in Path(sys.argv[2]).read_text().splitlines():
    digest, separator, raw_path = line.partition("  ")
    if separator:
        current[str(Path(raw_path).resolve())] = digest
artifacts = [toolchain.get("llvm_config_artifact"), toolchain.get("clang_artifact")]
for key in ("dynamic_libraries", "static_archives"):
    artifacts.extend(toolchain.get(key) or [])
for artifact in artifacts:
    if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
        raise SystemExit("Stage1 provenance contains a malformed LLVM artifact fingerprint")
    path = str(Path(artifact["path"]).resolve())
    if current.get(path) != artifact.get("sha256"):
        raise SystemExit(f"Stage1 LLVM provenance hash does not match current toolchain input: {path}")
PY

write_source_manifest() {
  python3 - "$HERE" "$ROOT" "${benches[@]}" >"$1" <<'PY'
import hashlib
import sys
from pathlib import Path

source_dir = Path(sys.argv[1])
repository_root = Path(sys.argv[2])
benches = sys.argv[3:]
sources = [source_dir / "cross_language.sh"]
for bench in benches:
    for suffix in ("elisa", "c", "rs", "zig"):
        sources.append(source_dir / f"{bench}.{suffix}")
for directory in (repository_root / "src", repository_root / "elisacore_std", repository_root / "scripts"):
    for source in directory.rglob("*"):
        if source.is_file() and source.suffix in (".elisa", ".elisai", ".c", ".h", ".sh", ".py"):
            sources.append(source)

for source in sorted(set(sources)):
    relative = source.relative_to(repository_root)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    print(f"{digest}  {relative}")
PY
}

# Pin the exact build inputs before compiling, then verify none changed before timings.
write_source_manifest "$OUT/sources.before.sha256"
for bench in "${benches[@]}"; do
  src="$HERE/$bench"
  bin_dir="$OUT/$bench"
  mkdir -p "$bin_dir"

  # Elisa applies the same host target tuning as the other variants. BENCH_PROFILE selects
  # either wrapping arithmetic for the fast profile or checked arithmetic for the safe one.
  if [[ "$bench" == darray_counted_fill ]]; then
    # The checksum proves correctness, but not that this workload reached the
    # counted-loop reserve optimization. Its report is emitted only for this
    # untimed preflight build; timed compiler samples keep the normal environment.
    ELISA_EXPLAIN_MEMORY=1 ELISA_STAGE1_BIN="$ELISA_BIN" bash "$ROOT/scripts/elisac_stage1.sh" \
      -emit obj -O3 "$ELISA_OVERFLOW_FLAG" -o "$bin_dir/elisa.o" "$src.elisa" \
      >"$bin_dir/elisa-build.log" 2>&1
    if ! grep -Eq '^memory: buffer xs @line [0-9]+: reserve once before a counted fill$' "$bin_dir/elisa-build.log"; then
      echo "darray_counted_fill did not exercise counted-loop pre-reservation; see $bin_dir/elisa-build.log" >&2
      exit 2
    fi
  else
    ELISA_STAGE1_BIN="$ELISA_BIN" bash "$ROOT/scripts/elisac_stage1.sh" \
      -emit obj -O3 "$ELISA_OVERFLOW_FLAG" -o "$bin_dir/elisa.o" "$src.elisa" \
      >"$bin_dir/elisa-build.log" 2>&1
  fi
  "$CLANG" "${CLANG_LINK_FLAGS[@]}" $ELISA_LD_DEAD_STRIP -o "$bin_dir/elisa" "$bin_dir/elisa.o" "$RUNTIME" \
    $ELISA_LINK_EXE_FLAGS >>"$bin_dir/elisa-build.log" 2>&1

  "$CLANG" "${CLANG_LINK_FLAGS[@]}" -O3 "${CLANG_CPU_FLAGS[@]}" -o "$bin_dir/c" "$src.c" \
    >"$bin_dir/c-build.log" 2>&1
  "$RUSTC" --edition=2021 -C opt-level=3 \
    -C target-cpu=native -C "overflow-checks=$RUST_OVERFLOW_CHECKS" -o "$bin_dir/rust" "$src.rs" \
    >"$bin_dir/rust-build.log" 2>&1
  "$ZIG" build-exe "$src.zig" -O "$ZIG_OPTIMIZE" -mcpu=native -lc \
    -femit-bin="$bin_dir/zig" >"$bin_dir/zig-build.log" 2>&1
done
write_source_manifest "$OUT/sources.sha256"
if ! cmp -s "$OUT/sources.before.sha256" "$OUT/sources.sha256"; then
  echo "benchmark or compiler sources changed during the build; refusing to report results" >&2
  echo "compare $OUT/sources.before.sha256 and $OUT/sources.sha256 to identify the changes" >&2
  exit 2
fi
rm -f "$OUT/sources.before.sha256"
write_tool_manifest "$OUT/toolchain.after-build.sha256" "${toolchain_inputs[@]}"
if ! cmp -s "$OUT/toolchain.before.sha256" "$OUT/toolchain.after-build.sha256"; then
  echo "compiler or toolchain binaries changed during the build; refusing to report results" >&2
  exit 2
fi

CPU_MODEL="unknown"
if [[ "$(uname -s)" == Darwin ]]; then
  CPU_MODEL="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || sysctl -n hw.model 2>/dev/null || echo unknown)"
elif [[ -r /proc/cpuinfo ]]; then
  CPU_MODEL="$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -n 1)"
  CPU_MODEL="${CPU_MODEL:-unknown}"
fi

GIT_REV="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
ELISA_SHA="$(shasum -a 256 "$ELISA_BIN" 2>/dev/null | awk '{print $1}' || sha256sum "$ELISA_BIN" | awk '{print $1}')"
RUNTIME_SHA="$(shasum -a 256 "$RUNTIME" 2>/dev/null | awk '{print $1}' || sha256sum "$RUNTIME" | awk '{print $1}')"
ELISA_PROVENANCE="$ELISA_BIN.provenance.json"
ELISA_PROVENANCE_SHA="$(tool_sha256 "$ELISA_PROVENANCE")"
ELISA_LLVM_LIBRARY_SHA="see-static-archive-hashes-in-toolchain-manifest"
if [[ -f "$ELISA_LLVM_LIBRARY_REALPATH" ]]; then
  ELISA_LLVM_LIBRARY_SHA="$(tool_sha256 "$ELISA_LLVM_LIBRARY_REALPATH")"
fi
{
  echo "repository_revision=$GIT_REV"
  echo "host=$(uname -s) $HOST_ARCH"
  echo "host_qualification=$HOST_QUALIFICATION"
  echo "host_qualification_result=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["qualified"], d["reason"])' "$HOST_QUALIFICATION")"
  echo "cpu_model=$CPU_MODEL"
  echo "elisa_target=host (ELISA_STAGE1_TRIPLE unset; backend uses LLVM host CPU/features)"
  echo "native_cpu_flags=clang ${CLANG_CPU_FLAGS[*]}; rustc -C target-cpu=native; zig -mcpu=native"
  echo "benchmark_profile=$BENCH_PROFILE"
  echo "release_flags=Elisa -O3 $ELISA_OVERFLOW_FLAG (host CPU); C clang -O3 ${CLANG_CPU_FLAGS[*]}; Rust --edition=2021 -C opt-level=3 (default codegen units) -C target-cpu=native -C overflow-checks=$RUST_OVERFLOW_CHECKS; Zig -O $ZIG_OPTIMIZE -mcpu=native -lc"
  echo "elisa_link_dead_strip_flags=${ELISA_LD_DEAD_STRIP:-<unset>}"
  echo "elisa_link_executable_flags=${ELISA_LINK_EXE_FLAGS:-<none>}"
  echo "elisa_version=stage1 product at repository revision $GIT_REV (identified by binary SHA-256 below)"
  echo "elisa_product=$ELISA_BIN"
  echo "elisa_product_sha256=$ELISA_SHA"
  echo "elisa_provenance=$ELISA_PROVENANCE"
  echo "elisa_provenance_sha256=$ELISA_PROVENANCE_SHA"
  echo "elisa_linked_llvm_library=$ELISA_LLVM_LIBRARY"
  echo "elisa_linked_llvm_library_realpath=$ELISA_LLVM_LIBRARY_REALPATH"
  echo "elisa_linked_llvm_library_sha256=$ELISA_LLVM_LIBRARY_SHA"
  echo "elisa_static_llvm_archive_count=${#ELISA_LLVM_STATIC_LIBS[@]}"
  echo "elisa_runtime_object=$RUNTIME"
  echo "elisa_runtime_sha256=$RUNTIME_SHA"
  echo "elisa_runtime_build=$RUNTIME_BUILD_DESCRIPTION"
  echo "elisa_timed_launcher=Stage1 product invoked directly; shell wrapper freshness checks and RSS polling excluded"
  echo "clang_path=$CLANG"
  echo "clang=$($CLANG --version | head -n 1)"
  echo "clang_sha256=$(tool_sha256 "$CLANG")"
  echo "clang_linker=$CLANG_LINKER_DESCRIPTION"
  echo "clang_linker_path=${LD64_LLD:-<platform-default>}"
  if [[ -n "$LD64_LLD" ]]; then
    echo "clang_linker_version=$("$LD64_LLD" --version | head -n 1)"
    echo "clang_linker_sha256=$(tool_sha256 "$LD64_LLD")"
  else
    echo "clang_linker_version=<platform-default>"
    echo "clang_linker_sha256=<not-pinned>"
  fi
  echo "clang_target=$($CLANG -print-target-triple)"
  echo "llvm_config_path=$LLVM_CONFIG"
  echo "llvm=$("$LLVM_CONFIG" --version 2>/dev/null || echo unknown)"
  echo "llvm_config_sha256=$(tool_sha256 "$LLVM_CONFIG")"
  echo "rustc_path=$RUSTC"
  echo "rustc_version_verbose=$(printf '%s' "$RUSTC_VERSION_VERBOSE" | tr '\n' ';')"
  echo "rustc_selected_toolchain_path=${RUSTUP_RUSTC:-unresolved-from-wrapper}"
  echo "rustc_binary_path=$RUSTC_REAL_PATH"
  echo "rustc_wrapper_sha256=$(tool_sha256 "$RUSTC")"
  echo "rustc_binary_sha256=$(tool_sha256 "$RUSTC_REAL_PATH")"
  echo "rustc_executable_linker=toolchain-selected default (not pinned by this harness)"
  echo "zig_path=$ZIG"
  echo "zig=$($ZIG version)"
  echo "zig_sha256=$(tool_sha256 "$ZIG")"
  echo "zig_executable_linker=toolchain-selected default (not pinned by this harness)"
  echo "zig_cache_run_id=$RUN_ID (unique across benchmark invocations; per-sample cache directories are created before timing)"
  echo "elisa_compile_mode=ordinary semantic path (incremental shadow/cache and forced contracts unset; Stage1 object cache disabled; OS file cache is managed normally)"
  echo "elisa_environment=ELISA_STAGE1_JOBS=1; target/diagnostic/profile/memory feature switches cleared; ELISACORE_* cleared (inherited names: ${INHERITED_ELISACORE_NAMES:-none}); host flags set by the harness"
  echo "ambient_loader_allocator_overrides=cleared at runner entry (inherited names: ${BENCH_ENV_OVERRIDES_CLEARED[*]:-none})"
  echo "zig_compile_cache_policy=unique empty local/global cache directories per sample"
  echo "repeat=$REPEAT (best and median wall and child user+system CPU seconds; correctness preflight is untimed)"
  echo "build_repeat=$BUILD_REPEAT (object-only and end-to-end build samples; variants rotated per metric/sample)"
  echo "compile_only=$COMPILE_ONLY (timed runtime samples skipped when set to 1; exact checksum preflight retained)"
  echo "preflight_only=$PREFLIGHT_ONLY (exact correctness and canonical fingerprint only; no timed samples)"
  echo "load_gate=load1/effective_cpu_capacity <= 0.20; Mac uses logical CPUs and Linux uses the minimum of affinity CPUs and cgroup quota; admission checked before preflight builds and load checked before/after every timed sample; violations write ABORTED.txt"
  echo "benchmark_host_lock=$BENCH_LOCK_PATH (held until run exit; concurrent runs on this host are rejected)"
  echo "source_manifest_sha256=$(tool_sha256 "$OUT/sources.sha256")"
  echo "canonical_workload_fingerprint=canonical_workload_fingerprint.json (scope, workload, host, environment, helper, and shared-toolchain parity; includes a per-run provenance fingerprint)"
  echo "expected_canonical_workload_fingerprint=${EXPECTED_CANONICAL_FINGERPRINT:-<none>}"
  echo "toolchain_manifest_sha256=$(tool_sha256 "$OUT/toolchain.before.sha256")"
  echo "toolchain_after_run=toolchain.after-run.sha256 (checked before exit)"
  echo "executable_manifest=executables.after-build.sha256 (final binaries validated after build samples; runtime identity checked before timing and after each sample)"
  echo "runtime_executable_manifest=executables.after-runtime.sha256 (full suite only; must match after-build manifest)"
  echo "bench_timeout_seconds=$BENCH_TIMEOUT_SECONDS"
} | tee "$OUT/metadata.txt"

BENCH_CLEARED_ENV_NAMES="$(IFS=,; printf '%s' "${BENCH_ENV_OVERRIDES_CLEARED[*]}")"
ELISA_BENCH_PREFLIGHT_ONLY="$PREFLIGHT_ONLY" python3 - "$OUT" "$BUILD_REPEAT" "$BENCH_TIMEOUT_SECONDS" "$HERE" "$ROOT" \
  "$ELISA_BIN" "$RUNTIME" "$CLANG" "$RUSTC" "$ZIG" "$RUN_ID" \
  "$EXPECTED_CANONICAL_FINGERPRINT" "$COMPILE_ONLY" "$REPEAT" \
  "$BENCH_CLEARED_ENV_NAMES" "$INHERITED_ELISACORE_NAMES" \
  "$ELISA_OVERFLOW_FLAG" "$RUST_OVERFLOW_CHECKS" "$ZIG_OPTIMIZE" \
  "$RUNTIME_PROFILE_MODE" "$RUNTIME_PROFILE_OPT_LEVEL" "$RUNTIME_PROFILE_OVERFLOW" \
  "${#CLANG_CPU_FLAGS[@]}" "${CLANG_CPU_FLAGS[@]}" "${benches[@]}" <<'PY'
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

out = Path(sys.argv[1])
preflight_only = os.environ.pop("ELISA_BENCH_PREFLIGHT_ONLY", "0") == "1"
repeat = int(sys.argv[2])
timeout_seconds = int(sys.argv[3])
source_dir = Path(sys.argv[4])
root = Path(sys.argv[5])
sys.path.insert(0, str(root / "scripts"))
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
times = {
    metric: {bench: {variant: {"wall": [], "cpu": []} for variant in variants} for bench in benches}
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

def host_platform_profile():
    host = platform.uname()
    models = set()
    features = set()
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-a"], capture_output=True, text=True, check=False, timeout=5
            )
            for line in result.stdout.splitlines():
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                key = key.strip()
                value = value.strip()
                if key in ("machdep.cpu.brand_string", "hw.model") and value:
                    models.add(value)
                elif key in (
                    "machdep.cpu.features",
                    "machdep.cpu.leaf7_features",
                    "machdep.cpu.extfeatures",
                ):
                    features.update(value.split())
                elif key.startswith("hw.optional.arm.") and value == "1":
                    features.add(key.removeprefix("hw.optional.arm."))
        except (OSError, subprocess.TimeoutExpired):
            pass
    elif sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines():
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                key = key.strip().lower()
                value = value.strip()
                if key in (
                    "model name",
                    "hardware",
                    "cpu model",
                    "cpu implementer",
                    "cpu architecture",
                    "cpu part",
                    "cpu revision",
                ) and value:
                    models.add(value)
                elif key in ("flags", "features"):
                    features.update(value.split())
        except OSError:
            pass
    if not models and platform.processor():
        models.add(platform.processor())
    qualification = json.loads((out / "host_qualification.json").read_text())
    try:
        allowed_cpu_ids = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed_cpu_ids = None
    return {
        "system": host.system,
        "machine": host.machine,
        "os_release": host.release,
        "os_version": host.version,
        "cpu_models": sorted(models) or ["unknown"],
        "cpu_features": sorted(features),
        "benchmark_cpu_entitlement": {
            "logical_cpu_count": os.cpu_count(),
            "allowed_cpu_count": qualification.get("allowed_cpu_count"),
            "allowed_cpu_ids": allowed_cpu_ids,
            "effective_cgroup_cpu_quota": qualification.get("effective_cgroup_cpu_quota"),
        },
    }

def comparator_toolchain_identity():
    """Hash comparator tools while excluding candidate-specific compiler/runtime products."""
    candidate_products = {
        str(Path(elisa_bin).resolve()),
        str(Path(f"{elisa_bin}.provenance.json").resolve()),
        str(Path(runtime).resolve()),
    }
    rows = []
    for line in (out / "toolchain.before.sha256").read_text().splitlines():
        digest, separator, raw_path = line.partition("  ")
        if not separator or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
            raise RuntimeError("malformed toolchain.before.sha256 manifest")
        raw_path_obj = Path(raw_path)
        resolved_path = str(raw_path_obj.resolve())
        if resolved_path in candidate_products or raw_path_obj.name.endswith(".provenance.json"):
            continue
        rows.append({"path": resolved_path, "sha256": digest.lower()})
    if not rows:
        raise RuntimeError("toolchain manifest contains no pinned comparator tools")
    return sorted(rows, key=lambda row: (row["path"], row["sha256"]))

def benchmark_helper_hashes():
    paths = (
        root / "scripts" / "bench_load_gate.py",
        root / "scripts" / "platform.sh",
        root / "scripts" / "stage1_provenance.py",
        root / "scripts" / "elisac_stage1.sh",
        root / "scripts" / "build_runtime_object.sh",
        root / "scripts" / "write_profiler_hook_fallbacks.sh",
    )
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }

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

def run_environment_input_hashes(environment):
    names = set(ENVIRONMENT_INPUT_NAMES)
    names.update(name for name in environment if name.startswith(("ELISA_", "ELISACORE_")))
    return environment_input_hashes(environment, sorted(names))

def parity_environment_input_hashes(environment):
    """Fingerprint effective settings while normalizing candidate-specific artifact paths."""
    normalized_paths = {
        "ELISA_STAGE1_BIN": "<stage1-binary>",
        "ELISA_STAGE1_SELF": "<stage1-binary>",
        "ELISA_STAGE1_ROOT": "<stage1-source-root>",
        "ELISA_RUNTIME_OBJ": "<runtime-object>",
    }
    projected = run_environment_input_hashes(environment)
    for name, normalized_value in normalized_paths.items():
        raw = projected.get(name, {"present": False, "sha256": None})
        projected[name] = {
            "present": raw["present"],
            "normalized_value": normalized_value if raw["present"] else None,
        }
    return projected

def parse_toolchain_manifest():
    rows = []
    for line in (out / "toolchain.before.sha256").read_text().splitlines():
        digest, separator, raw_path = line.partition("  ")
        if not separator or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()) or not raw_path:
            raise RuntimeError("malformed toolchain.before.sha256 manifest")
        rows.append({"path": str(Path(raw_path).resolve()), "sha256": digest.lower()})
    return sorted(rows, key=lambda row: (row["path"], row["sha256"]))

def shared_runtime_source_manifest():
    """Fingerprint runtime source inputs independently of changing compiler sources."""
    runtime_root = root / "elisacore_std"
    if not runtime_root.is_dir():
        raise RuntimeError(f"missing runtime source directory: {runtime_root}")
    paths = [
        path for path in runtime_root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.suffix in (".elisa", ".elisai")
    ]
    paths.extend((
        root / "scripts" / "build_runtime_object.sh",
        root / "scripts" / "write_profiler_hook_fallbacks.sh",
    ))
    rows = []
    for path in sorted(set(paths)):
        if not path.is_file():
            raise RuntimeError(f"missing shared runtime source input: {path}")
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    if not any(row["path"].startswith("elisacore_std/") for row in rows):
        raise RuntimeError("shared runtime source manifest contains no runtime sources")
    manifest_bytes = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(manifest_bytes).hexdigest(), "files": rows}

def write_canonical_workload_fingerprint(observed_results):
    """Record source/checksum/status parity independently of candidate compiler sources."""
    workloads = []
    for bench in benches:
        source_hashes = {
            suffix: hashlib.sha256((source_dir / f"{bench}.{suffix}").read_bytes()).hexdigest()
            for suffix in ("elisa", "c", "rs", "zig")
        }
        observed = observed_results[bench]
        workloads.append({
            "name": bench,
            "source_sha256": source_hashes,
            "expected": {
                "checksum": expected_checksums[bench],
                "exit_status": expected_exit_statuses[bench],
            },
            "observed": {
                "checksum": observed["checksum"].strip(),
                "exit_status": observed["exit_status"],
            },
        })
    payload = {
        "schema": "canonical-codegen-workloads-v5",
        "scope": "compile_only" if compile_only else "full_runtime",
        "runner_sha256": hashlib.sha256((source_dir / "cross_language.sh").read_bytes()).hexdigest(),
        "benchmark_helper_sha256": benchmark_helper_hashes(),
        "comparator_toolchain": comparator_toolchain_identity(),
        "platform": host_platform_profile(),
        "measurement_protocol": {
            "build_repeats": repeat,
            "runtime_repeats": runtime_repeat,
            "timeout_seconds": timeout_seconds,
            "load_gate_fraction": LOAD_FRACTION,
        },
        "environment": {
            "cleared_loader_allocator_names": cleared_loader_allocator_names,
            "cleared_elisacore_names": cleared_elisacore_names,
            "ambient_inputs": environment_input_hashes(os.environ),
            "effective_build_inputs": parity_environment_input_hashes(child_env),
            "effective_runtime_inputs": parity_environment_input_hashes(os.environ),
        },
        "compile_profile": {
            "elisa": {"opt": "-O3", "overflow": elisa_overflow_flag},
            "elisa_runtime": {
                "mode": runtime_profile_mode,
                "opt_level": runtime_profile_opt_level,
                "overflow": runtime_profile_overflow,
            },
            "c": {"opt": "-O3", "cpu_flags": cpu_flags, "linker_flags": clang_linker_flags, "dead_strip_flags": dead_strip, "link_flags": link_flags},
            "rust": {"opt_level": 3, "codegen_units": "default", "overflow_checks": rust_overflow_checks, "target_cpu": "native"},
            "zig": {"optimize": zig_optimize, "target_cpu": "native"},
        },
        "workloads": workloads,
    }
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    source_manifest_bytes = (out / "sources.sha256").read_bytes()
    toolchain_manifest_bytes = (out / "toolchain.before.sha256").read_bytes()
    metadata_bytes = (out / "metadata.txt").read_bytes()
    qualification_bytes = (out / "host_qualification.json").read_bytes()
    runtime_artifact_sha256 = hashlib.sha256(Path(runtime).read_bytes()).hexdigest()
    run_provenance = {
        "scope": payload["scope"],
        "source_manifest_sha256": hashlib.sha256(source_manifest_bytes).hexdigest(),
        "toolchain_manifest_sha256": hashlib.sha256(toolchain_manifest_bytes).hexdigest(),
        "toolchain_manifest": parse_toolchain_manifest(),
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "host_qualification_sha256": hashlib.sha256(qualification_bytes).hexdigest(),
        "runtime_artifact_sha256": runtime_artifact_sha256,
        "shared_runtime_source_manifest": shared_runtime_source_manifest(),
        "build_environment_inputs": run_environment_input_hashes(child_env),
        "runtime_environment_inputs": run_environment_input_hashes(os.environ),
    }
    run_binding_bytes = json.dumps(
        {"payload": payload, "run_provenance": run_provenance},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    record = {
        "schema": payload["schema"],
        "fingerprint_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "run_fingerprint_sha256": hashlib.sha256(run_binding_bytes).hexdigest(),
        # Runtime bytes can legitimately change when this candidate compiler builds them.
        # Keep their identity per run without making workload/profile parity revision-sensitive.
        "runtime_artifact_sha256": runtime_artifact_sha256,
        "payload": payload,
        "run_provenance": run_provenance,
    }
    fingerprint_file = out / "canonical_workload_fingerprint.json"
    fingerprint_file.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if expected_fingerprint_path:
        reference_path = Path(expected_fingerprint_path)
        if reference_path.resolve() == fingerprint_file.resolve():
            mark_aborted("canonical workload fingerprint check failed", "reference cannot be the candidate output fingerprint file")
        try:
            reference = json.loads(reference_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            mark_aborted("canonical workload fingerprint check failed", f"cannot read {reference_path}: {error}")
        if not isinstance(reference, dict):
            mark_aborted("canonical workload fingerprint check failed", f"reference {reference_path} is not a JSON object")
        reference_payload = reference.get("payload")
        reference_scope = reference_payload.get("scope") if isinstance(reference_payload, dict) else None
        if reference_scope not in ("compile_only", "full_runtime"):
            mark_aborted("canonical workload fingerprint check failed", f"reference {reference_path} has an invalid run scope")
        completion_marker = "COMPILE_COMPLETE" if reference_scope == "compile_only" else "COMPLETE"
        reference_directory = reference_path.resolve().parent
        marker_path = reference_directory / completion_marker
        other_marker = reference_directory / ("COMPLETE" if completion_marker == "COMPILE_COMPLETE" else "COMPILE_COMPLETE")
        preflight_marker = reference_directory / "PREFLIGHT_COMPLETE"
        successful_timing_marker = (
            marker_path.is_file() and marker_path.stat().st_size > 0 and not other_marker.exists()
        )
        successful_preflight_marker = preflight_marker.is_file() and preflight_marker.stat().st_size > 0
        if (
            (reference_directory / "ABORTED.txt").exists()
            or not (successful_timing_marker or successful_preflight_marker)
        ):
            mark_aborted(
                "canonical workload fingerprint check failed",
                f"reference {reference_path} has no successful {completion_marker} or PREFLIGHT_COMPLETE marker",
            )
        if reference_scope != payload["scope"]:
            mark_aborted(
                "canonical workload fingerprint scope mismatch",
                f"candidate scope {payload['scope']} does not match reference scope {reference_scope!r}",
            )
        reference_provenance = reference.get("run_provenance")
        if not isinstance(reference_provenance, dict):
            mark_aborted("canonical workload fingerprint check failed", f"reference {reference_path} has no run provenance")
        reference_run_binding = json.dumps(
            {"payload": reference_payload, "run_provenance": reference_provenance},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if reference.get("run_fingerprint_sha256") != hashlib.sha256(reference_run_binding).hexdigest():
            mark_aborted("canonical workload fingerprint check failed", f"reference {reference_path} has invalid run provenance integrity")
        if reference.get("runtime_artifact_sha256") != reference_provenance.get("runtime_artifact_sha256"):
            mark_aborted("canonical workload fingerprint check failed", f"reference {reference_path} has inconsistent runtime artifact provenance")
        if (
            reference.get("schema") != record["schema"]
            or reference.get("fingerprint_sha256") != record["fingerprint_sha256"]
            or reference.get("payload") != payload
        ):
            mark_aborted(
                "canonical workload fingerprint mismatch",
                f"candidate fingerprint {record['fingerprint_sha256']} does not match reference {reference_path}",
            )
        if runtime_profile_mode == "rebuilt-from-source":
            reference_runtime_sources = reference_provenance.get("shared_runtime_source_manifest")
            candidate_runtime_sources = run_provenance["shared_runtime_source_manifest"]
            if reference_runtime_sources != candidate_runtime_sources:
                mark_aborted(
                    "shared runtime source mismatch",
                    "rebuilt-runtime comparison requires identical runtime source and build-helper inputs",
                )
        reference_runtime_sha256 = reference_provenance.get("runtime_artifact_sha256")
        if (
            not isinstance(reference_runtime_sha256, str)
            or len(reference_runtime_sha256) != 64
            or any(char not in "0123456789abcdef" for char in reference_runtime_sha256.lower())
        ):
            mark_aborted("canonical workload fingerprint check failed", f"reference {reference_path} has an invalid runtime artifact hash")
        runtime_comparison = {
            "policy": (
                "must_match_shared_selected_runtime"
                if runtime_profile_mode == "selected-runtime-object"
                else "report_both_rebuilt_runtime_hashes_allow_difference"
            ),
            "reference_sha256": reference_runtime_sha256.lower(),
            "candidate_sha256": runtime_artifact_sha256,
            "equal": reference_runtime_sha256.lower() == runtime_artifact_sha256,
        }
        run_provenance["runtime_artifact_comparison"] = runtime_comparison
        run_binding_bytes = json.dumps(
            {"payload": payload, "run_provenance": run_provenance},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        record["run_fingerprint_sha256"] = hashlib.sha256(run_binding_bytes).hexdigest()
        record["run_provenance"] = run_provenance
        record["runtime_artifact_comparison"] = runtime_comparison
        fingerprint_file.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f"runtime_artifact_policy={runtime_comparison['policy']}")
        print(f"runtime_artifact_reference_sha256={runtime_comparison['reference_sha256']}")
        print(f"runtime_artifact_candidate_sha256={runtime_comparison['candidate_sha256']}")
        print(f"runtime_artifact_hashes_equal={runtime_comparison['equal']}")
        if runtime_profile_mode == "selected-runtime-object" and not runtime_comparison["equal"]:
            mark_aborted(
                "runtime artifact parity mismatch",
                "selected runtime objects differ: "
                f"reference SHA-256 {runtime_comparison['reference_sha256']}, "
                f"candidate SHA-256 {runtime_comparison['candidate_sha256']}",
            )
    return record["fingerprint_sha256"]

def run_once(binary):
    try:
        proc = subprocess.Popen(
            [str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
    except OSError as error:
        raise RuntimeError(f"could not start correctness preflight program {binary}: {error}") from error
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise RuntimeError(f"{binary} exceeded {timeout_seconds}s correctness preflight timeout; process group killed") from error
    if proc.returncode < 0:
        raise RuntimeError(f"{binary} terminated by signal {-proc.returncode} during correctness preflight")
    if stdout and stderr:
        raise RuntimeError(f"{binary} wrote checksum data to both stdout and stderr")
    return proc.returncode, stdout, stderr

def correctness_preflight(stage):
    results = {}
    for bench in benches:
        try:
            observed = {variant: run_once(out / bench / variant) for variant in variants}
        except RuntimeError as error:
            mark_aborted("correctness preflight failed", f"{stage}: {error}")
        expected_output = f"{expected_checksums[bench]}\n".encode()
        expected_status = expected_exit_statuses[bench]
        accepted_streams = ((expected_output, b""), (b"", expected_output))
        invalid = {
            variant: (code, stdout, stderr)
            for variant, (code, stdout, stderr) in observed.items()
            if code != expected_status or (stdout, stderr) not in accepted_streams
        }
        if invalid:
            printable = {
                variant: (code, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace"))
                for variant, (code, stdout, stderr) in invalid.items()
            }
            mark_aborted(
                "correctness preflight failed",
                f"{stage}: expected exact checksum on one stream and exit status {expected_status} for {bench}; got {printable}",
            )
        results[bench] = {"checksum": expected_output.decode("utf-8"), "exit_status": expected_status}
    return results

def current_source_manifest():
    sources = [source_dir / "cross_language.sh"]
    for bench in benches:
        for suffix in ("elisa", "c", "rs", "zig"):
            sources.append(source_dir / f"{bench}.{suffix}")
    for directory in (root / "src", root / "elisacore_std", root / "scripts"):
        for source in directory.rglob("*"):
            if source.is_file() and source.suffix in (".elisa", ".elisai", ".c", ".h", ".sh", ".py"):
                sources.append(source)
    lines = []
    for source in sorted(set(sources)):
        relative = source.relative_to(root)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}\n")
    return "".join(lines).encode("utf-8")

def assert_build_sources_unchanged(stage):
    try:
        expected = (out / "sources.sha256").read_bytes()
        current = current_source_manifest()
    except OSError as error:
        mark_aborted("source manifest check failed", f"{stage}: {error}")
    if current != expected:
        mark_aborted("source manifest changed", f"{stage}: sources differ from the files used for the preflight builds")

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

def run(args, log, deadline, bench, variant, phase, log_path):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError(f"{bench}/{variant} {phase} exceeded {timeout_seconds}s; see {log_path}")
    try:
        proc = subprocess.Popen(
            args, cwd=root, env=child_env, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        raise RuntimeError(f"could not start {bench}/{variant} {phase}: {error}") from error
    try:
        status = proc.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        raise RuntimeError(f"{bench}/{variant} {phase} exceeded {timeout_seconds}s; see {log_path}") from error
    if status != 0:
        raise RuntimeError(f"{bench}/{variant} {phase} failed with status {status}; see {log_path}")

def sample_compile(bench, variant, sample):
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
        run(args, log, deadline, bench, variant, "object compilation", log_path)
    wall = (time.perf_counter_ns() - started) / 1e9
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (usage_after.ru_utime - usage_before.ru_utime) + (usage_after.ru_stime - usage_before.ru_stime)
    load_after = load_average()
    enforce_load_gate(load_after, f"after compile sample {bench}/{variant}/{sample}")
    if variant == "rust":
        rust_objects = list(compile_dir.glob("*.o"))
        if not rust_objects or any(not path.is_file() or path.stat().st_size == 0 for path in rust_objects):
            raise RuntimeError(f"{bench}/{variant} object compilation produced no object files; see {log_path}")
    elif not obj.is_file() or obj.stat().st_size == 0:
        raise RuntimeError(f"{bench}/{variant} object compilation produced no nonempty object; see {log_path}")
    return wall, cpu, load_before, load_after

def sample_build(bench, variant, sample):
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
    with log_path.open("w") as log:
        deadline = time.monotonic() + timeout_seconds
        if variant == "elisa":
            run([elisa_bin, "-emit", "obj", "-O3", elisa_overflow_flag, "-o", str(obj), str(src.with_suffix(".elisa"))], log, deadline, bench, variant, "object compilation", log_path)
            run([clang, *clang_linker_flags, *dead_strip, "-o", str(binary), str(obj), runtime, *link_flags], log, deadline, bench, variant, "link", log_path)
        elif variant == "c":
            run([clang, *clang_linker_flags, "-O3", *cpu_flags, "-o", str(binary), str(src.with_suffix(".c"))], log, deadline, bench, variant, "executable build", log_path)
        elif variant == "rust":
            run([rustc, "--edition=2021", "-C", "opt-level=3", "-C", "target-cpu=native", "-C", f"overflow-checks={rust_overflow_checks}", "-o", str(binary), str(src.with_suffix(".rs"))], log, deadline, bench, variant, "executable build", log_path)
        else:
            run([zig, "build-exe", str(src.with_suffix(".zig")), "-O", zig_optimize, "-mcpu=native", "-lc", f"-femit-bin={binary}", *cache_args], log, deadline, bench, variant, "executable build", log_path)
    wall = (time.perf_counter_ns() - started) / 1e9
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (usage_after.ru_utime - usage_before.ru_utime) + (usage_after.ru_stime - usage_before.ru_stime)
    load_after = load_average()
    enforce_load_gate(load_after, f"after build sample {bench}/{variant}/{sample}")
    if not binary.is_file() or binary.stat().st_size == 0 or not binary.stat().st_mode & 0o111:
        raise RuntimeError(f"{bench}/{variant} build did not produce an executable; see {log_path}")
    return wall, cpu, load_before, load_after

def csv_samples(path, header, samples):
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for row in samples:
            writer.writerow((*row[:4], f"{row[4]:.6f}", f"{row[5]:.6f}", *("" if value is None else f"{value:.2f}" for value in row[6:])))

for bench in benches:
    for sample in range(repeat):
        offset = sample % len(variants)
        order = variants[offset:] + variants[:offset]
        for metric, action, samples in (
            ("compile", sample_compile, compile_samples),
            ("build", sample_build, build_samples),
        ):
            for launch_order, variant in enumerate(order, 1):
                wall, cpu, load_before, load_after = action(bench, variant, sample + 1)
                times[metric][bench][variant]["wall"].append(wall)
                times[metric][bench][variant]["cpu"].append(cpu)
                samples.append((bench, sample + 1, launch_order, variant, wall, cpu, *load_before, *load_after))

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

load_header = ("benchmark", "sample", "launch_order", "variant", "wall_seconds", "child_cpu_seconds", "load1_before", "load5_before", "load15_before", "load1_after", "load5_after", "load15_after")
compile_samples_path = out / "compile_samples.csv"
build_samples_path = out / "build_samples.csv"
csv_samples(compile_samples_path, load_header, compile_samples)
csv_samples(build_samples_path, load_header, build_samples)

for metric, results_name in (("compile", "compile_results.csv"), ("build", "build_results.csv")):
    result_path = out / results_name
    with result_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("benchmark", "variant", "best_wall_seconds", "median_wall_seconds", "best_child_cpu_seconds", "median_child_cpu_seconds", "repeat_count"))
        for bench in benches:
            for variant in variants:
                wall = times[metric][bench][variant]["wall"]
                cpu = times[metric][bench][variant]["cpu"]
                writer.writerow((bench, variant, f"{min(wall):.6f}", f"{statistics.median(wall):.6f}", f"{min(cpu):.6f}", f"{statistics.median(cpu):.6f}", len(wall)))

RATIO_FIELDS = (
    ("elisa_over_rust_median_wall", "rust", "wall"),
    ("elisa_over_rust_median_child_cpu", "rust", "cpu"),
    ("elisa_over_zig_median_wall", "zig", "wall"),
    ("elisa_over_zig_median_child_cpu", "zig", "cpu"),
)
diagnostic_only_benches = {"packed_side_table_read"}
comparison_benches = [bench for bench in benches if bench not in diagnostic_only_benches]

def ratio_record(bench, metric_times):
    result = {}
    for field, comparator, axis in RATIO_FIELDS:
        elisa_median = statistics.median(metric_times[bench]["elisa"][axis])
        comparator_median = statistics.median(metric_times[bench][comparator][axis])
        if elisa_median <= 0 or comparator_median <= 0:
            raise RuntimeError(f"cannot compute positive median ratio for {bench}/{comparator}/{axis}")
        result[field] = elisa_median / comparator_median
    return result

def write_ratio_results(metric, metric_times):
    path = out / f"{metric}_ratios.csv"
    records = [ratio_record(bench, metric_times) for bench in comparison_benches]
    geometric_means = {
        field: math.exp(sum(math.log(record[field]) for record in records) / len(records))
        for field, _, _ in RATIO_FIELDS
    }
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("benchmark", *(field for field, _, _ in RATIO_FIELDS)))
        for bench, record in zip(comparison_benches, records):
            writer.writerow((bench, *(f"{record[field]:.6f}" for field, _, _ in RATIO_FIELDS)))
        writer.writerow(("geometric_mean", *(f"{geometric_means[field]:.6f}" for field, _, _ in RATIO_FIELDS)))
    return path, comparison_benches, records, geometric_means

def print_ratio_summary(title, compared_benches, records, geometric_means):
    print(f"\n{title} Elisa/comparator median ratios (<1.0 means Elisa is faster)")
    print(f"{'benchmark':<20} {'Elisa/Rust wall':>17} {'Elisa/Rust CPU':>17} {'Elisa/Zig wall':>17} {'Elisa/Zig CPU':>17}")
    print("Diagnostic-only workloads omitted from ratios and geometric mean: " + ", ".join(sorted(diagnostic_only_benches)))
    for bench, record in zip(compared_benches, records):
        values = [record[field] for field, _, _ in RATIO_FIELDS]
        print(f"{bench:<20} " + " ".join(f"{value:>17.3f}" for value in values))
    values = [geometric_means[field] for field, _, _ in RATIO_FIELDS]
    print(f"{'geometric mean':<20} " + " ".join(f"{value:>17.3f}" for value in values))

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
PY

write_source_manifest "$OUT/sources.after-build-samples.sha256"
if ! cmp -s "$OUT/sources.sha256" "$OUT/sources.after-build-samples.sha256"; then
  echo "benchmark or compiler sources changed during build-time sampling; refusing to report results" >&2
  exit 2
fi
rm -f "$OUT/sources.after-build-samples.sha256"

if [[ "$COMPILE_ONLY" == 1 ]]; then
  write_tool_manifest "$OUT/toolchain.after-run.sha256" "${toolchain_inputs[@]}"
  if ! cmp -s "$OUT/toolchain.before.sha256" "$OUT/toolchain.after-run.sha256"; then
    echo "compiler or toolchain binaries changed during measurement; results are invalid" >&2
    exit 2
  fi
  date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ' >"$OUT/COMPILE_COMPLETE"
  echo "Compile-only comparison complete. Timed runtime samples were skipped; correctness preflights passed."
  exit 0
fi

python3 - "$OUT" "$REPEAT" "$BENCH_TIMEOUT_SECONDS" "$ROOT" "${benches[@]}" <<'PY'
import csv
import hashlib
import json
import math
import os
import platform
import resource
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

out = Path(sys.argv[1])
repeat = int(sys.argv[2])
timeout_seconds = int(sys.argv[3])
root = Path(sys.argv[4])
sys.path.insert(0, str(root / "scripts"))
from bench_load_gate import LoadGateError, check_load_gate, load_average
benches = sys.argv[5:]
variants = ("elisa", "c", "rust", "zig")
checksums = {}
exit_statuses = {}

def enforce_load_gate(load, stage):
    try:
        check_load_gate(load, stage, out, platform.system(), out / "host_qualification.json", require_live_linux=True)
    except LoadGateError as error:
        raise SystemExit(str(error)) from error

preflight_path = out / "correctness_preflight.json"
try:
    preflight = json.loads(preflight_path.read_text())
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"missing or invalid correctness preflight manifest {preflight_path}: {error}") from error
if preflight.get("schema") != "cross-language-correctness-v1":
    raise SystemExit(f"unsupported correctness preflight schema in {preflight_path}")
before_timing = preflight.get("before_timing")
after_build_samples = preflight.get("after_build_samples")
if not isinstance(before_timing, dict) or before_timing != after_build_samples:
    raise SystemExit(f"correctness preflight did not pass both before and after build samples: {preflight_path}")
if set(after_build_samples) != set(benches):
    raise SystemExit(f"correctness preflight workloads do not match this run: {preflight_path}")
manifest_path = out / "executables.after-build.sha256"
if preflight.get("executable_manifest") != manifest_path.name:
    raise SystemExit(f"correctness preflight references an unexpected executable artifact manifest: {preflight_path}")
try:
    manifest_bytes = manifest_path.read_bytes()
except OSError as error:
    raise SystemExit(f"missing executable artifact manifest {manifest_path}: {error}") from error
if hashlib.sha256(manifest_bytes).hexdigest() != preflight.get("executable_manifest_sha256"):
    raise SystemExit(f"executable artifact manifest does not match correctness preflight: {manifest_path}")
expected_artifacts = {}
for line in manifest_bytes.decode("utf-8").splitlines():
    digest, separator, relative_path = line.partition("  ")
    if not separator or len(digest) != 64 or relative_path in expected_artifacts:
        raise SystemExit(f"invalid executable artifact manifest row: {line!r}")
    expected_artifacts[relative_path] = digest
expected_artifact_paths = {f"{bench}/{variant}" for bench in benches for variant in variants}
if set(expected_artifacts) != expected_artifact_paths:
    raise SystemExit(f"executable artifact manifest does not match this run: {manifest_path}")

def artifact_manifest_text():
    rows = []
    for bench in benches:
        for variant in variants:
            binary = out / bench / variant
            relative_path = f"{bench}/{variant}"
            if not binary.is_file() or not binary.stat().st_mode & 0o111:
                raise SystemExit(f"missing executable artifact {binary}")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            rows.append(f"{digest}  {relative_path}\n")
    return "".join(rows)

def verify_artifact(bench, variant, stage):
    relative_path = f"{bench}/{variant}"
    binary = out / relative_path
    try:
        actual = hashlib.sha256(binary.read_bytes()).hexdigest()
    except OSError as error:
        raise SystemExit(f"could not verify executable artifact {binary} {stage}: {error}") from error
    if actual != expected_artifacts[relative_path]:
        raise SystemExit(f"executable artifact changed {stage}: {binary}")

for bench in benches:
    record = after_build_samples[bench]
    if not isinstance(record, dict) or not isinstance(record.get("checksum"), str) or not isinstance(record.get("exit_status"), int):
        raise SystemExit(f"invalid correctness preflight record for {bench}: {preflight_path}")
    checksums[bench] = record["checksum"].encode("utf-8")
    exit_statuses[bench] = record["exit_status"]

# Tie the post-build checksums to the exact final binaries before runtime timing starts.
if artifact_manifest_text().encode("utf-8") != manifest_bytes:
    raise SystemExit(f"executable artifacts changed after correctness preflight: {manifest_path}")
enforce_load_gate(load_average(), "before the first timed runtime sample")

times = {bench: {variant: {"wall": [], "cpu": []} for variant in variants} for bench in benches}
raw_samples = []
for bench in benches:
    for sample in range(repeat):
        # Rotate launch order to reduce a fixed first/last variant bias.
        offset = sample % len(variants)
        order = variants[offset:] + variants[:offset]
        for launch_order, variant in enumerate(order):
            load_before = load_average()
            enforce_load_gate(load_before, f"before runtime sample {bench}/{variant}/{sample + 1}")
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            started = time.perf_counter_ns()
            binary = out / bench / variant
            proc = subprocess.Popen(
                [str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()
                raise RuntimeError(f"{bench}/{variant} exceeded {timeout_seconds}s timeout; process group killed") from error
            elapsed_ns = time.perf_counter_ns() - started
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            load_after = load_average()
            enforce_load_gate(load_after, f"after runtime sample {bench}/{variant}/{sample + 1}")
            if proc.returncode != exit_statuses[bench]:
                raise RuntimeError(f"timed status changed: {bench}/{variant} returned {proc.returncode}")
            if (stdout, stderr) not in ((checksums[bench], b""), (b"", checksums[bench])):
                raise RuntimeError(f"timed exact checksum output changed: {bench}/{variant}")
            verify_artifact(bench, variant, f"after runtime sample {bench}/{variant}/{sample + 1}")
            cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
            times[bench][variant]["wall"].append(elapsed_ns / 1e9)
            times[bench][variant]["cpu"].append(cpu)
            raw_samples.append((bench, sample + 1, launch_order + 1, variant, elapsed_ns / 1e9, cpu, load_before[0], load_after[0]))

runtime_manifest_bytes = artifact_manifest_text().encode("utf-8")
(out / "executables.after-runtime.sha256").write_bytes(runtime_manifest_bytes)
if runtime_manifest_bytes != manifest_bytes:
    raise SystemExit(f"executable artifacts changed during runtime sampling: {manifest_path}")

samples_path = out / "samples.csv"
with samples_path.open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(("benchmark", "sample", "launch_order", "variant", "wall_seconds", "child_cpu_seconds", "load1_before", "load1_after"))
    for row in raw_samples:
        writer.writerow((row[0], row[1], row[2], row[3], f"{row[4]:.6f}", f"{row[5]:.6f}", "" if row[6] is None else f"{row[6]:.2f}", "" if row[7] is None else f"{row[7]:.2f}"))

result_path = out / "results.csv"
with result_path.open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(("benchmark", "full_checksum", "exit_status", "variant", "best_wall_seconds", "median_wall_seconds", "best_child_cpu_seconds", "median_child_cpu_seconds", "repeat_count"))
    for bench in benches:
        for variant in variants:
            samples = times[bench][variant]
            writer.writerow((
                bench,
                checksums[bench].decode("utf-8").strip(),
                exit_statuses[bench],
                variant,
                f"{min(samples['wall']):.6f}",
                f"{statistics.median(samples['wall']):.6f}",
                f"{min(samples['cpu']):.6f}",
                f"{statistics.median(samples['cpu']):.6f}",
                len(samples["cpu"]),
            ))

runtime_ratio_fields = (
    ("elisa_over_rust_median_wall", "rust", "wall"),
    ("elisa_over_rust_median_child_cpu", "rust", "cpu"),
    ("elisa_over_zig_median_wall", "zig", "wall"),
    ("elisa_over_zig_median_child_cpu", "zig", "cpu"),
)
runtime_ratio_records = []
# The side-table read fixture uses volatile native accesses while Elisa emits
# ordinary helper accesses. Keep correctness and raw compile/build/runtime samples,
# but omit all cross-language ratios until both sides share that access contract.
diagnostic_only_benches = {"packed_side_table_read"}
runtime_comparison_benches = [bench for bench in benches if bench not in diagnostic_only_benches]
for bench in runtime_comparison_benches:
    record = {}
    for field, comparator, axis in runtime_ratio_fields:
        elisa_median = statistics.median(times[bench]["elisa"][axis])
        comparator_median = statistics.median(times[bench][comparator][axis])
        if elisa_median <= 0 or comparator_median <= 0:
            raise RuntimeError(f"cannot compute positive median ratio for {bench}/{comparator}/{axis}")
        record[field] = elisa_median / comparator_median
    runtime_ratio_records.append(record)
runtime_ratio_means = {
    field: math.exp(sum(math.log(record[field]) for record in runtime_ratio_records) / len(runtime_ratio_records))
    for field, _, _ in runtime_ratio_fields
}
runtime_ratio_path = out / "runtime_ratios.csv"
with runtime_ratio_path.open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(("benchmark", *(field for field, _, _ in runtime_ratio_fields)))
    for bench, record in zip(runtime_comparison_benches, runtime_ratio_records):
        writer.writerow((bench, *(f"{record[field]:.6f}" for field, _, _ in runtime_ratio_fields)))
    writer.writerow(("geometric_mean", *(f"{runtime_ratio_means[field]:.6f}" for field, _, _ in runtime_ratio_fields)))

print("\nFull checksums and exit statuses matched in a separate preflight; timed fresh processes were checked again (repeat count per variant: " + str(repeat) + ")")
for metric, label in (("wall", "best/median wall seconds"), ("cpu", "best/median child CPU seconds")):
    print(f"\n{label}")
    print(f"{'benchmark':<30} {'checksum':>18} {'Elisa':>17} {'C':>17} {'Rust':>17} {'Zig':>17}")
    for bench in benches:
        values = []
        for variant in variants:
            samples = times[bench][variant][metric]
            values.append(f"{min(samples):.6f}/{statistics.median(samples):.6f}")
        checksum = checksums[bench].decode("utf-8").strip()
        label = f"{bench} (diagnostic-only)" if bench in diagnostic_only_benches else bench
        print(f"{label:<30} {checksum:>18} " + " ".join(f"{value:>17}" for value in values))
print("\nGenerated runtime Elisa/comparator median ratios (<1.0 means Elisa is faster; diagnostic-only workloads are omitted)")
print(f"{'benchmark':<20} {'Elisa/Rust wall':>17} {'Elisa/Rust CPU':>17} {'Elisa/Zig wall':>17} {'Elisa/Zig CPU':>17}")
for bench, record in zip(runtime_comparison_benches, runtime_ratio_records):
    values = [record[field] for field, _, _ in runtime_ratio_fields]
    print(f"{bench:<20} " + " ".join(f"{value:>17.3f}" for value in values))
values = [runtime_ratio_means[field] for field, _, _ in runtime_ratio_fields]
print(f"{'geometric mean':<20} " + " ".join(f"{value:>17.3f}" for value in values))
print(f"\nMetadata: {out / 'metadata.txt'}")
print(f"Sources:  {out / 'sources.sha256'}")
print(f"Compile:  {out / 'compile_results.csv'}")
print(f"Builds:   {out / 'build_results.csv'}")
print(f"Ratios:   {out / 'compile_ratios.csv'}, {out / 'build_ratios.csv'}, {runtime_ratio_path}")
print(f"Samples:  {samples_path}")
print(f"Results:  {result_path}")
PY
write_tool_manifest "$OUT/toolchain.after-run.sha256" "${toolchain_inputs[@]}"
if ! cmp -s "$OUT/toolchain.before.sha256" "$OUT/toolchain.after-run.sha256"; then
  echo "compiler or toolchain binaries changed during measurement; results are invalid" >&2
  exit 2
fi
date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ' >"$OUT/COMPLETE"
