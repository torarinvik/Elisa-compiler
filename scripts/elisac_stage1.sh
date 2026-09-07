#!/usr/bin/env bash
# Host-facing CLI for the stage1 product compiler.
#
# Usage:
#   elisac_stage1.sh -o out.o source.elisa
#   elisac_stage1.sh -emit wasm -o demo.wasm source.elisa  # compatibility module plus sidecars
#   elisac_stage1.sh -emit wasm --wasm-only --component-type app.wit -o app.wasm source.elisa
#   elisac_stage1.sh --seed          # one-time seed build using stage0 (optional)
#   elisac_stage1.sh --emit-driver   # only build the product binary (needs seed elisac)
#
# Include expansion is a host packaging step (matches stage0's readSourceWithIncludes).
# The compiler binary itself is pure stage1 frontend+backend.
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
# Default to the canonical Elisa-core checkout every parity smoke and the drift guard
# also assume (`../../Go projects/structpy-tree`). The old `../stage0/.../elisac-local`
# default named a worktree that no longer exists, so a bare `--seed` failed with
# "seed requires stage0 elisac" until ELISACORE_BIN was exported by hand. Callers can
# still select an explicit compiler with ELISACORE_BIN.
STAGE0_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
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

out=""
src=""
noalias=0
bounds_check=0
debug_info=0
trace_info=0
opt_level=0
test_filter=""
emit_mode="obj"
target_triple=""
wasm_ld=""
link_flags=()
component_types=()
wasm_component_ld=""
wasm_only=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="${2:-}"; shift 2 ;;
    --python-config)
      PYTHON_CONFIG="${2:-}"; shift 2 ;;
    -o)
      out="${2:-}"; shift 2 ;;
    -emit)
      # `obj` (default) lowers to a native object; `llvm` prints the SAME module as
      # textual IR — the debugging surface this repo kept borrowing from stage0; `exe`
      # links the object against the runtime into a runnable binary (host clang does the
      # link — linking is host tooling, and every harness in this repo already links this
      # exact way by hand).
      case "${2:-}" in
        obj)    emit_mode="obj" ;;
        llvm)   emit_mode="llvm" ;;
        bc)     emit_mode="bc" ;;
        exe)    emit_mode="exe" ;;
        wasm)   emit_mode="wasm" ;;
        tokens) emit_mode="tokens" ;;
        ast)    emit_mode="ast" ;;
        iface)  emit_mode="iface" ;;
        fmt)    emit_mode="fmt" ;;
        doc)    emit_mode="doc" ;;
        header) emit_mode="header" ;;
        pymodule) emit_mode="pymodule" ;;
        pymodule-c) emit_mode="pymodule-c" ;;
        pymodule-pyi) emit_mode="pymodule-pyi" ;;
        pymodule-so) emit_mode="pymodule-so" ;;
        test-runner) emit_mode="test-runner" ;;
        # stage0 refuses `-o` for these three and prints the listing on stdout; the
        # wrapper mirrors that rather than inventing a file-writing form.
        tests) emit_mode="tests" ;;
        benches) emit_mode="benches" ;;
        fixtures) emit_mode="fixtures" ;;
        # `-emit test` runs the suite; like the listings, stage0 refuses `-o` for it.
        test) emit_mode="test" ;;
        c-bind-check) emit_mode="c-bind-check" ;;
        c-bind-check-json) emit_mode="c-bind-check-json" ;;
        packed) emit_mode="packed" ;;
        unsafe) emit_mode="unsafe" ;;
        c-archive) emit_mode="c-archive" ;;
        lowered) emit_mode="lowered" ;;
        progress) emit_mode="progress" ;;
        # `-emit ir` writes the .elisair frontend-IR bundle (binary; the driver writes it
        # through the -o path like every other emit mode).
        ir|frontend-ir|bundle) emit_mode="ir" ;;
        interpret) emit_mode="interpret" ;;
        deps)      emit_mode="deps" ;;
        deps-json) emit_mode="deps-json" ;;
        *) echo "only -emit obj, -emit llvm, -emit bc, -emit exe, -emit wasm, -emit tokens, -emit ast, -emit iface, -emit fmt, -emit doc, -emit header, -emit pymodule, -emit pymodule-c, -emit pymodule-pyi, -emit pymodule-so, -emit test-runner, -emit tests, -emit benches, -emit fixtures, -emit test, -emit c-bind-check, -emit c-bind-check-json, -emit packed, -emit unsafe, -emit c-archive, -emit lowered, -emit progress, -emit ir, -emit interpret, -emit deps and -emit deps-json are supported" >&2; exit 2 ;;
      esac
      shift 2 ;;
    -filter)
      test_filter="${2:-}"; shift 2 ;;
    -fnoalias)
      noalias=1; shift ;;
    -fbounds-check)
      bounds_check=1; shift ;;
    -g|-debug-info)
      debug_info=1; shift ;;
    -ftrace|-record-trace)
      trace_info=1; shift ;;
    # Cross-compilation and linker passthrough. The DRIVER has implemented both for a
    # while (requested_target_triple, and ELISA_STAGE1_LINK read in the c-archive/exe
    # paths) — only this wrapper rejected them, so `-target-triple` and `-link/-L/-l`
    # looked like compiler gaps when they were three missing cases in an argument loop.
    -target-triple)
      target_triple="${2:-}"; shift 2 ;;
    --wasm-ld)
      wasm_ld="${2:-}"; shift 2 ;;
    --wasm-component-ld)
      wasm_component_ld="${2:-}"; shift 2 ;;
    --component-type|--wit)
      component_types+=("${2:-}"); shift 2 ;;
    --wasm-only)
      wasm_only=1; shift ;;
    -link)
      link_flags+=("${2:-}"); shift 2 ;;
    -L)
      link_flags+=("-L${2:-}"); shift 2 ;;
    -l)
      link_flags+=("-l${2:-}"); shift 2 ;;
    -O0|-permissive) shift ;;
    # -O1/-O2/-O3 now run LLVM's `default<O{n}>` pass pipeline in the driver
    # (ELISA_STAGE1_OPT). The pipeline was disabled while `default<O2>` trapped on
    # large self-host modules; those traps were the opaque-handle `==` and
    # arena-identity miscompiles in the self-hosted binary, fixed 2026-08-02/03.
    # -Os/-Oz remain unsupported: stage0 has no size-pipeline parity to hold them to.
    -O1) opt_level=1; shift ;;
    -O2) opt_level=2; shift ;;
    -O3) opt_level=3; shift ;;
    -Os|-Oz)
      echo "$1: unsupported (no size-optimisation parity with stage0); use -O0..-O3" >&2
      exit 2 ;;
    -*)
      echo "unknown flag: $1" >&2; exit 2 ;;
    *)
      src="$1"; shift ;;
  esac
done
resolve_python_tools
if [[ "$emit_mode" == "pymodule-so" ]]; then
  validate_python_toolchain
fi
# Recursive emit steps re-enter this same wrapper. Export the resolved absolute paths so
# one-off CLI overrides remain in force for those child invocations instead of falling back to
# the host's default python3/python3-config.
if [[ -n "$PYTHON_HOST" ]]; then
  export PYTHON_BIN="$PYTHON_HOST"
fi
if [[ -n "$PYTHON_CONFIG_HOST" ]]; then
  export PYTHON_CONFIG="$PYTHON_CONFIG_HOST"
fi

# `-emit wasm` is the driver's (§4.4): it emits the wasm32 object, builds the portable
# runtime object, links with wasm-ld and writes the manifest and the JS/TS facade itself.
# The packaging options travel by environment like every other option.
if [[ "$emit_mode" == "wasm" ]]; then
  [[ -n "$src" ]] || { echo "usage: $0 -emit wasm -o out.wasm source.elisa" >&2; exit 2; }
  if [[ -z "$out" ]]; then
    out="${src%.*}.wasm"
  elif [[ "$out" != *.wasm ]]; then
    out="${out}.wasm"
  fi
  [[ -z "$target_triple" ]] && target_triple="wasm32-unknown-unknown"
  joined_component_types=""
  if [[ "${#component_types[@]}" -gt 0 ]]; then
    for component_type in "${component_types[@]}"; do
      absolute_component_type="$(cd -- "$(dirname -- "$component_type")" && pwd)/$(basename -- "$component_type")"
      joined_component_types="${joined_component_types:+$joined_component_types;}$absolute_component_type"
    done
  fi
fi

# `-emit tests|benches|fixtures` list annotated functions on STDOUT and stage0 rejects
# `-o` for them, so they are the one shape that needs no output path.
case "$emit_mode" in
  tests|benches|fixtures|test)
    if [[ -n "$out" ]]; then
      echo "error: -o is not supported for -emit $emit_mode" >&2; exit 1
    fi
    out=/dev/null ;;
  interpret)
    # stage0 refuses `-o` here too, but callers (including this repo's own gate) pass
    # `-o /dev/null` to satisfy the wrapper's usual requirement. Accept either, and
    # default the path so a bare `-emit interpret` behaves like stage0's rather than
    # failing with a usage error — which read as exit 2 where stage0 answers 1.
    out="${out:-/dev/null}" ;;
esac
[[ -n "$src" ]] || { echo "usage: $0 [-o out.o] source.elisa" >&2; exit 2; }
if [[ "$emit_mode" != "pymodule-so" && "$emit_mode" != "pymodule-pyi" && -z "$out" ]]; then
  echo "usage: $0 -o out.o source.elisa" >&2
  exit 2
fi
[[ -f "$src" ]] || { echo "missing source: $src" >&2; exit 2; }
# Python is needed only by the pymodule-so and wasm pipelines below, each of which checks
# for it itself; include expansion is the driver's (§4.1), so an ordinary compile needs none.
# Keep all Python-facing emitters consistent: explicit manifest, generated C, stub, and
# complete-extension paths may point into a directory that does not exist yet.
case "$emit_mode" in
  pymodule|pymodule-c)
    [[ -z "$out" ]] || mkdir -p "$(dirname -- "$out")" ;;
esac

stage1_request="$(mktemp)"
trap 'rm -f "$stage1_request"' EXIT
# `-emit deps` / `-emit deps-json` are handled by the DRIVER (emit_deps_report in
# elisac.elisa), like every other emit mode. They used to be computed here in ~30 lines of
# Python that re-walked the include graph — a second implementation of dependency discovery,
# in a second language, shadowing a correct one: the driver produced stage0's exact bytes and
# never got to run. Verified identical to stage0 for both formats over a nested include chain
# before this was deleted.

# `-emit exe`: the DRIVER emits the object beside the executable and links it (§4.3:
# link_executable — runtime object, weak callback fallback, -link flags, dead-strip). The
# wrapper only checks the runtime object exists, so the failure names the fix rather than
# surfacing as an undefined `_arena_free` from the host linker.
runtime_obj="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
if [[ "$emit_mode" == "exe" ]]; then
  [[ -f "$runtime_obj" ]] || { echo "-emit exe requires the runtime object at $runtime_obj (run scripts/build_runtime_object.sh)" >&2; exit 2; }
fi

# `-emit pymodule-so` and `-emit pymodule-pyi` are the DRIVER's (§4.5): it emits the
# manifest, the C shim and the object in-process, spawns the target interpreter for the three
# facts only that interpreter can answer (EXT_SUFFIX, the suffixes its import machinery
# recognises, and its header directory), and runs clang itself. The wrapper's remaining job
# is to hand over the toolchain paths it already resolved.

# Run the self-hosted compiler as a direct child so its RSS can be observed. The previous
# stdin pipeline made it possible for a large compile to escape every wrapper-level guard:
# the shell only waited on the pipeline while the compiler itself grew into swap. The limit
# is deliberately conservative for ordinary development; a dedicated build host can raise
# ELISA_STAGE1_MAX_RSS_KB explicitly.
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
  env "${driver_env[@]+${driver_env[@]}}" "$BIN" "${driver_args[@]+${driver_args[@]}}" <"$stage1_request" &
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


# Optimisation level and emit mode reach the driver via env (the stdin protocol
# carries only the output path and the source).
driver_env=()
# Diagnostics name the source file (stage0's `PATH:LINE: message`). The wrapper is the only
# side that knows the ORIGINAL path once includes are flattened, so pass it for EVERY mode,
# not just the report modes below — otherwise a wrapper-compiled program reports a bare
# line number while the same file compiled through the CLI names itself.
driver_env+=("ELISA_STAGE1_SRC=$src")
[[ "$debug_info" == 1 ]] && driver_env+=("ELISA_STAGE1_DEBUG=1")
[[ "$trace_info" == 1 ]] && driver_env+=("ELISA_STAGE1_TRACE=1")
[[ -n "$target_triple" ]] && driver_env+=("ELISA_STAGE1_TRIPLE=$target_triple")
[[ "$target_triple" == wasm* ]] && driver_env+=("ELISA_STAGE1_WASM=1")
[[ ${#link_flags[@]} -gt 0 ]] && driver_env+=("ELISA_STAGE1_LINK=${link_flags[*]}")
[[ "$opt_level" != 0 ]] && driver_env+=("ELISA_STAGE1_OPT=$opt_level")
[[ "$emit_mode" == "llvm" ]] && driver_env+=("ELISA_STAGE1_EMIT=llvm")
[[ "$emit_mode" == "bc" ]] && driver_env+=("ELISA_STAGE1_EMIT=bc")
if [[ "$emit_mode" == "wasm" ]]; then
  driver_env+=("ELISA_STAGE1_EMIT=wasm" "ELISA_STAGE1_ROOT=$ROOT" "ELISA_STAGE1_SELF=$0")
  [[ -n "$wasm_ld" ]] && driver_env+=("ELISA_STAGE1_WASM_LD=$wasm_ld")
  [[ -n "$wasm_component_ld" ]] && driver_env+=("ELISA_STAGE1_WASM_COMPONENT_LD=$wasm_component_ld")
  [[ "$wasm_only" == 1 ]] && driver_env+=("ELISA_STAGE1_WASM_ONLY=1")
  [[ -n "$joined_component_types" ]] && driver_env+=("ELISA_STAGE1_WASM_COMPONENT_TYPES=$joined_component_types")
fi
if [[ "$emit_mode" == "pymodule-so" || "$emit_mode" == "pymodule-pyi" ]]; then
  # ELISA_STAGE1_SELF is how the driver re-invokes itself to auto-build a missing runtime
  # object; without it the child would be `bin/elisac-stage1` relative to the CWD.
  driver_env+=("ELISA_STAGE1_EMIT=$emit_mode" "ELISA_STAGE1_ROOT=$ROOT" "ELISA_RUNTIME_OBJ=$runtime_obj")
  driver_env+=("ELISA_STAGE1_SELF=$BIN")
  driver_env+=("ELISA_LLVM_BIN_DIR=$LLVM_BIN_DIR")
  [[ -x "$ELISA_CLANG_TOOL" ]] && driver_env+=("ELISA_CLANG=$ELISA_CLANG_TOOL")
  # `-o` reaches the driver through the environment for these two: absent, it names the
  # output after the MODULE, which no path default can express.
  driver_env+=("ELISA_STAGE1_PYMODULE_OUT=$out")
  out=""
fi
if [[ "$emit_mode" == "exe" ]]; then
  driver_env+=("ELISA_STAGE1_EMIT=exe" "ELISA_RUNTIME_OBJ=$runtime_obj")
  [[ -x "$ELISA_CLANG_TOOL" ]] && driver_env+=("ELISA_CLANG=$ELISA_CLANG_TOOL")
fi
# `-emit c-archive` writes its OWN files (the archive and three sidecars), so it needs the
# mode and the source path but must NOT have stdout redirected like a text report.
if [[ "$emit_mode" == "interpret" ]]; then
  # Runs the program; its stdout IS the report, so no -o redirection.
  driver_env+=("ELISA_STAGE1_EMIT=interpret" "ELISA_STAGE1_SRC=$src")
  [[ -f "$runtime_obj" ]] && driver_env+=("ELISA_RUNTIME_OBJ=$runtime_obj")
fi
if [[ "$emit_mode" == "c-archive" ]]; then
  driver_env+=("ELISA_STAGE1_EMIT=c-archive" "ELISA_STAGE1_SRC=$src")
  # Set AFTER driver_env is initialised — an earlier placement was silently wiped by the
  # `driver_env=()` below it, so the archive shipped without the runtime object.
  [[ -f "$runtime_obj" ]] && driver_env+=("ELISA_RUNTIME_OBJ=$runtime_obj")
fi
# `-emit tests|benches|fixtures` also print on STDOUT, but stage0 refuses `-o` for them,
# so unlike the text reports below they are NOT redirected — the listing IS the stdout.
if [[ "$emit_mode" == "tests" || "$emit_mode" == "benches" || "$emit_mode" == "fixtures" || "$emit_mode" == "test" ]]; then
  driver_env+=("ELISA_STAGE1_EMIT=$emit_mode" "ELISA_STAGE1_SRC=$src")
  [[ -n "$test_filter" ]] && driver_env+=("ELISA_STAGE1_FILTER=$test_filter")
  # `-emit test` LINKS and RUNS, so it needs the runtime object the same way -emit exe
  # and -emit interpret do.
  [[ "$emit_mode" == "test" && -f "$runtime_obj" ]] && driver_env+=("ELISA_RUNTIME_OBJ=$runtime_obj")
fi
# `-emit tokens` prints the report on STDOUT (stage0's shape); redirect it to -o. The
# report names the ORIGINAL source path, which only the wrapper knows.
if [[ "$emit_mode" == "tokens" || "$emit_mode" == "ast" || "$emit_mode" == "iface" || "$emit_mode" == "fmt" || "$emit_mode" == "doc" || "$emit_mode" == "header" || "$emit_mode" == "pymodule" || "$emit_mode" == "pymodule-c" || "$emit_mode" == "test-runner" || "$emit_mode" == "c-bind-check" || "$emit_mode" == "c-bind-check-json" || "$emit_mode" == "packed" || "$emit_mode" == "unsafe" || "$emit_mode" == "lowered" || "$emit_mode" == "progress" || "$emit_mode" == "deps" || "$emit_mode" == "deps-json" || "$emit_mode" == "ir" ]]; then
  # `-emit fmt` additionally needs the OFFSET MAP (the driver publishes it): stage0 names
  # its synthesized auto-regions `__auto_<pos.Offset>` with offsets measured over its
  # directive-bearing expansion. ELISA_STAGE1_SRC stays as given — the tokens report
  # prints it verbatim and is byte-parity held.
  driver_env+=("ELISA_STAGE1_EMIT=$emit_mode" "ELISA_STAGE1_SRC=$src")
  [[ -n "$test_filter" ]] && driver_env+=("ELISA_STAGE1_FILTER=$test_filter")
  exec > "$out"
fi
# The driver's CLI door: `-o OUT SRC` with the mode and every other option already in the
# environment (cli_request leaves ELISA_STAGE1_EMIT alone unless `-emit` is given). The driver
# expands the includes itself. The stdin request stays as an empty file only because the
# guarded runner redirects from it.
# The listing/run modes — the ones stage0 refuses `-o` for, which the case above defaulted to
# /dev/null — must get NO `-o` here: on the CLI door an output path routes a report INTO that
# file (that is how the redirected report modes work), and `-o /dev/null` routed the whole
# `-emit tests|benches|fixtures|test` listing into the void (emit_annotated_list and
# emit_test_run parity, 2026-09-06). Without `-o` the listing is stdout, as it always was.
if [[ "$out" == /dev/null || -z "$out" ]]; then
  driver_args=("$src")
else
  driver_args=(-o "$out" "$src")
fi
: >"$stage1_request"
if [[ "$noalias" == 1 && "$bounds_check" == 1 ]]; then
  driver_env+=("ELISACORE_NOALIAS_MUTABLE_REFS=1" "ELISACORE_FORCE_BOUNDS_CHECK=1")
elif [[ "$noalias" == 1 ]]; then
  driver_env+=("ELISACORE_NOALIAS_MUTABLE_REFS=1")
elif [[ "$bounds_check" == 1 ]]; then
  driver_env+=("ELISACORE_FORCE_BOUNDS_CHECK=1")
fi
run_stage1_driver_guarded
compile_rc=$?
exit "$compile_rc"

