#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/platform.sh"  # host flags/paths: scripts/platform.sh
# Host-facing entry point for the stage1 product compiler.
#
# Since §4.6 this parses NOTHING. `bin/elisac-stage1` is the compiler's only front door:
# every flag, every emit mode, include expansion, linking, the WASM packaging and the
# Python extension pipeline are its own. What is left here is the two jobs that are
# genuinely the host's:
#
#   * the SEED build (`--seed` / `--emit-driver`), which needs a bootstrap compiler, and the refusal to
#     run a product older than the sources it was built from;
#   * running the compiler as a watched child so a runaway compile is killed with a message
#     rather than by the OS — the one thing `exec` cannot do.
#
# Everything else it does is hand the driver the toolchain paths it resolved: the LLVM
# installation that matches the C API the product was built against, and the repository
# root.
#
# Usage:
#   elisac_stage1.sh -o out.o source.elisa
#   elisac_stage1.sh -emit wasm -o demo.wasm source.elisa
#   elisac_stage1.sh --seed          # seed build using the selected bootstrap compiler
#   elisac_stage1.sh --emit-driver   # only build the product binary (needs seed elisac)
set -euo pipefail

# macOS upgrades can leave the selected Xcode SDK/linker in a state that
# requires an interactive license agreement. Prefer the installed Command Line
# Tools for headless compiler gates unless the caller explicitly selected a
# developer directory.
if [[ -z "${DEVELOPER_DIR:-}" && -d /Library/Developer/CommandLineTools ]]; then
  export DEVELOPER_DIR=/Library/Developer/CommandLineTools
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
# `ELISA_STAGE1_BIN` is a product override, but callers commonly obtain it from
# `command -v elisac-stage1`, which is the installed host wrapper rather than the
# snapshot's product. Preserving that wrapper as BIN makes the product re-enter
# this script recursively through ELISA_STAGE1_SELF. Normalize wrapper overrides
# to the product in the same snapshot before exporting the self path below.
if [[ -n "${ELISA_STAGE1_BIN:-}" && -f "$BIN" ]] && grep -a -q '^#!/usr/bin/env bash$' "$BIN"; then
  BIN="$ROOT/bin/elisac-stage1"
fi
LLVM_CONFIG="${LLVM_CONFIG:-$ELISA_LLVM_BIN_DIR/llvm-config}"
# Keep the host linker in the same LLVM installation as the C API library used to
# build the stage1 product. Apple clang can link ordinary objects, but it may not
# parse textual IR printed by a newer Homebrew LLVM (for example, LLVM 22 emits
# attributes Apple clang 21 does not understand).
LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$(dirname -- "$LLVM_CONFIG")}"
ELISA_CLANG_TOOL="${ELISA_CLANG:-$LLVM_BIN_DIR/clang}"
if [[ ! -x "$ELISA_CLANG_TOOL" ]]; then
  ELISA_CLANG_TOOL="$(command -v clang || true)"
fi
if [[ -x "$ELISA_CLANG_TOOL" ]]; then
  export ELISA_CLANG="$ELISA_CLANG_TOOL"
fi
# `ELISA_RUNTIME_OBJ=none` is an explicit product-link mode: emit only the
# module object so a dependency graph can provide one shared Elisa runtime
# archive. An unset value retains the normal standalone archive behavior.
ELISA_OMIT_RUNTIME=0
if [[ "${ELISA_RUNTIME_OBJ:-}" == "none" ]]; then
  ELISA_OMIT_RUNTIME=1
fi
# Prefer LLVM's archive tool on macOS. `/usr/bin/ar` is an Xcode shim and
# refuses to run until the machine-wide Xcode license has been accepted.
if [[ -z "${ELISA_AR:-}" ]]; then
  if [[ -x "$LLVM_BIN_DIR/llvm-ar" ]]; then
    export ELISA_AR="$LLVM_BIN_DIR/llvm-ar"
  else
    export ELISA_AR="$(command -v ar || true)"
  fi
fi
# Prefer the canonical Elisa-core checkout in both a top-level compiler checkout
# and a nested profiler worktree. The old `../stage0/.../elisac-local` default
# named a worktree that no longer exists, while a single fixed `../../` depth is
# wrong for `elisa-compiler-worktrees/profiler`. Callers can still select an
# explicit compiler with ELISACORE_BIN.
if [[ -n "${ELISACORE_BIN:-}" ]]; then
  BOOTSTRAP_BIN="$ELISACORE_BIN"
else
  BOOTSTRAP_BIN=""
  # Inside a linked worktree (.claude/worktrees/*) the relative paths below miss; the main
  # checkout is the parent of the shared git dir.
  # Installed snapshots intentionally omit .git. Treat that as the standalone
  # compiler root instead of letting set -e abort the product launcher.
  main_checkout="$(cd "$ROOT" && git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  main_checkout="${main_checkout%/.git}"
  for bootstrap_candidate in \
      "${main_checkout:-$ROOT}/../../Go projects/Elisa-core/compiler/bin/elisac" \
      "$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac" \
      "$ROOT/../../../Go projects/Elisa-core/compiler/bin/elisac"; do
    if [[ -x "$bootstrap_candidate" ]]; then
      BOOTSTRAP_BIN="$bootstrap_candidate"
      break
    fi
  done
  BOOTSTRAP_BIN="${BOOTSTRAP_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
fi
# Host predicates for the product's `static if ELISA_TARGET_OS_*` / `PLATFORM_*` consts and
# the project system's platform key (see register_target_consts / host_platform_name). stage0
# reads runtime.GOOS; the self-hosted compiler reads these flags, exported once here.
if [[ "$(uname -s)" == "Linux" ]]; then export ELISA_HOST_LINUX=1; fi
# Set by hand to CROSS-compile for Windows; exported here too so a compiler built
# under MSYS/MinGW answers its own platform rather than macOS.
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) export ELISA_HOST_WINDOWS=1 ;; esac
if [[ "$(uname -m)" == "x86_64" ]]; then export ELISA_HOST_X86_64=1; fi
# Include expansion is a host-side Python step. Resolve the same interpreter selected by
# `PYTHON_BIN` (including a command name such as `python3.14`) before any emit mode runs so
# custom toolchains are honored consistently by the wrapper and its recursive invocations.
resolve_python_tools() {
  PYTHON_HOST="${PYTHON_BIN:-$(command -v python3 || true)}"
  if [[ -n "${PYTHON_BIN:-}" && "$PYTHON_BIN" != */* ]]; then
    PYTHON_HOST="$(command -v "$PYTHON_BIN" || true)"
  fi
  PYTHON_CONFIG_HOST="${PYTHON_CONFIG:-}"
  if [[ -n "${PYTHON_CONFIG_HOST}" && "$PYTHON_CONFIG_HOST" != */* ]]; then
    PYTHON_CONFIG_HOST="$(command -v "$PYTHON_CONFIG_HOST" || true)"
  elif [[ -z "${PYTHON_CONFIG_HOST}" && -n "${PYTHON_BIN:-}" ]]; then
    python_config_sibling="${PYTHON_HOST}-config"
    if [[ -x "$python_config_sibling" ]]; then
      PYTHON_CONFIG_HOST="$python_config_sibling"
    else
      PYTHON_CONFIG_HOST="$(command -v python3-config || true)"
    fi
  elif [[ -z "${PYTHON_CONFIG_HOST}" ]]; then
    PYTHON_CONFIG_HOST="$(command -v python3-config || true)"
  fi

}

validate_python_toolchain() {
  # A generic `python3-config` on PATH is not guaranteed to belong to the
  # interpreter selected above.  On this host `/usr/bin/python3` is Python 3.9
  # while Homebrew's `python3-config` is Python 3.14; mixing those headers with
  # the selected runtime produces an extension that compiles but fails at import
  # time (for example with an unresolved `_PyObject_DelAttrString`).  Reject an
  # explicitly supplied mismatch and discard an implicit one so the pymodule-so
  # path can derive the include directory from the selected interpreter itself.
  if [[ -x "$PYTHON_HOST" && -x "$PYTHON_CONFIG_HOST" ]]; then
    python_host_version="$("$PYTHON_HOST" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
    python_config_includes="$("$PYTHON_CONFIG_HOST" --includes 2>/dev/null || true)"
    python_config_version="$(printf '%s\n' "$python_config_includes" | sed -nE 's/.*python([0-9]+)\.([0-9]+).*/\1.\2/p' | head -n 1)"
    if [[ -n "$python_host_version" && -n "$python_config_version" && "$python_host_version" != "$python_config_version" ]]; then
      if [[ -n "${PYTHON_CONFIG:-}" ]]; then
        echo "python toolchain mismatch: $PYTHON_HOST is Python $python_host_version but $PYTHON_CONFIG is Python $python_config_version" >&2
        exit 2
      fi
      PYTHON_CONFIG_HOST=""
    fi
  fi
}
resolve_python_tools

# Include expansion is the DRIVER's (expand_includes in src/driver/elisac.elisa): it walks
# the include graph itself, publishes the original-file line map and the stage0 offset map,
# and decides the `# smt` and trusted-std facts from its own expanded buffer. The Python
# flattener that lived here counted CHARACTERS where stage0 counts BYTES, so its offset map
# was wrong on any non-ASCII source (§4.1).

terminate_guarded_pid() {
  local pid="$1" ticks=0
  kill -TERM "$pid" 2>/dev/null || true
  while kill -0 "$pid" 2>/dev/null && [[ "$ticks" -lt 20 ]]; do
    sleep 0.1
    ticks=$((ticks + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}

source "$ROOT/scripts/process_rss.sh"
source "$ROOT/scripts/elisac_stage1_seed.sh"

if [[ "${1:-}" == "--seed" ]]; then
  export ELISA_STAGE1_SEED_BOOTSTRAP_BIN="$BOOTSTRAP_BIN"
  ELISA_STAGE1_SEED_BOOTSTRAP_KIND="$("${PYTHON_HOST:-python3}" "$ROOT/scripts/stage1_provenance.py" bootstrap-kind "$BOOTSTRAP_BIN")"
  export ELISA_STAGE1_SEED_BOOTSTRAP_KIND
  export ELISA_STAGE1_SEED_CLANG="$ELISA_CLANG_TOOL"
  bash "$ROOT/scripts/assert_stage0_fresh.sh" "$BOOTSTRAP_BIN"
  seed_input_fingerprint="$("${PYTHON_HOST:-python3}" "$ROOT/scripts/stage1_provenance.py" inputs "$ROOT")"
  ELISA_STAGE1_SEED_INPUTS="$seed_input_fingerprint"
  seed_build
  "${PYTHON_HOST:-python3}" "$ROOT/scripts/stage1_provenance.py" record "$ROOT" "$BIN" "$seed_input_fingerprint"
  exit 0
fi

if [[ ! -x "$BIN" ]]; then
  echo "stage1 product binary missing: $BIN (run: $0 --seed once)" >&2
  exit 2
fi

# Provenance is a driver diagnostic, not part of the emitted program/report.
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$BIN" >&2

run_stage1_driver_guarded() {
  local driver_pid driver_rss driver_peak=0 driver_rc=0
  local driver_max_rss_kb="${ELISA_STAGE1_MAX_RSS_KB:-4194304}"
  local driver_rss_poll_seconds="${ELISA_STAGE1_RSS_POLL_SECONDS:-0.05}"
  # The poll BACKS OFF exponentially from 2ms up to the configured interval. A
  # fixed 50ms first sleep dominated small compiles outright — a differential-
  # corpus program compiles in ~10ms, and the guard added 50ms of pure wall to
  # every one of the ~4900 wrapper invocations a full gate makes (~4 minutes of
  # sleeping per gate). A runaway compile still meets the full-interval poll
  # within a few iterations, so the guard's protection is unchanged.
  # Polls are fork-free on Linux (scripts/process_rss.sh): the backoff is integer
  # microseconds, the RSS comes from /proc, the sleep is a builtin timed read.
  local driver_poll_us=2000 driver_poll_cap_us
  process_seconds_to_us "$driver_rss_poll_seconds"
  driver_poll_cap_us="$PROCESS_US"
  # stdin is closed rather than fed: the stdin wire protocol is still the driver's other
  # front door, and leaving a terminal attached would make it wait for one.
  "$BIN" "${driver_args[@]+${driver_args[@]}}" </dev/null &
  driver_pid=$!
  while kill -0 "$driver_pid" 2>/dev/null; do
    # The compiler can finish between kill(0) and the RSS read. Do not let that ordinary
    # observation race trip `set -euo pipefail`: the wait below owns the child's
    # authoritative exit status.
    process_observe "$driver_pid"
    driver_rss="$PROCESS_RSS_KB"
    if [[ -n "$driver_rss" && "$driver_rss" -gt "$driver_peak" ]]; then
      driver_peak="$driver_rss"
    fi
    if [[ -n "$driver_rss" && "$driver_rss" -gt "$driver_max_rss_kb" ]]; then
      echo "stage1: memory guard stopped pid $driver_pid at ${driver_rss} KB (limit ${driver_max_rss_kb} KB; peak ${driver_peak} KB)" >&2
      terminate_guarded_pid "$driver_pid"
      return 125
    fi
    process_us_to_seconds "$driver_poll_us"
    process_sleep "$PROCESS_SECONDS"
    driver_poll_us=$(( driver_poll_us * 2 ))
    (( driver_poll_us > driver_poll_cap_us )) && driver_poll_us="$driver_poll_cap_us"
  done
  wait "$driver_pid" || driver_rc=$?
  return "$driver_rc"
}

# The toolchain the driver cannot discover for itself, and the root every path-relative
# default hangs off. Exported rather than passed as flags because the driver re-invokes
# ITSELF for the WASM runtime object and the auto-built pymodule runtime, and those
# children must resolve the same tools.
export ELISA_STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
export ELISA_STAGE1_SELF="${ELISA_STAGE1_SELF:-$BIN}"
export ELISA_LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$LLVM_BIN_DIR}"
[[ -x "$ELISA_CLANG_TOOL" ]] && export ELISA_CLANG="${ELISA_CLANG:-$ELISA_CLANG_TOOL}" || true
if (( ELISA_OMIT_RUNTIME )); then
  export ELISA_RUNTIME_OBJ=""
elif [[ -z "${ELISA_RUNTIME_OBJ:-}" ]]; then
  export ELISA_RUNTIME_OBJ="$ROOT/build/runtime/elisacore_runtime.o"
fi
resolve_python_tools
[[ -n "${PYTHON_HOST:-}" ]] && export PYTHON_BIN="${PYTHON_BIN:-$PYTHON_HOST}" || true
# PYTHON_CONFIG is exported ONLY when the caller named one. An implicit `python3-config`
# from PATH need not belong to the selected interpreter, and the driver refuses a
# mismatched pair by name — so handing it one we merely guessed at would turn a working
# build into an error. Absent it, the driver derives the headers from the interpreter.
[[ -n "${PYTHON_CONFIG:-}" ]] && export PYTHON_CONFIG || true

driver_args=("$@")

# Opt-in content-addressed object cache (ELISA_STAGE1_CACHE=1, directory
# ELISA_STAGE1_CACHE_DIR, default ~/.cache/elisac-stage1). Only a plain object compile
# (`-o OUT` with no `-emit` other than obj) is cached. The key covers everything the
# object is a function of: the product binary, the argument vector with OUT
# normalised, every ELISA_* variable, every file of the source's include graph
# (`-emit deps`), and the standard library tree the driver may pull in implicitly.
# A hit restores the object and replays both diagnostic streams; a miss compiles
# and stores the object plus diagnostics. The product provenance manifest is
# part of the key because it attests the exact LLVM toolchain artifacts; a
# reseed after an in-place LLVM update must not reuse objects from the old ABI.
# Products outside this tree and explicit stale-product runs skip the cache because
# assert_stage1_fresh.sh cannot attest their manifest.
# Integrity metadata is mandatory;
# legacy, partial, or corrupted entries take the ordinary compile path.
stage1_cache_key=""
stage1_cache_base_key=""
stage1_cache_dependency_identity=""
stage1_cache_dir=""
stage1_cache_out=""
stage1_cache_environment() {
  env | LC_ALL=C grep -E '^(ELISA_|ELISACORE_FORCE_CONTRACTS=)' | LC_ALL=C grep -v '^ELISA_STAGE1_CACHE' | LC_ALL=C sort
}
stage1_cache_prepare() {
  [[ "${ELISA_STAGE1_CACHE:-0}" == 1 ]] || return 1
  [[ "${ELISA_ALLOW_STALE_STAGE1:-0}" != 1 ]] || return 1
  [[ ! -L "$BIN" ]] || return 1
  local normalized_bin normalized_root
  normalized_bin="$(cd -- "$(dirname -- "$BIN")" 2>/dev/null && pwd -P)/$(basename -- "$BIN")" || return 1
  normalized_root="$(cd -- "$ROOT" 2>/dev/null && pwd -P)" || return 1
  case "$normalized_bin" in
    "$normalized_root/bin/"*) ;;
    *) return 1 ;;
  esac
  local index=0 count=${#driver_args[@]} arg emit="obj" source="" source_count=0 emit_count=0 output_count=0
  local provenance_file="${BIN}.provenance.json"
  local -a normalized=() auxiliary_inputs=() dependency_args=()
  while (( index < count )); do
    arg="${driver_args[index]}"
    case "$arg" in
      -o)
        (( output_count += 1 ))
        (( index + 1 < count )) || return 1
        stage1_cache_out="${driver_args[index + 1]:-}"
        [[ -n "$stage1_cache_out" ]] || return 1
        normalized+=("-o" "@OUT@")
        index=$((index + 2))
        continue
        ;;
      -fprofile-use)
        [[ -n "${driver_args[index + 1]:-}" ]] || return 1
        auxiliary_inputs+=("${driver_args[index + 1]}")
        normalized+=("$arg" "${driver_args[index + 1]}")
        index=$((index + 2))
        continue
        ;;
      -emit)
        (( emit_count += 1 ))
        (( index + 1 < count )) || return 1
        emit="${driver_args[index + 1]:-}"
        normalized+=("$arg" "$emit")
        index=$((index + 2))
        continue
        ;;
      *.elisa|*.elisai)
        source="$arg"
        (( source_count += 1 ))
        ;;
    esac
    normalized+=("$arg")
    index=$((index + 1))
  done
  [[ "$emit" == obj && "$emit_count" -le 1 && "$output_count" == 1 && "$source_count" == 1 && -n "$source" ]] || return 1
  [[ -f "$provenance_file" && -r "$provenance_file" ]] || return 1
  stage1_cache_dir="${ELISA_STAGE1_CACHE_DIR:-$HOME/.cache/elisac-stage1}"
  stage1_cache_base_key="$(
    {
      printf 'elisac-stage1-object-cache v6\n'
      printf 'cwd=%s\0' "$(pwd -P)" || exit 1
      shasum -a 256 "$BIN" "$provenance_file" | cut -d' ' -f1 || exit 1
      shasum -a 256 "$ROOT/scripts/elisac_stage1.sh" "$ROOT/scripts/stage1_object_cache.py" "$ROOT/scripts/platform.sh" | cut -d' ' -f1 || exit 1
      printf '%s\0' "${normalized[@]}"
      printf '\n'
      stage1_cache_environment || true
      if (( ${#auxiliary_inputs[@]} > 0 )); then
        shasum -a 256 "${auxiliary_inputs[@]}" || exit 1
      fi
      (cd "$ROOT" && find elisacore_std -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) || exit 1
    } | shasum -a 256 | cut -d' ' -f1
  )" || return 1
  [[ "$stage1_cache_base_key" =~ ^[0-9a-f]{64}$ ]] || return 1

  local dependency_index="$stage1_cache_dir/dependencies/$stage1_cache_base_key.json"
  local dependency_state="" dependency_graph="" dependency_identity=""
  dependency_state="$(python3 "$ROOT/scripts/stage1_object_cache.py" dependency-key "$dependency_index" "$stage1_cache_base_key" "$source" 2>/dev/null)" || dependency_state=""
  if [[ "$dependency_state" =~ ^([0-9a-f]{64})[[:space:]]([0-9a-f]{64})$ ]]; then
    dependency_graph="${BASH_REMATCH[1]}"
    dependency_identity="${BASH_REMATCH[2]}"
  else
    local deps_file snapshot_file verify_file emit_seen=0 deps_output_index=-1 dependency_arg_index
    deps_file="$(mktemp "${TMPDIR:-/tmp}/elisac-stage1-deps.XXXXXX")" || return 1
    snapshot_file="$(mktemp "${TMPDIR:-/tmp}/elisac-stage1-dependency-snapshot.XXXXXX")" || { rm -f "$deps_file"; return 1; }
    index=0
    while (( index < count )); do
      arg="${driver_args[index]}"
      case "$arg" in
        -o)
          dependency_args+=("-o" "$deps_file")
          index=$((index + 2))
          continue
          ;;
        -emit)
          dependency_args+=("-emit" "deps")
          emit_seen=1
          index=$((index + 2))
          continue
          ;;
      esac
      dependency_args+=("$arg")
      index=$((index + 1))
    done
    (( emit_seen )) || dependency_args+=("-emit" "deps")
    for ((dependency_arg_index = 0; dependency_arg_index + 1 < ${#dependency_args[@]}; dependency_arg_index++)); do
      if [[ "${dependency_args[dependency_arg_index]}" == "-o" ]]; then
        deps_output_index=$((dependency_arg_index + 1))
        break
      fi
    done
    if (( deps_output_index < 0 )); then
      rm -f "$deps_file" "$snapshot_file"
      return 1
    fi
    if ! "$BIN" "${dependency_args[@]}" </dev/null >/dev/null 2>&1; then
      rm -f "$deps_file" "$snapshot_file"
      return 1
    fi
    dependency_state="$(python3 "$ROOT/scripts/stage1_object_cache.py" dependency-store "$snapshot_file" "$stage1_cache_base_key" "$deps_file" "$source" 2>/dev/null)" || dependency_state=""
    if [[ ! "$dependency_state" =~ ^([0-9a-f]{64})[[:space:]]([0-9a-f]{64})$ || ! -s "$snapshot_file" ]]; then
      rm -f "$deps_file" "$snapshot_file"
      return 1
    fi
    verify_file="$(mktemp "${TMPDIR:-/tmp}/elisac-stage1-deps-verify.XXXXXX")" || { rm -f "$deps_file" "$snapshot_file"; return 1; }
    dependency_args[deps_output_index]="$verify_file"
    if ! "$BIN" "${dependency_args[@]}" </dev/null >/dev/null 2>&1; then
      rm -f "$deps_file" "$snapshot_file" "$verify_file"
      return 1
    fi
    dependency_state="$(python3 "$ROOT/scripts/stage1_object_cache.py" dependency-confirm "$snapshot_file" "$dependency_index" "$stage1_cache_base_key" "$verify_file" "$source" 2>/dev/null)" || dependency_state=""
    rm -f "$deps_file" "$snapshot_file" "$verify_file"
    if [[ "$dependency_state" =~ ^([0-9a-f]{64})[[:space:]]([0-9a-f]{64})$ ]]; then
      dependency_graph="${BASH_REMATCH[1]}"
      dependency_identity="${BASH_REMATCH[2]}"
    fi
  fi
  [[ "$dependency_graph" =~ ^[0-9a-f]{64}$ && "$dependency_identity" =~ ^[0-9a-f]{64}$ ]] || return 1
  stage1_cache_dependency_identity="$dependency_identity"
  stage1_cache_key="$(printf '%s\0%s\0%s' 'elisac-stage1-object-cache-key-v6' "$stage1_cache_base_key" "$dependency_graph" | shasum -a 256 | cut -d' ' -f1)" || return 1
  [[ -n "$stage1_cache_key" ]]
}
stage1_cache_publish_if_unchanged() {
  local compiled_key="$stage1_cache_key" compiled_identity="$stage1_cache_dependency_identity"
  # A successful compile can overlap an editor save or dependency regeneration.
  # Keep its output, but publish only under the exact inputs observed at admission.
  stage1_cache_prepare || return 0
  [[ "$stage1_cache_key" == "$compiled_key" && "$stage1_cache_dependency_identity" == "$compiled_identity" ]] || return 0
  # A cache-hit recheck may discover changed inputs and send the wrapper through
  # compilation under a new key. Publish to that key's path, not the earlier hit.
  stage1_cache_entry="$stage1_cache_dir/$stage1_cache_key.o"
  python3 "$ROOT/scripts/stage1_object_cache.py" publish "$stage1_cache_entry" "$stage1_cache_out" "$stage1_cache_key" "$stage1_cache_logs/stdout" "$stage1_cache_logs/stderr" || true
}
stage1_cache_restore_if_unchanged() {
  local admitted_key="$stage1_cache_key"
  local admitted_identity="$stage1_cache_dependency_identity"
  local restore_template="$stage1_cache_out.cache.XXXXXX"
  local staged_object staged_stdout staged_stderr restore_rc=0 destination="$stage1_cache_out"
  # Keep the staged object beside the requested output so the final rename is atomic.
  # Prefix relative paths so an output beginning with '-' is not parsed as an option.
  case "$restore_template" in /*|./*|../*) ;; *) restore_template="./$restore_template" ;; esac
  case "$destination" in /*|./*|../*) ;; *) destination="./$destination" ;; esac
  staged_object="$(mktemp "$restore_template" 2>/dev/null)" || return 1
  staged_stdout="${staged_object}.stdout"
  staged_stderr="${staged_object}.stderr"
  python3 "$ROOT/scripts/stage1_object_cache.py" restore "$stage1_cache_entry" "$staged_object" "$admitted_key" >"$staged_stdout" 2>"$staged_stderr" || restore_rc=$?
  if [[ "$restore_rc" -ne 0 ]]; then
    rm -f "$staged_object" "$staged_stdout" "$staged_stderr"
    return "$restore_rc"
  fi
  if ! stage1_cache_prepare || [[ "$stage1_cache_key" != "$admitted_key" || "$stage1_cache_dependency_identity" != "$admitted_identity" ]]; then
    rm -f "$staged_object" "$staged_stdout" "$staged_stderr"
    return 1
  fi
  if ! mv -f "$staged_object" "$destination"; then
    rm -f "$staged_object" "$staged_stdout" "$staged_stderr"
    return 1
  fi
  cat "$staged_stderr" >&2
  cat "$staged_stdout"
  rm -f "$staged_stdout" "$staged_stderr"
  return 0
}
if stage1_cache_prepare; then
  stage1_cache_dir="${ELISA_STAGE1_CACHE_DIR:-$HOME/.cache/elisac-stage1}"
  stage1_cache_entry="$stage1_cache_dir/$stage1_cache_key.o"
  stage1_cache_restore_rc=0
  stage1_cache_restore_if_unchanged || stage1_cache_restore_rc=$?
  [[ "$stage1_cache_restore_rc" == 0 ]] && exit 0
  [[ "$stage1_cache_restore_rc" == 1 ]] || exit "$stage1_cache_restore_rc"
  stage1_cache_logs="$(mktemp -d "${TMPDIR:-/tmp}/elisac-stage1-cache-logs.XXXXXX")"
  trap 'rm -rf "$stage1_cache_logs"' EXIT
  stage1_cache_rc=0
  run_stage1_driver_guarded >"$stage1_cache_logs/stdout" 2>"$stage1_cache_logs/stderr" || stage1_cache_rc=$?
  cat "$stage1_cache_logs/stderr" >&2
  cat "$stage1_cache_logs/stdout"
  if [[ "$stage1_cache_rc" -eq 0 && -f "$stage1_cache_out" ]]; then
    stage1_cache_publish_if_unchanged
  fi
  exit "$stage1_cache_rc"
fi

run_stage1_driver_guarded
exit $?
