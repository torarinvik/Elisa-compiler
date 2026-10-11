#!/usr/bin/env bash
# Cross-language compiler and native runtime comparison for matmul, sieve, and darray_sum.
# See README.cross-language.md for flags, checksum semantics, and known allocator differences.
set -euo pipefail

# Compare the ordinary native compiler path. Remove inherited feature, ABI, and
# instrumentation switches before building; keep only the product override, the
# explicit host-target guard, and the controls we pin below.
unset ELISA_SEMANTIC_SERIAL ELISA_INCREMENTAL_SHADOW ELISACORE_FORCE_CONTRACTS
unset ELISA_DEBUG_NODE_COUNT
unset ELISA_PLATFORM_SOURCED
unset ELISA_LLVM_BIN_DIR ELISA_LLVM_LIBDIR ELISA_LLVM_LIBS
unset ELISA_LD_DEAD_STRIP ELISA_LINK_EXE_FLAGS
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
OUT="$(cd -- "$OUT" && pwd)"
if [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "output directory is not empty: $OUT (choose a fresh directory so failed runs cannot leave stale result CSVs)" >&2
  exit 2
fi
RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
HOST_QUALIFICATION="$OUT/host_qualification.json"
python3 - "$HOST_QUALIFICATION" "$(uname -s)" <<'PY'
import json
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
    "effective_cgroup_cpu_quota": None,
    "cgroup_quota_sources": [],
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
        allowed = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed = os.cpu_count() or 0
        issues.append("could not read the process CPU affinity mask")
    result["allowed_cpu_count"] = allowed

    memberships = []
    try:
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            _, controllers, path = line.split(":", 2)
            if not controllers:
                memberships.append(("v2", path))
            elif "cpu" in controllers.split(","):
                memberships.append(("v1", path))
    except (OSError, ValueError) as error:
        issues.append(f"could not parse /proc/self/cgroup: {error}")

    mounts = []
    try:
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
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
REPEAT="${REPEAT:-5}"
[[ "$REPEAT" =~ ^[1-9][0-9]*$ ]] || { echo "REPEAT must be a positive integer" >&2; exit 2; }
BUILD_REPEAT="${BUILD_REPEAT:-$REPEAT}"
[[ "$BUILD_REPEAT" =~ ^[1-9][0-9]*$ ]] || { echo "BUILD_REPEAT must be a positive integer" >&2; exit 2; }
COMPILE_ONLY="${COMPILE_ONLY:-0}"
[[ "$COMPILE_ONLY" == 0 || "$COMPILE_ONLY" == 1 ]] || { echo "COMPILE_ONLY must be 0 or 1" >&2; exit 2; }
BENCH_TIMEOUT_SECONDS="${BENCH_TIMEOUT_SECONDS:-900}"
[[ "$BENCH_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "BENCH_TIMEOUT_SECONDS must be a positive integer" >&2; exit 2; }

ELISA_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
CLANG="${CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
RUSTC="${RUSTC:-$(command -v rustc || true)}"
ZIG="${ZIG:-$(command -v zig || true)}"

[[ -x "$ELISA_BIN" ]] || { echo "missing Elisa stage1 product: $ELISA_BIN" >&2; exit 2; }
[[ -s "$ELISA_BIN.provenance.json" ]] || { echo "missing Stage1 provenance: $ELISA_BIN.provenance.json" >&2; exit 2; }
python3 "$ROOT/scripts/stage1_provenance.py" check "$ROOT" "$ELISA_BIN" || {
  echo "Stage1 product does not match the compiler sources in $ROOT; rebuild it from this checkout" >&2
  exit 2
}
[[ -s "$RUNTIME" ]] || { echo "missing Elisa runtime object: $RUNTIME" >&2; exit 2; }
command -v "$CLANG" >/dev/null || { echo "missing clang: $CLANG" >&2; exit 2; }
[[ -n "$RUSTC" ]] && command -v "$RUSTC" >/dev/null || { echo "rustc is required" >&2; exit 2; }
[[ -n "$ZIG" ]] && command -v "$ZIG" >/dev/null || { echo "zig is required" >&2; exit 2; }
CLANG="$(command -v "$CLANG")"
export ELISA_CLANG="$CLANG"
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

benches=(matmul sieve darray_sum)
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
if [[ -f "$ELISA_LLVM_LIBRARY" ]]; then
  toolchain_inputs+=("$ELISA_LLVM_LIBRARY" "$ELISA_LLVM_LIBRARY_REALPATH")
fi
if [[ "${#ELISA_LLVM_STATIC_LIBS[@]}" -gt 0 ]]; then
  toolchain_inputs+=("${ELISA_LLVM_STATIC_LIBS[@]}")
fi
write_tool_manifest "$OUT/toolchain.before.sha256" "${toolchain_inputs[@]}"

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

  # Elisa applies the same host target tuning as the other variants. Overflow checks are
  # disabled only because these fixed workloads are bounded and release comparison is the
  # intended mode; the checked mode remains available by changing this flag explicitly.
  ELISA_STAGE1_BIN="$ELISA_BIN" bash "$ROOT/scripts/elisac_stage1.sh" \
    -emit obj -O3 -foverflow=wrap -o "$bin_dir/elisa.o" "$src.elisa" \
    >"$bin_dir/elisa-build.log" 2>&1
  "$CLANG" $ELISA_LD_DEAD_STRIP -o "$bin_dir/elisa" "$bin_dir/elisa.o" "$RUNTIME" \
    $ELISA_LINK_EXE_FLAGS >>"$bin_dir/elisa-build.log" 2>&1

  "$CLANG" -O3 "${CLANG_CPU_FLAGS[@]}" -o "$bin_dir/c" "$src.c" \
    >"$bin_dir/c-build.log" 2>&1
  "$RUSTC" --edition=2021 -C opt-level=3 -C codegen-units=1 \
    -C target-cpu=native -C overflow-checks=off -o "$bin_dir/rust" "$src.rs" \
    >"$bin_dir/rust-build.log" 2>&1
  "$ZIG" build-exe "$src.zig" -O ReleaseFast -mcpu=native -lc \
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
  echo "release_flags=Elisa -O3 -foverflow=wrap; C clang -O3; Rust -C opt-level=3 -C overflow-checks=off; Zig -O ReleaseFast"
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
  echo "elisa_timed_launcher=Stage1 product invoked directly; shell wrapper freshness checks and RSS polling excluded"
  echo "clang_path=$CLANG"
  echo "clang=$($CLANG --version | head -n 1)"
  echo "clang_sha256=$(tool_sha256 "$CLANG")"
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
  echo "zig_path=$ZIG"
  echo "zig=$($ZIG version)"
  echo "zig_sha256=$(tool_sha256 "$ZIG")"
  echo "zig_cache_run_id=$RUN_ID (unique across benchmark invocations; per-sample cache directories are created before timing)"
  echo "elisa_compile_mode=ordinary semantic path (incremental shadow/cache and forced contracts unset; Stage1 object cache disabled; OS file cache is managed normally)"
  echo "elisa_environment=ELISA_STAGE1_JOBS=1; target/diagnostic/profile/memory feature switches cleared; host flags set by the harness"
  echo "zig_compile_cache_policy=unique empty local/global cache directories per sample"
  echo "repeat=$REPEAT (best and median wall and child user+system CPU seconds; correctness preflight is untimed)"
  echo "build_repeat=$BUILD_REPEAT (object-only and end-to-end build samples; variants rotated per metric/sample)"
  echo "compile_only=$COMPILE_ONLY (runtime checksum and timing phase skipped when set to 1)"
  echo "source_manifest_sha256=$(tool_sha256 "$OUT/sources.sha256")"
  echo "toolchain_manifest_sha256=$(tool_sha256 "$OUT/toolchain.before.sha256")"
  echo "toolchain_after_run=toolchain.after-run.sha256 (checked before exit)"
  echo "bench_timeout_seconds=$BENCH_TIMEOUT_SECONDS"
} | tee "$OUT/metadata.txt"

python3 - "$OUT" "$BUILD_REPEAT" "$BENCH_TIMEOUT_SECONDS" "$HERE" "$ROOT" \
  "$ELISA_BIN" "$RUNTIME" "$CLANG" "$RUSTC" "$ZIG" "$RUN_ID" \
  "${CLANG_CPU_FLAGS[@]}" "${benches[@]}" <<'PY'
import csv
import os
import resource
import shlex
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

out = Path(sys.argv[1])
repeat = int(sys.argv[2])
timeout_seconds = int(sys.argv[3])
source_dir = Path(sys.argv[4])
root = Path(sys.argv[5])
elisa_bin, runtime, clang, rustc, zig = sys.argv[6:11]
elisa_bin, runtime, clang, rustc, zig = (str(Path(path).resolve()) for path in (elisa_bin, runtime, clang, rustc, zig))
run_id = sys.argv[11]
cpu_flags = sys.argv[12:-3]
benches = sys.argv[-3:]
variants = ("elisa", "c", "rust", "zig")
dead_strip = shlex.split(os.environ.get("ELISA_LD_DEAD_STRIP", ""))
link_flags = shlex.split(os.environ.get("ELISA_LINK_EXE_FLAGS", ""))
log_root = out / "build-samples"
child_env = os.environ.copy()
for name in list(child_env):
    if name.startswith(("ELISA_STAGE1_", "ELISA_DISABLE_MEMORY_", "ELISA_INCREMENTAL_", "ELISA_DBG_", "ELISA_EXPLAIN_")) or name in ("ELISACORE_FORCE_CONTRACTS", "ELISA_SEMANTIC_SERIAL", "ELISA_DEBUG_NODE_COUNT"):
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

def load_average():
    try:
        return os.getloadavg()
    except (AttributeError, OSError):
        return (None, None, None)

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
    obj = build_dir / f"{variant}.compile.o"
    cache_args = zig_cache_args(bench, "object", sample) if variant == "zig" else []
    load_before = load_average()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter_ns()
    with log_path.open("w") as log:
        deadline = time.monotonic() + timeout_seconds
        if variant == "elisa":
            args = [elisa_bin, "-emit", "obj", "-O3", "-foverflow=wrap", "-o", str(obj), str(src.with_suffix(".elisa"))]
        elif variant == "c":
            args = [clang, "-O3", *cpu_flags, "-c", "-o", str(obj), str(src.with_suffix(".c"))]
        elif variant == "rust":
            args = [rustc, "--edition=2021", "-C", "opt-level=3", "-C", "codegen-units=1", "-C", "target-cpu=native", "-C", "overflow-checks=off", "--emit=obj", "-o", str(obj), str(src.with_suffix(".rs"))]
        else:
            args = [zig, "build-obj", str(src.with_suffix(".zig")), "-O", "ReleaseFast", "-mcpu=native", "-lc", f"-femit-bin={obj}", *cache_args]
        run(args, log, deadline, bench, variant, "object compilation", log_path)
    wall = (time.perf_counter_ns() - started) / 1e9
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (usage_after.ru_utime - usage_before.ru_utime) + (usage_after.ru_stime - usage_before.ru_stime)
    load_after = load_average()
    if not obj.is_file():
        raise RuntimeError(f"{bench}/{variant} object compilation produced no object; see {log_path}")
    return wall, cpu, load_before, load_after

def sample_build(bench, variant, sample):
    src = source_dir / bench
    build_dir = out / bench
    binary = build_dir / variant
    obj = build_dir / "elisa-build.o"
    log_path = log_root / bench / f"{variant}-executable-{sample:02d}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cache_args = zig_cache_args(bench, "executable", sample) if variant == "zig" else []
    load_before = load_average()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter_ns()
    with log_path.open("w") as log:
        deadline = time.monotonic() + timeout_seconds
        if variant == "elisa":
            run([elisa_bin, "-emit", "obj", "-O3", "-foverflow=wrap", "-o", str(obj), str(src.with_suffix(".elisa"))], log, deadline, bench, variant, "object compilation", log_path)
            run([clang, *dead_strip, "-o", str(binary), str(obj), runtime, *link_flags], log, deadline, bench, variant, "link", log_path)
        elif variant == "c":
            run([clang, "-O3", *cpu_flags, "-o", str(binary), str(src.with_suffix(".c"))], log, deadline, bench, variant, "executable build", log_path)
        elif variant == "rust":
            run([rustc, "--edition=2021", "-C", "opt-level=3", "-C", "codegen-units=1", "-C", "target-cpu=native", "-C", "overflow-checks=off", "-o", str(binary), str(src.with_suffix(".rs"))], log, deadline, bench, variant, "executable build", log_path)
        else:
            run([zig, "build-exe", str(src.with_suffix(".zig")), "-O", "ReleaseFast", "-mcpu=native", "-lc", f"-femit-bin={binary}", *cache_args], log, deadline, bench, variant, "executable build", log_path)
    wall = (time.perf_counter_ns() - started) / 1e9
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (usage_after.ru_utime - usage_before.ru_utime) + (usage_after.ru_stime - usage_before.ru_stime)
    load_after = load_average()
    if not binary.is_file() or not binary.stat().st_mode & 0o111:
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

def print_summary(metric, title):
    print(f"\n{title} (median wall seconds / child CPU seconds)")
    print(f"{'benchmark':<12} {'Elisa':>21} {'C':>21} {'Rust':>21} {'Zig':>21}")
    for bench in benches:
        values = [f"{statistics.median(times[metric][bench][variant]['wall']):.6f}/{statistics.median(times[metric][bench][variant]['cpu']):.6f}" for variant in variants]
        print(f"{bench:<12} " + " ".join(f"{value:>21}" for value in values))

print_summary("compile", "Object-only compiler time")
print_summary("build", "End-to-end executable build time")
print(f"Object compile samples/results: {compile_samples_path} / {out / 'compile_results.csv'}")
print(f"Executable build samples/results: {build_samples_path} / {out / 'build_results.csv'}")
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
  echo "Compile-only comparison complete. Runtime checks and measurements were skipped."
  exit 0
fi

python3 - "$OUT" "$REPEAT" "$BENCH_TIMEOUT_SECONDS" "${benches[@]}" <<'PY'
import csv
import os
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
benches = sys.argv[4:]
variants = ("elisa", "c", "rust", "zig")
checksums = {}
exit_statuses = {}
expected_checksums = {
    "matmul": "-432360",
    "sieve": "19937370",
    "darray_sum": "751804663071387784",
}
expected_exit_statuses = {"matmul": 113, "sieve": 189, "darray_sum": 152}

def run_once(binary):
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
        raise RuntimeError(f"{binary} exceeded {timeout_seconds}s timeout; process group killed") from error
    if proc.returncode < 0:
        raise RuntimeError(f"{binary} terminated by signal {-proc.returncode}")
    if stdout and stderr:
        raise RuntimeError(f"{binary} wrote checksum data to both stdout and stderr")
    return proc.returncode, stdout, stderr

# Correctness is a gate: compare full-width checksum output and process status before timing.
for bench in benches:
    observed = {variant: run_once(out / bench / variant) for variant in variants}
    statuses = {variant: result[0] for variant, result in observed.items()}
    outputs = {variant: result[1] or result[2] for variant, result in observed.items()}
    if len(set(statuses.values())) != 1 or len(set(outputs.values())) != 1:
        printable = {variant: (code, (stdout or stderr).decode("utf-8", errors="replace")) for variant, (code, stdout, stderr) in observed.items()}
        raise SystemExit(f"full-checksum mismatch for {bench}: {printable}")
    expected_output = f"{expected_checksums[bench]}\n".encode()
    if outputs["elisa"] != expected_output or statuses["elisa"] != expected_exit_statuses[bench]:
        actual = (outputs["elisa"].decode("utf-8", errors="replace"), statuses["elisa"])
        raise SystemExit(f"independent checksum mismatch for {bench}: expected {(expected_checksums[bench], expected_exit_statuses[bench])}, got {actual}")
    checksums[bench] = outputs["elisa"]
    exit_statuses[bench] = statuses["elisa"]

times = {bench: {variant: {"wall": [], "cpu": []} for variant in variants} for bench in benches}
raw_samples = []
for bench in benches:
    for sample in range(repeat):
        # Rotate launch order to reduce a fixed first/last variant bias.
        offset = sample % len(variants)
        order = variants[offset:] + variants[:offset]
        for launch_order, variant in enumerate(order):
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
            if proc.returncode != exit_statuses[bench]:
                raise RuntimeError(f"timed status changed: {bench}/{variant} returned {proc.returncode}")
            if (stdout and stderr) or (stdout or stderr) != checksums[bench]:
                raise RuntimeError(f"timed full checksum changed: {bench}/{variant}")
            cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
            times[bench][variant]["wall"].append(elapsed_ns / 1e9)
            times[bench][variant]["cpu"].append(cpu)
            raw_samples.append((bench, sample + 1, launch_order + 1, variant, elapsed_ns / 1e9, cpu))

samples_path = out / "samples.csv"
with samples_path.open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(("benchmark", "sample", "launch_order", "variant", "wall_seconds", "child_cpu_seconds"))
    for row in raw_samples:
        writer.writerow((row[0], row[1], row[2], row[3], f"{row[4]:.6f}", f"{row[5]:.6f}"))

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

print("\nFull checksums and exit statuses matched in a separate preflight; timed fresh processes were checked again (repeat count per variant: " + str(repeat) + ")")
for metric, label in (("wall", "best/median wall seconds"), ("cpu", "best/median child CPU seconds")):
    print(f"\n{label}")
    print(f"{'benchmark':<12} {'checksum':>8} {'Elisa':>17} {'C':>17} {'Rust':>17} {'Zig':>17}")
    for bench in benches:
        values = []
        for variant in variants:
            samples = times[bench][variant][metric]
            values.append(f"{min(samples):.6f}/{statistics.median(samples):.6f}")
        checksum = checksums[bench].decode("utf-8").strip()
        print(f"{bench:<12} {checksum:>18} " + " ".join(f"{value:>17}" for value in values))
print(f"\nMetadata: {out / 'metadata.txt'}")
print(f"Sources:  {out / 'sources.sha256'}")
print(f"Compile:  {out / 'compile_results.csv'}")
print(f"Builds:   {out / 'build_results.csv'}")
print(f"Samples:  {samples_path}")
print(f"Results:  {result_path}")
PY
write_tool_manifest "$OUT/toolchain.after-run.sha256" "${toolchain_inputs[@]}"
if ! cmp -s "$OUT/toolchain.before.sha256" "$OUT/toolchain.after-run.sha256"; then
  echo "compiler or toolchain binaries changed during measurement; results are invalid" >&2
  exit 2
fi
date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ' >"$OUT/COMPLETE"
