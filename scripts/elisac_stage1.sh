#!/usr/bin/env bash
# Host-facing entry point for the stage1 product compiler.
#
# Since §4.6 this parses NOTHING. `bin/elisac-stage1` is the compiler's only front door:
# every flag, every emit mode, include expansion, linking, the WASM packaging and the
# Python extension pipeline are its own. What is left here is the two jobs that are
# genuinely the host's:
#
#   * the SEED build (`--seed` / `--emit-driver`), which needs stage0, and the refusal to
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
#   elisac_stage1.sh --seed          # one-time seed build using stage0
#   elisac_stage1.sh --emit-driver   # only build the product binary (needs seed elisac)
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
# Keep the host linker in the same LLVM installation as the C API library used to
# build the stage1 product. Apple clang can link ordinary objects, but it may not
# parse textual IR printed by a newer Homebrew LLVM (for example, LLVM 22 emits
# attributes Apple clang 21 does not understand).
LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$(dirname -- "$LLVM_CONFIG")}"
ELISA_CLANG_TOOL="${ELISA_CLANG:-$LLVM_BIN_DIR/clang}"
if [[ ! -x "$ELISA_CLANG_TOOL" ]]; then
  ELISA_CLANG_TOOL="$(command -v clang || true)"
fi
# Prefer the canonical Elisa-core checkout in both a top-level compiler checkout
# and a nested profiler worktree. The old `../stage0/.../elisac-local` default
# named a worktree that no longer exists, while a single fixed `../../` depth is
# wrong for `elisa-compiler-worktrees/profiler`. Callers can still select an
# explicit compiler with ELISACORE_BIN.
if [[ -n "${ELISACORE_BIN:-}" ]]; then
  STAGE0_BIN="$ELISACORE_BIN"
else
  STAGE0_BIN=""
  for stage0_candidate in \
      "$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac" \
      "$ROOT/../../../Go projects/structpy-tree/compiler/bin/elisac"; do
    if [[ -x "$stage0_candidate" ]]; then
      STAGE0_BIN="$stage0_candidate"
      break
    fi
  done
  STAGE0_BIN="${STAGE0_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
fi
# Host predicates for the product's `static if ELISA_TARGET_OS_*` / `PLATFORM_*` consts and
# the project system's platform key (see register_target_consts / host_platform_name). stage0
# reads runtime.GOOS; the self-hosted compiler reads these flags, exported once here.
if [[ "$(uname -s)" == "Linux" ]]; then export ELISA_HOST_LINUX=1; fi
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

source "$ROOT/scripts/elisac_stage1_seed.sh"

if [[ "${1:-}" == "--seed" ]]; then
  seed_build
  exit 0
fi

if [[ ! -x "$BIN" ]]; then
  echo "stage1 product binary missing: $BIN (run: $0 --seed once)" >&2
  exit 2
fi

# A product binary generated from older compiler sources is not a compatible cache.
# In particular, parser/lowering changes can make the stale product misread a newer
# flattened driver and grow without bound instead of producing a useful diagnostic.
# Refuse that state up front: it turns a multi-gigabyte OS kill into a deterministic,
# actionable error. The escape hatch is intentionally explicit for compiler archaeology.
stale_stage1_source="$(find "$ROOT/src" "$ROOT/elisacore_std" -type f \( -name '*.elisa' -o -name '*.elisai' \) -newer "$BIN" -print -quit)"
if [[ -n "$stale_stage1_source" && "${ELISA_ALLOW_STALE_STAGE1:-0}" != 1 ]]; then
  echo "stage1 product binary is stale: $stale_stage1_source is newer than $BIN" >&2
  echo "run: $0 --seed" >&2
  echo "set ELISA_ALLOW_STALE_STAGE1=1 only when intentionally testing an older product" >&2
  exit 2
fi

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
  local driver_poll_now=0.002
  # stdin is closed rather than fed: the stdin wire protocol is still the driver's other
  # front door, and leaving a terminal attached would make it wait for one.
  "$BIN" "${driver_args[@]+${driver_args[@]}}" </dev/null &
  driver_pid=$!
  while kill -0 "$driver_pid" 2>/dev/null; do
    # The compiler can finish between kill(0) and ps(1). Do not let that ordinary
    # observation race trip `set -euo pipefail`: the wait below owns the child's
    # authoritative exit status.
    driver_rss="$(ps -o rss= -p "$driver_pid" 2>/dev/null | awk '{print $1}')" || driver_rss=""
    if [[ -n "$driver_rss" && "$driver_rss" -gt "$driver_peak" ]]; then
      driver_peak="$driver_rss"
    fi
    if [[ -n "$driver_rss" && "$driver_rss" -gt "$driver_max_rss_kb" ]]; then
      echo "stage1: memory guard stopped pid $driver_pid at ${driver_rss} KB (limit ${driver_max_rss_kb} KB; peak ${driver_peak} KB)" >&2
      terminate_guarded_pid "$driver_pid"
      return 125
    fi
    sleep "$driver_poll_now"
    driver_poll_now="$(awk -v now="$driver_poll_now" -v cap="$driver_rss_poll_seconds" 'BEGIN { doubled = now * 2; print (doubled > cap) ? cap : doubled }')"
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
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
resolve_python_tools
[[ -n "${PYTHON_HOST:-}" ]] && export PYTHON_BIN="${PYTHON_BIN:-$PYTHON_HOST}" || true
# PYTHON_CONFIG is exported ONLY when the caller named one. An implicit `python3-config`
# from PATH need not belong to the selected interpreter, and the driver refuses a
# mismatched pair by name — so handing it one we merely guessed at would turn a working
# build into an error. Absent it, the driver derives the headers from the interpreter.
[[ -n "${PYTHON_CONFIG:-}" ]] && export PYTHON_CONFIG || true

driver_args=("$@")
run_stage1_driver_guarded
exit $?
