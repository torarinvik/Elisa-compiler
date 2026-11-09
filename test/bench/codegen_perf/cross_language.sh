#!/usr/bin/env bash
# Cross-language compiler and runtime comparison for the arithmetic, DArray,
# and packed side-table workloads listed below.
# See README.cross-language.md for flags, checksum semantics, and known allocator differences.
set -euo pipefail

# Optional cross-run parity gate. Keep the reference path out of compiler and workload
# subprocess environments; it is passed only to this harness's Python coordinator below.
EXPECTED_CANONICAL_FINGERPRINT="${ELISA_BENCH_EXPECT_CANONICAL_FINGERPRINT:-}"
unset ELISA_BENCH_EXPECT_CANONICAL_FINGERPRINT

# Remove inherited driver/loader overrides and allocator tuning before any
# compiler, linker, preflight executable, or timed executable is launched. Keep
# bare LD intact for linker selection.
# Keep inherited variable names for the run manifest without recording values.
BENCH_ENV_OVERRIDES_CLEARED=()
for env_name in \
  "${!DYLD_@}" "${!LD_@}" GLIBC_TUNABLES CCC_OVERRIDE_OPTIONS \
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
    ELISA_STAGE1_BIN|ELISA_STAGE1_TRIPLE|ELISA_STAGE1_CACHE|ELISA_STAGE1_JOBS|ELISA_STAGE1_PROVENANCE_ROOT) ;;
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

bind_timing_sample_provenance() {
  local scope="$1"
  python3 "$HERE/timing_sample_provenance.py" "$OUT" "$scope"
}

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
  python3 "$HERE/inherited_benchmark_lock.py" "$INHERITED_BENCH_LOCK_FD" "$BENCH_LOCK_PATH"
  [[ "$INHERITED_BENCH_LOCK_FD" =~ ^[0-9]+$ ]] || { echo "invalid inherited benchmark lock descriptor" >&2; exit 2; }
  eval "exec ${INHERITED_BENCH_LOCK_FD}>&-"
  unset ELISA_BENCH_LOCK_FD
else
  BENCH_LOCK_READY="$OUT/.benchmark-lock-ready"
  mkfifo "$BENCH_LOCK_READY"
  python3 "$HERE/hold_benchmark_lock.py" "$BENCH_LOCK_PATH" "$$" >"$BENCH_LOCK_READY" &
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
python3 "$HERE/qualify_benchmark_host.py" "$HOST_QUALIFICATION" "$(uname -s)"
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
ELISA_PROVENANCE_ROOT="${ELISA_STAGE1_PROVENANCE_ROOT:-$ROOT}"
ELISA_PROVENANCE_ROOT="$(cd -- "$ELISA_PROVENANCE_ROOT" && pwd -P)"
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
python3 "$ROOT/scripts/stage1_provenance.py" check-exact "$ELISA_PROVENANCE_ROOT" "$ELISA_BIN" || {
  echo "Stage1 product does not match its declared compiler source root or the selected LLVM toolchain" >&2
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
tool_sha256() { python3 "$HERE/hash_benchmark_tool.py" "$1"
}

write_tool_manifest() {
  local manifest="$1"
  shift
  python3 "$HERE/write_benchmark_tool_manifest.py" "$manifest" "$@"
}
ELISA_LLVM_LIBRARY="$(python3 "$HERE/select_llvm_library.py" "$ELISA_BIN"
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
python3 "$HERE/verify_llvm_provenance.py" "$ELISA_BIN.provenance.json" "$LLVM_CONFIG" "$ELISA_LLVM_LIBRARY_REALPATH" "${#ELISA_LLVM_STATIC_LIBS[@]}" "${ELISA_LLVM_STATIC_LIBS[@]}"
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
python3 "$HERE/verify_toolchain_manifest.py" "$ELISA_BIN.provenance.json" "$OUT/toolchain.before.sha256"

write_source_manifest() {
  python3 "$HERE/write_benchmark_source_manifest.py" "$HERE" "$ROOT" "${benches[@]}" >"$1"
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

BENCHMARK_GIT_REV="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
ELISA_SOURCE_GIT_REV="$(git -C "$ELISA_PROVENANCE_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
ELISA_SHA="$(shasum -a 256 "$ELISA_BIN" 2>/dev/null | awk '{print $1}' || sha256sum "$ELISA_BIN" | awk '{print $1}')"
RUNTIME_SHA="$(shasum -a 256 "$RUNTIME" 2>/dev/null | awk '{print $1}' || sha256sum "$RUNTIME" | awk '{print $1}')"
ELISA_PROVENANCE="$ELISA_BIN.provenance.json"
ELISA_PROVENANCE_SHA="$(tool_sha256 "$ELISA_PROVENANCE")"
ELISA_LLVM_LIBRARY_SHA="see-static-archive-hashes-in-toolchain-manifest"
if [[ -f "$ELISA_LLVM_LIBRARY_REALPATH" ]]; then
  ELISA_LLVM_LIBRARY_SHA="$(tool_sha256 "$ELISA_LLVM_LIBRARY_REALPATH")"
fi
if [[ "$(uname -s)" == Darwin && -x /usr/bin/time ]]; then
  RETIRED_COUNTER_METHOD="macOS /usr/bin/time -l"
elif [[ "$(uname -s)" == Darwin ]]; then
  RETIRED_COUNTER_METHOD="unavailable: /usr/bin/time is missing or not executable"
else
  RETIRED_COUNTER_METHOD="unavailable: retired-instruction counters require macOS /usr/bin/time -l"
fi
{
  echo "benchmark_repository_revision=$BENCHMARK_GIT_REV"
  echo "host=$(uname -s) $HOST_ARCH"
  echo "host_qualification=$HOST_QUALIFICATION"
  echo "host_qualification_result=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["qualified"], d["reason"])' "$HOST_QUALIFICATION")"
  echo "cpu_model=$CPU_MODEL"
  echo "elisa_target=host (ELISA_STAGE1_TRIPLE unset; backend uses LLVM host CPU/features)"
  echo "native_cpu_flags=clang ${CLANG_CPU_FLAGS[*]}; rustc -C target-cpu=native; zig -mcpu=native"
  echo "benchmark_profile=$BENCH_PROFILE"
  echo "retired_instruction_counter=$RETIRED_COUNTER_METHOD"
  echo "release_flags=Elisa -O3 $ELISA_OVERFLOW_FLAG (host CPU); C clang -O3 ${CLANG_CPU_FLAGS[*]}; Rust --edition=2021 -C opt-level=3 (default codegen units) -C target-cpu=native -C overflow-checks=$RUST_OVERFLOW_CHECKS; Zig -O $ZIG_OPTIMIZE -mcpu=native -lc"
  echo "elisa_link_dead_strip_flags=${ELISA_LD_DEAD_STRIP:-<unset>}"
  echo "elisa_link_executable_flags=${ELISA_LINK_EXE_FLAGS:-<none>}"
  echo "elisa_source_repository_revision=$ELISA_SOURCE_GIT_REV"
  echo "elisa_version=stage1 product built from compiler source root revision $ELISA_SOURCE_GIT_REV (identified by binary SHA-256 and provenance below)"
  echo "elisa_product=$ELISA_BIN"
  echo "elisa_product_sha256=$ELISA_SHA"
  echo "elisa_provenance_source_root=$ELISA_PROVENANCE_ROOT"
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
ELISA_BENCH_PREFLIGHT_ONLY="$PREFLIGHT_ONLY" python3 "$HERE/compile_benchmark.py" "$OUT" "$BUILD_REPEAT" "$BENCH_TIMEOUT_SECONDS" "$HERE" "$ROOT" \
  "$ELISA_BIN" "$RUNTIME" "$CLANG" "$RUSTC" "$ZIG" "$RUN_ID" \
  "$EXPECTED_CANONICAL_FINGERPRINT" "$COMPILE_ONLY" "$REPEAT" \
  "$BENCH_CLEARED_ENV_NAMES" "$INHERITED_ELISACORE_NAMES" \
  "$ELISA_OVERFLOW_FLAG" "$RUST_OVERFLOW_CHECKS" "$ZIG_OPTIMIZE" \
  "$RUNTIME_PROFILE_MODE" "$RUNTIME_PROFILE_OPT_LEVEL" "$RUNTIME_PROFILE_OVERFLOW" \
  "${#CLANG_CPU_FLAGS[@]}" "${CLANG_CPU_FLAGS[@]}" "${benches[@]}"

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
  bind_timing_sample_provenance compile_only
  date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ' >"$OUT/COMPILE_COMPLETE"
  echo "Compile-only comparison complete. Timed runtime samples were skipped; correctness preflights passed."
  exit 0
fi

python3 "$HERE/runtime_benchmark.py" "$OUT" "$REPEAT" "$BENCH_TIMEOUT_SECONDS" "$ROOT" "$HERE" "${benches[@]}"
write_source_manifest "$OUT/sources.after-run.sha256"
if ! cmp -s "$OUT/sources.sha256" "$OUT/sources.after-run.sha256"; then
  echo "benchmark or compiler sources changed during runtime sampling; refusing to report results" >&2
  exit 2
fi
rm -f "$OUT/sources.after-run.sha256"
write_tool_manifest "$OUT/toolchain.after-run.sha256" "${toolchain_inputs[@]}"
if ! cmp -s "$OUT/toolchain.before.sha256" "$OUT/toolchain.after-run.sha256"; then
  echo "compiler or toolchain binaries changed during measurement; results are invalid" >&2
  exit 2
fi
bind_timing_sample_provenance full_runtime
date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ' >"$OUT/COMPLETE"
