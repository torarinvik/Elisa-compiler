#!/usr/bin/env bash
# Host-facing CLI for the stage1 product compiler.
#
# Usage:
#   elisac_stage1.sh -o out.o source.elisa
#   elisac_stage1.sh -emit wasm -o demo.wasm source.elisa  # also writes ESM/types/manifest sidecars
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
# Never silently seed stage1 with the installed compiler. Callers can pin a
# particular local stage0 with ELISACORE_BIN; otherwise use the compiler/bin
# artifact in the selected ELISA_CORE source tree.
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}"
STAGE0_BIN="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
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

flatten_includes() {
  # Writes the flattened source to stdout. When $2 is given, also writes an OFFSET MAP
  # there: stage0 expands includes into a buffer with `#line <n> <abs path>` directives
  # spliced in (writeSourceWithIncludesWithOptionsActive), and its synthesized auto-region
  # names are `__auto_<offset in THAT buffer>`. The map records, at each flat-buffer
  # offset where the two buffers diverge, the byte DELTA (stage0 offset - flat offset), as
  # ascending `flatoff:delta` pairs — the driver's fmt adds the covering delta to a token
  # offset to recover stage0's number. Indented include directives (stage0 re-indents the
  # spliced lines) are not modeled; this repo's includes are all at column 0.
  "$PYTHON_HOST" - "$1" "${2:-}" <<'PY'
import re, pathlib, sys
path = pathlib.Path(sys.argv[1]).resolve()
map_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
include_re = re.compile(r'^[ \t]*(?:#\s*)?include[ \t]+"([^"]+)"[ \t]*$')
seen = set()
entries: list[tuple[int, int]] = []
pos = {"flat": 0, "s0": 0}

def directive_len(line_num: int, abs_path: str) -> int:
    # "#line %d %s\n"
    return 6 + len(str(line_num)) + 1 + len(abs_path) + 1

def mark() -> None:
    delta = pos["s0"] - pos["flat"]
    if entries and entries[-1][0] == pos["flat"]:
        entries[-1] = (pos["flat"], delta)
    else:
        entries.append((pos["flat"], delta))

def flatten(p: pathlib.Path, out: list[str], stack: list[pathlib.Path]) -> None:
    ap = p.resolve()
    if ap in seen:
        return
    if ap in stack:
        raise SystemExit(f"cyclic include: {ap}")
    seen.add(ap)
    stack.append(ap)
    text = p.read_text(encoding="utf-8")
    base = p.parent
    pos["s0"] += directive_len(1, str(ap))
    mark()
    cur_line = 1
    for line in text.splitlines(keepends=True):
        m = include_re.match(line.rstrip("\n"))
        if m:
            rel = m.group(1)
            inc = pathlib.Path(rel) if pathlib.Path(rel).is_absolute() else (base / rel)
            if not inc.exists():
                raise SystemExit(f"missing include {rel!r} from {p}")
            s0_before = pos["s0"]
            flatten(inc, out, stack)
            # stage0's newline guard: the spliced content must end with '\n'.
            if pos["s0"] == s0_before or (out and not out[-1].endswith("\n")):
                pos["s0"] += 1
            pos["s0"] += directive_len(cur_line + 1, str(ap))
            mark()
        else:
            out.append(line)
            pos["flat"] += len(line)
            pos["s0"] += len(line)
        cur_line += 1
    stack.pop()

out: list[str] = []
flatten(path, out, [])
sys.stdout.write("".join(out))
if map_path:
    with open(map_path, "w") as f:
        f.write(",".join(f"{o}:{d}" for o, d in entries))
PY
}

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

seed_build() {
  local libdir seed_lock seed_lock_pid global_seed_lock global_seed_lock_pid seed_max_rss_kb seed_rss_poll_seconds seed_opt_level seed_output seed_object
  # The EXIT trap runs after this function's locals have gone out of scope under
  # `set -u`; retain the private lock path in a function-external variable so a
  # successful high-memory seed always releases its lock without an unbound-var exit.
  # Create the lock's parent before taking the lock. A fresh checkout has no build/
  # directory yet; treating a failed mkdir as a stale lock there makes the very first
  # seed fail before it can create its own build outputs.
  mkdir -p "$ROOT/build"
  ELISA_SEED_LOCK_DIR="$ROOT/build/.elisac-stage1-seed.lock"
  seed_lock="$ELISA_SEED_LOCK_DIR"
  if ! mkdir "$seed_lock" 2>/dev/null; then
    seed_lock_pid=""
    if [[ -f "$seed_lock/pid" ]]; then
      seed_lock_pid="$(<"$seed_lock/pid")"
    fi
    if [[ -n "$seed_lock_pid" ]] && kill -0 "$seed_lock_pid" 2>/dev/null; then
      echo "seed: another stage1 seed is already running (pid $seed_lock_pid); refusing a concurrent high-memory build" >&2
      exit 2
    fi
    # A killed shell may leave only its lock directory behind. Reclaim it only when
    # the recorded owner is no longer alive; the target is this private lock directory.
    rm -f "$seed_lock/pid"
    rmdir "$seed_lock" 2>/dev/null || {
      echo "seed: could not acquire stale lock $seed_lock" >&2
      exit 2
    }
    mkdir "$seed_lock" || {
      echo "seed: could not acquire lock $seed_lock" >&2
      exit 2
    }
  fi
  # Worktrees have distinct local locks, but a stage0 seed is a host-wide high-memory
  # operation. Serialize all Elisa self-host seeds on this machine so independent Codex
  # worktrees cannot reproduce the multi-gigabyte contention that previously froze the host.
  ELISA_SEED_GLOBAL_LOCK_DIR="${ELISA_STAGE1_GLOBAL_SEED_LOCK_DIR:-${TMPDIR:-/tmp}/elisac-stage1-global-seed.lock}"
  global_seed_lock="$ELISA_SEED_GLOBAL_LOCK_DIR"
  if ! mkdir "$global_seed_lock" 2>/dev/null; then
    global_seed_lock_pid=""
    if [[ -f "$global_seed_lock/pid" ]]; then
      global_seed_lock_pid="$(<"$global_seed_lock/pid")"
    fi
    if [[ -n "$global_seed_lock_pid" ]] && kill -0 "$global_seed_lock_pid" 2>/dev/null; then
      rm -f "$seed_lock/pid"
      rmdir "$seed_lock" 2>/dev/null || true
      echo "seed: another Elisa self-host seed is already running on this host (pid $global_seed_lock_pid); refusing concurrent high-memory build" >&2
      exit 2
    fi
    rm -f "$global_seed_lock/pid"
    rmdir "$global_seed_lock" 2>/dev/null || {
      rm -f "$seed_lock/pid"
      rmdir "$seed_lock" 2>/dev/null || true
      echo "seed: could not acquire stale global lock $global_seed_lock" >&2
      exit 2
    }
    mkdir "$global_seed_lock" || {
      rm -f "$seed_lock/pid"
      rmdir "$seed_lock" 2>/dev/null || true
      echo "seed: could not acquire global lock $global_seed_lock" >&2
      exit 2
    }
  fi
  printf '%s\n' "$$" >"$seed_lock/pid"
  printf '%s\n' "$$" >"$global_seed_lock/pid"
  # Never link directly over the product binary. Readers may be compiling through the wrapper
  # while another session refreshes the seed; an in-place clang output can expose a truncated
  # executable or make two adjacent parity probes use different compiler generations. Link next
  # to the final path and publish it with one same-filesystem rename after the complete image is
  # ready.
  seed_output="${BIN}.tmp.$$"
  # The stage0 compiler also writes a large object. Publish that object atomically too:
  # a concurrent stage1 invocation must never observe a truncated object while the guarded
  # seed is still running. Keeping the temporary name private also makes an RSS-guarded
  # termination recoverable without leaving a misleading apparently-valid artifact.
  seed_object="$ROOT/build/elisac_stage1.o.tmp.$$"
  ELISA_SEED_OUTPUT="$seed_output"
  ELISA_SEED_OBJECT="$seed_object"
  cleanup_seed_lock() {
    if [[ -n "${ELISA_SEED_OUTPUT:-}" ]]; then
      rm -f "$ELISA_SEED_OUTPUT"
    fi
    if [[ -n "${ELISA_SEED_OBJECT:-}" ]]; then
      rm -f "$ELISA_SEED_OBJECT"
    fi
    rm -f "$ELISA_SEED_LOCK_DIR/pid"
    rmdir "$ELISA_SEED_LOCK_DIR" 2>/dev/null || true
    if [[ -n "${ELISA_SEED_GLOBAL_LOCK_DIR:-}" ]]; then
      rm -f "$ELISA_SEED_GLOBAL_LOCK_DIR/pid"
      rmdir "$ELISA_SEED_GLOBAL_LOCK_DIR" 2>/dev/null || true
    fi
  }
  trap cleanup_seed_lock EXIT INT TERM HUP
  libdir="$("$LLVM_CONFIG" --libdir)"
  mkdir -p "$ROOT/bin" "$ROOT/build"
  if [[ ! -x "$STAGE0_BIN" ]]; then
    echo "seed requires stage0 elisac at ELISACORE_BIN=$STAGE0_BIN" >&2
    exit 2
  fi
  echo "seed: building product with stage0 $STAGE0_BIN" >&2
  # The compiler itself is a large input. A duplicated seed can consume the whole
  # workstation before either invocation reports an error, so bound one seed by default.
  # Keep one-shot seed builds below the same 4 GiB operational ceiling used by ordinary
  # stage1 invocations. The compiler is large, but allowing the default seed to claim 5.5 GiB
  # made two independent worktrees capable of freezing a developer machine at the same time;
  # raise ELISA_STAGE1_SEED_MAX_RSS_KB deliberately on a host sized for a larger build.
  seed_max_rss_kb="${ELISA_STAGE1_SEED_MAX_RSS_KB:-4194304}"
  seed_rss_poll_seconds="${ELISA_STAGE1_RSS_POLL_SECONDS:-0.05}"
  seed_opt_level="${ELISA_STAGE1_SEED_OPT_LEVEL:--O2}"
  case "$seed_opt_level" in
    -O0|-O1|-O2|-O3) ;;
    *)
      echo "seed: ELISA_STAGE1_SEED_OPT_LEVEL must be -O0, -O1, -O2 or -O3 (got $seed_opt_level)" >&2
      exit 2
      ;;
  esac
  "$STAGE0_BIN" -emit obj "$seed_opt_level" -o "$seed_object" "$ROOT/src/driver/elisac.elisa" &
  seed_pid=$!
  seed_peak_rss_kb=0
  while kill -0 "$seed_pid" 2>/dev/null; do
    # The child may exit between kill(0) and ps(1). With `set -euo pipefail`, the
    # resulting non-zero ps status used to abort the seed shell before `wait` could
    # collect the child's successful status, making a completed seed look failed.
    seed_rss_kb="$(ps -o rss= -p "$seed_pid" 2>/dev/null | awk '{print $1}')" || seed_rss_kb=""
    if [[ -n "$seed_rss_kb" && "$seed_rss_kb" -gt "$seed_peak_rss_kb" ]]; then
      seed_peak_rss_kb="$seed_rss_kb"
    fi
    if [[ -n "$seed_rss_kb" && "$seed_rss_kb" -gt "$seed_max_rss_kb" ]]; then
      echo "seed: memory guard stopped pid $seed_pid at ${seed_rss_kb} KB (limit ${seed_max_rss_kb} KB; peak ${seed_peak_rss_kb} KB)" >&2
      terminate_guarded_pid "$seed_pid"
      exit 125
    fi
    sleep "$seed_rss_poll_seconds"
  done
  wait "$seed_pid"
  # -stack_size: a deeply left-nested expression (adversarial input, see
  # malformed_input_fuzz.py / the depth guard in codegen_scope.elisa's expression_type)
  # recurses once per AST level through emit_expression. 0x20000000 (512MB) is the max
  # ld64 allows on arm64 and gives the compiler's own main thread far more headroom than
  # the default ~8MB before a pathological input can overflow the native stack.
  [[ -x "$ELISA_CLANG_TOOL" ]] || {
    echo "seed requires clang compatible with LLVM_CONFIG=$LLVM_CONFIG (set ELISA_CLANG)" >&2
    exit 2
  }
  # The compiler source includes the complete standard runtime.  Its optional
  # native-callback and varargs entry points are deliberately unreachable from
  # the compiler itself and are provided only when linking an executable/runtime
  # consumer.  Dead-strip those sections here, matching the other self-host
  # product links, instead of requiring unrelated host runtime symbols.
  "$ELISA_CLANG_TOOL" -Wl,-dead_strip -o "$seed_output" "$seed_object" -L"$libdir" -lLLVM -Wl,-rpath,"$libdir" -Wl,-stack_size,0x20000000
  mv -f "$seed_output" "$BIN"
  mv -f "$seed_object" "$ROOT/build/elisac_stage1.o"
  ELISA_SEED_OUTPUT=""
  echo "seed: wrote $BIN" >&2
}

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
stale_stage1_source="$(find "$ROOT/src" -type f -name '*.elisa' -newer "$BIN" -print -quit)"
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
opt_level=0
test_filter=""
emit_mode="obj"
target_triple=""
wasm_ld=""
link_flags=()
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
    # Cross-compilation and linker passthrough. The DRIVER has implemented both for a
    # while (requested_target_triple, and ELISA_STAGE1_LINK read in the c-archive/exe
    # paths) — only this wrapper rejected them, so `-target-triple` and `-link/-L/-l`
    # looked like compiler gaps when they were three missing cases in an argument loop.
    -target-triple)
      target_triple="${2:-}"; shift 2 ;;
    --wasm-ld)
      wasm_ld="${2:-}"; shift 2 ;;
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

# WASM is a packaging target, not just another object suffix: it needs a wasm-ld link,
# imported linear memory, and the generated ESM/TypeScript facade. Keep that orchestration
# in one dependency-light Python helper so the shell wrapper remains pleasant to use and
# callers get a complete module with one command.
if [[ "$emit_mode" == "wasm" ]]; then
  [[ -n "$src" ]] || { echo "usage: $0 -emit wasm -o out.wasm source.elisa" >&2; exit 2; }
  if [[ -z "$out" ]]; then
    out="${src%.*}.wasm"
  elif [[ "$out" != *.wasm ]]; then
    out="${out}.wasm"
  fi
  wasm_python="${PYTHON_BIN:-python3}"
  command -v "$wasm_python" >/dev/null 2>&1 || {
    echo "-emit wasm requires Python 3 (set PYTHON_BIN)" >&2
    exit 2
  }
  wasm_command=("$wasm_python" "$ROOT/scripts/wasm_build.py" --root "$ROOT" --compiler "$0" --source "$src" --output "$out" --target "${target_triple:-wasm32-unknown-unknown}")
  [[ -n "$wasm_ld" ]] && wasm_command+=(--wasm-ld "$wasm_ld")
  [[ "$noalias" == 1 ]] && wasm_command+=(--compiler-flag=-fnoalias)
  [[ "$bounds_check" == 1 ]] && wasm_command+=(--compiler-flag=-fbounds-check)
  [[ "$opt_level" != 0 ]] && wasm_command+=("--compiler-flag=-O$opt_level")
  exec "${wasm_command[@]}"
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
[[ -x "$PYTHON_HOST" ]] || {
  echo "stage1 requires python3 for include expansion (set PYTHON_BIN)" >&2
  exit 2
}
# Keep all Python-facing emitters consistent: explicit manifest, generated C, stub, and
# complete-extension paths may point into a directory that does not exist yet.
case "$emit_mode" in
  pymodule|pymodule-c)
    [[ -z "$out" ]] || mkdir -p "$(dirname -- "$out")" ;;
esac

flat="$(mktemp)"
stage1_request="$(mktemp)"
trap 'rm -f "$flat" "$flat.map" "$stage1_request"' EXIT
flatten_includes "$src" "$flat.map" >"$flat"
# `# smt` belongs to the original source header, but include flattening can place that
# header far beyond the first few lines of the expanded buffer. Detect it here, before the
# source enters the self-hosted compiler, and pass a one-bit fact through the environment.
# This keeps stage1's in-compiler fallback bounded; an 11 MB self-host input must not turn
# a header check into an O(source-size) loop in every generated compiler.
if grep -Eq '^[[:space:]]*#[[:space:]]*smt([[:space:]]|$)' "$src"; then
  export ELISA_STAGE1_SMT=1
else
  unset ELISA_STAGE1_SMT
fi
# Trusted-stdlib marker: stage0 skips the user-code-only passes (raw-concurrency surface
# removal, region-tied return) for elisacore_std's OWN sources, deciding per FILE. stage1
# cannot — flattening concatenates without line directives, so a declaration's origin is gone
# by the time the driver sees the source. Decide from the FLATTENED UNIT's CONTENT, not the
# input path: a program that `include`s the std pulls the std's own definitions into the unit
# and would otherwise be judged as if it had written them. Keying on the path missed exactly
# that — every corpus program includes the std. See runtime_std_enabled().
if grep -q 'def arena_alloc(' "$flat" 2>/dev/null; then
  export ELISA_STAGE1_RUNTIME_STD=1
fi
# `-emit deps` / `-emit deps-json` are handled by the DRIVER (emit_deps_report in
# elisac.elisa), like every other emit mode. They used to be computed here in ~30 lines of
# Python that re-walked the include graph — a second implementation of dependency discovery,
# in a second language, shadowing a correct one: the driver produced stage0's exact bytes and
# never got to run. Verified identical to stage0 for both formats over a nested include chain
# before this was deleted.

# `-emit exe`: compile to a temporary object, then link with the runtime object.
runtime_obj="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
link_out=""
if [[ "$emit_mode" == "exe" ]]; then
  [[ -f "$runtime_obj" ]] || { echo "-emit exe requires the runtime object at $runtime_obj (run scripts/build_runtime_object.sh)" >&2; exit 2; }
  link_out="$out"
  out="$(mktemp).o"
  emit_mode="obj"
fi

# `-emit pymodule-so` is the host-facing convenience path for the complete Python
# extension pipeline.  The compiler still owns the language-facing pieces (the
# machine-readable export manifest, the CPython C shim, and the native object); this
# wrapper owns the platform toolchain invocation so a user only needs one command.
if [[ "$emit_mode" == "pymodule-so" ]]; then
  [[ -x "$ELISA_CLANG_TOOL" ]] || {
    echo "-emit pymodule-so requires clang compatible with LLVM_CONFIG=$LLVM_CONFIG (set ELISA_CLANG)" >&2
    exit 2
  }
  python_config="$PYTHON_CONFIG_HOST"
  python_bin="$PYTHON_HOST"
  [[ -x "$python_bin" ]] || {
    echo "-emit pymodule-so requires python3 (set PYTHON_BIN)" >&2
    exit 2
  }
  pymodule_runtime_auto=0
  if [[ ! -f "$runtime_obj" && "${ELISA_PYMODULE_AUTO_RUNTIME:-1}" != "0" ]]; then
    runtime_support="$ROOT/elisacore_std/native_runtime_support.elisa"
    [[ -f "$runtime_support" ]] || {
      echo "-emit pymodule-so cannot auto-build the runtime: missing $runtime_support; run scripts/build_runtime_object.sh or set ELISA_RUNTIME_OBJ" >&2
      exit 2
    }
    mkdir -p "$(dirname -- "$runtime_obj")"
    echo "pymodule-so: building runtime object at $runtime_obj" >&2
    "$0" -emit obj -O0 -o "$runtime_obj" "$runtime_support"
    pymodule_runtime_auto=1
  fi
  [[ -f "$runtime_obj" ]] || {
    echo "-emit pymodule-so requires the runtime object at $runtime_obj (run scripts/build_runtime_object.sh or set ELISA_PYMODULE_AUTO_RUNTIME=0)" >&2
    exit 2
  }

  pymodule_work="$(mktemp -d)"
  trap 'rm -f "$flat" "$flat.map"; rm -rf "$pymodule_work"' EXIT
  pymodule_manifest="$pymodule_work/manifest.json"
  pymodule_c="$pymodule_work/module.c"
  pymodule_obj="$pymodule_work/module.o"

  # Emit the manifest first so the no-output-path form can derive its canonical
  # module name before choosing an ABI-tagged filename.
  "$0" -emit pymodule -o "$pymodule_manifest" "$src"
  pymodule_module="$("$python_bin" - "$pymodule_manifest" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    manifest = json.load(f)
module = manifest.get("module")
if not isinstance(module, str) or not module:
    raise SystemExit("pymodule manifest has no module name")
print(module)
PY
)"
  if [[ -z "$out" ]]; then
    out="$pymodule_module"
  fi

  # Python's import machinery recognizes ABI-tagged extension suffixes (and the plain .so
  # fallback), not an arbitrary suffixless filename. Keep the convenient no-output-path and
  # -o demo spellings importable by appending the selected interpreter's canonical suffix;
  # explicit .so or ABI-tagged output names remain untouched.
  pymodule_ext_suffix="$("$python_bin" - <<'PY'
import sysconfig

suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
print(suffix)
PY
)"
  [[ -n "$pymodule_ext_suffix" ]] || {
    echo "-emit pymodule-so could not determine Python's extension suffix" >&2
    exit 2
  }
  pymodule_output_has_suffix=0
  pymodule_extension_suffixes="$("$python_bin" - <<'PY'
import _imp

for suffix in _imp.extension_suffixes():
    print(suffix)
PY
)"
  while IFS= read -r pymodule_known_suffix; do
    if [[ -n "$pymodule_known_suffix" && "$out" == *"$pymodule_known_suffix" ]]; then
      pymodule_output_has_suffix=1
      break
    fi
  done <<< "$pymodule_extension_suffixes"
  if [[ "$pymodule_output_has_suffix" == 0 ]]; then
    out="${out}${pymodule_ext_suffix}"
  fi

  # Validate the import-facing basename before compiling the generated shim/object. This turns
  # a common typo (`-o wrong-name.so`) into an immediate diagnostic instead of doing all the
  # expensive native work first. The suffix matcher also accepts ABI-tagged names from a
  # different Python installation, which is useful when the build and import interpreters
  # intentionally differ.
  pymodule_output_base="$(basename -- "$out")"
  pymodule_output_stem="$pymodule_output_base"
  while IFS= read -r pymodule_known_suffix; do
    if [[ -n "$pymodule_known_suffix" && "$pymodule_output_base" == *"$pymodule_known_suffix" ]]; then
      # Remove the exact suffix. Python ABI tags contain punctuation, but no Bash glob
      # metacharacters, so the variable expansion is an exact match.
      pymodule_output_stem="${pymodule_output_base%$pymodule_known_suffix}"
      break
    fi
  done <<< "$pymodule_extension_suffixes"
  if [[ "$pymodule_output_stem" != "$pymodule_module" && "$pymodule_output_base" == "$pymodule_module"* ]]; then
    pymodule_output_suffix="${pymodule_output_base#"$pymodule_module"}"
    case "$pymodule_output_suffix" in
      .abi3.so|.cpython-[0-9]*.so|.pypy*.so)
        pymodule_output_stem="$pymodule_module"
        ;;
    esac
  fi
  if [[ "$pymodule_output_stem" != "$pymodule_module" ]]; then
    echo "pymodule-so: output filename '$pymodule_output_base' must be named '$pymodule_module' plus a Python extension suffix to import as $pymodule_module" >&2
    exit 2
  fi
  mkdir -p "$(dirname -- "$out")"

  # Re-enter this wrapper for the generated C shim and native object. Keeping these calls
  # through the public CLI preserves include flattening, stdlib detection, diagnostics,
  # optimisation flags, and target-triple behaviour in one place.
  "$0" -emit pymodule-c -o "$pymodule_c" "$src"
  pymodule_compile_args=()
  case "$opt_level" in
    1) pymodule_compile_args+=("-O1") ;;
    2) pymodule_compile_args+=("-O2") ;;
    3) pymodule_compile_args+=("-O3") ;;
  esac
  [[ -n "$target_triple" ]] && pymodule_compile_args+=("-target-triple" "$target_triple")
  [[ "$noalias" == 1 ]] && pymodule_compile_args+=("-fnoalias")
  [[ "$bounds_check" == 1 ]] && pymodule_compile_args+=("-fbounds-check")
  if [[ ${#pymodule_compile_args[@]} -gt 0 ]]; then
    "$0" -emit obj -o "$pymodule_obj" "${pymodule_compile_args[@]}" "$src"
  else
    "$0" -emit obj -o "$pymodule_obj" "$src"
  fi

  if [[ -n "$python_config" ]]; then
    [[ -x "$python_config" ]] || {
      echo "-emit pymodule-so requires a usable python3-config (set PYTHON_CONFIG)" >&2
      exit 2
    }
    read -r -a pymodule_include_flags <<< "$("$python_config" --includes)"
  else
    pymodule_include_dir="$("$python_bin" -c 'import sysconfig; print(sysconfig.get_config_var("INCLUDEPY") or sysconfig.get_path("include") or "")' 2>/dev/null || true)"
    [[ -n "$pymodule_include_dir" && -d "$pymodule_include_dir" ]] || {
      echo "-emit pymodule-so could not determine Python headers for $python_bin (set PYTHON_CONFIG)" >&2
      exit 2
    }
    pymodule_include_flags=("-I$pymodule_include_dir")
  fi
  # The object backend can deliberately decline an unsupported target body. On Darwin the
  # bundle linker permits unresolved symbols for Python's C API, which would otherwise let a
  # missing Elisa wrapper survive until `import module` with an opaque dynamic-loader error.
  # Audit every manifest row before linking so the user gets the exact exported symbol that
  # needs a supported native ABI.
  pymodule_nm_tool="${ELISA_LLVM_NM:-$LLVM_BIN_DIR/llvm-nm}"
  if [[ -x "$pymodule_nm_tool" ]]; then
    "$pymodule_nm_tool" -g "$pymodule_obj" >"$pymodule_work/symbols.txt"
    if ! "$python_bin" - "$pymodule_manifest" "$pymodule_work/symbols.txt" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    manifest = json.load(f)
with open(sys.argv[2], encoding="utf-8") as f:
    symbols = {line.split()[-1].lstrip("_") for line in f if line.split()}
module = manifest["module"]
missing = [
    f"elisa_pymodule_{module}_{entry['name']}"
    for entry in manifest.get("functions", [])
    if f"elisa_pymodule_{module}_{entry['name']}" not in symbols
]
missing += [
    f"elisa_pymodule_{module}_{entry['name']}"
    for entry in manifest.get("constants", [])
    if f"elisa_pymodule_{module}_{entry['name']}" not in symbols
]
if missing:
    for symbol in missing:
        print(f"error: native pymodule symbol missing from object: {symbol}", file=sys.stderr)
    raise SystemExit(1)
PY
    then
      exit 1
    fi
  fi
  # A pymodule object is linked together with the complete Elisa runtime. User functions are
  # reached through their generated `elisa_pymodule_*` wrappers, so any same-named definition
  # already present in the runtime must remain local to the module object. A common function
  # such as `fail` otherwise produces a duplicate-symbol linker error before Python can import
  # the extension. Localizing only the exact intersection preserves every public wrapper.
  pymodule_objcopy_tool="${ELISA_LLVM_OBJCOPY:-$LLVM_BIN_DIR/llvm-objcopy}"
  if [[ -x "$pymodule_nm_tool" && -x "$pymodule_objcopy_tool" ]]; then
    "$pymodule_nm_tool" --defined-only -g --format=posix "$pymodule_obj" | awk '{print $1}' | sort -u >"$pymodule_work/module-defined.txt"
    "$pymodule_nm_tool" --defined-only -g --format=posix "$runtime_obj" | awk '{print $1}' | sort -u >"$pymodule_work/runtime-defined.txt"
    comm -12 "$pymodule_work/module-defined.txt" "$pymodule_work/runtime-defined.txt" >"$pymodule_work/localize-symbols.txt"
    if [[ -s "$pymodule_work/localize-symbols.txt" ]]; then
      "$pymodule_objcopy_tool" --localize-symbols="$pymodule_work/localize-symbols.txt" "$pymodule_obj"
    fi
  fi
  pymodule_link_inputs=("$pymodule_c" "$pymodule_obj" "$runtime_obj")
  # The runtime intentionally leaves the host callback hooks unresolved. This is true for
  # both an object auto-built above and the repository's normal prebuilt runtime object.
  # Supply the extension-safe fallbacks whenever those imports are present; restricting this
  # to the auto-build path produced a .so that linked successfully on Darwin but failed at
  # import time with `_elisa_native_callback_call_i32_voidp` missing.
  pymodule_needs_callback_fallback="$pymodule_runtime_auto"
  pymodule_host_nm="${ELISA_LLVM_NM:-$LLVM_BIN_DIR/llvm-nm}"
  if [[ "$pymodule_needs_callback_fallback" != 1 && -x "$pymodule_host_nm" ]] && \
      "$pymodule_host_nm" -u "$runtime_obj" 2>/dev/null | grep -q 'elisa_native_callback_'; then
    pymodule_needs_callback_fallback=1
  fi
  if [[ "$pymodule_needs_callback_fallback" == 1 ]]; then
    # The complete runtime also carries optional native-callback and varargs hooks whose
    # host implementations are supplied by an executable, not by a Python extension. Provide
    # the documented fallback behavior (return the caller's fallback value/no-op) so importing a
    # simple module does not fail on unrelated runtime entry points.
    pymodule_callback_fallback_obj="$pymodule_work/native_callback_fallback.o"
    "$ELISA_CLANG_TOOL" -c -fPIC -fno-builtin -O2 -o "$pymodule_callback_fallback_obj" "$ROOT/scripts/pymodule_runtime_fallback.c"
    pymodule_link_inputs+=("$pymodule_callback_fallback_obj")
  fi
  pymodule_link_command=()
  if [[ "$(uname -s)" == "Darwin" ]]; then
    pymodule_link_command=("$ELISA_CLANG_TOOL" -bundle -undefined dynamic_lookup -Wl,-dead_strip)
  elif [[ "$(uname -s)" == "Linux" ]]; then
    pymodule_link_command=("$ELISA_CLANG_TOOL" -shared -fPIC -Wl,--gc-sections)
  else
    echo "-emit pymodule-so is unsupported on $(uname -s)" >&2
    exit 2
  fi
  pymodule_link_command+=("${pymodule_include_flags[@]}" -o "$out" "${pymodule_link_inputs[@]}")
  "${pymodule_link_command[@]}"
  # A native extension is most useful when IDEs can discover its typed surface immediately.
  # Keep the sidecar beside the extension and name it after the manifest module, rather than
  # after the ABI-tagged filename (`demo.cpython-314-darwin.so` -> `demo.pyi`).
  pymodule_stub="$(dirname -- "$out")/$pymodule_module.pyi"
  "$python_bin" "$ROOT/scripts/pymodule_pyi.py" "$pymodule_manifest" "$pymodule_stub"
  echo "pymodule-so: wrote $out and $pymodule_stub (import as $pymodule_module)" >&2
  exit 0
fi

# Run the self-hosted compiler as a direct child so its RSS can be observed. The previous
# stdin pipeline made it possible for a large compile to escape every wrapper-level guard:
# the shell only waited on the pipeline while the compiler itself grew into swap. The limit
# is deliberately conservative for ordinary development; a dedicated build host can raise
# ELISA_STAGE1_MAX_RSS_KB explicitly.
run_stage1_driver_guarded() {
  local driver_pid driver_rss driver_peak=0 driver_rc=0
  local driver_max_rss_kb="${ELISA_STAGE1_MAX_RSS_KB:-4194304}"
  local driver_rss_poll_seconds="${ELISA_STAGE1_RSS_POLL_SECONDS:-0.05}"
  env "${driver_env[@]+${driver_env[@]}}" "$BIN" <"$stage1_request" &
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
    sleep "$driver_rss_poll_seconds"
  done
  wait "$driver_pid" || driver_rc=$?
  return "$driver_rc"
}

# `-emit pymodule-pyi` renders a type-checker stub from the compiler-owned JSON contract. It
# intentionally has no native-toolchain dependency: a manifest is enough to describe the Python
# surface, so editor/type-checking workflows remain useful even when clang or the runtime object
# are not installed on the host.
if [[ "$emit_mode" == "pymodule-pyi" ]]; then
  python_bin="$PYTHON_HOST"
  [[ -x "$python_bin" ]] || {
    echo "-emit pymodule-pyi requires python3 (set PYTHON_BIN)" >&2
    exit 2
  }
  pymodule_work="$(mktemp -d)"
  trap 'rm -f "$flat" "$flat.map"; rm -rf "$pymodule_work"' EXIT
  pymodule_manifest="$pymodule_work/manifest.json"
  "$0" -emit pymodule -o "$pymodule_manifest" "$src"
  pymodule_module="$("$python_bin" - "$pymodule_manifest" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    manifest = json.load(f)
module = manifest.get("module")
if not isinstance(module, str) or not module:
    raise SystemExit("pymodule manifest has no module name")
print(module)
PY
)"
  if [[ -z "$out" ]]; then
    out="$pymodule_module.pyi"
  fi
  mkdir -p "$(dirname -- "$out")"
  "$python_bin" "$ROOT/scripts/pymodule_pyi.py" "$pymodule_manifest" "$out"
  echo "pymodule-pyi: wrote $out" >&2
  exit 0
fi

# Optimisation level and emit mode reach the driver via env (the stdin protocol
# carries only the output path and the source).
driver_env=()
# Diagnostics name the source file (stage0's `PATH:LINE: message`). The wrapper is the only
# side that knows the ORIGINAL path once includes are flattened, so pass it for EVERY mode,
# not just the report modes below — otherwise a wrapper-compiled program reports a bare
# line number while the same file compiled through the CLI names itself.
driver_env+=("ELISA_STAGE1_SRC=$src")
[[ -n "$target_triple" ]] && driver_env+=("ELISA_STAGE1_TRIPLE=$target_triple")
[[ "$target_triple" == wasm* ]] && driver_env+=("ELISA_STAGE1_WASM=1")
[[ ${#link_flags[@]} -gt 0 ]] && driver_env+=("ELISA_STAGE1_LINK=${link_flags[*]}")
[[ "$opt_level" != 0 ]] && driver_env+=("ELISA_STAGE1_OPT=$opt_level")
[[ "$emit_mode" == "llvm" ]] && driver_env+=("ELISA_STAGE1_EMIT=llvm")
[[ "$emit_mode" == "bc" ]] && driver_env+=("ELISA_STAGE1_EMIT=bc")
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
  # `-emit fmt` additionally needs the OFFSET MAP (see flatten_includes): stage0 names
  # its synthesized auto-regions `__auto_<pos.Offset>` with offsets measured over its
  # directive-bearing expansion. ELISA_STAGE1_SRC stays as given — the tokens report
  # prints it verbatim and is byte-parity held.
  driver_env+=("ELISA_STAGE1_EMIT=$emit_mode" "ELISA_STAGE1_SRC=$src")
  [[ -n "$test_filter" ]] && driver_env+=("ELISA_STAGE1_FILTER=$test_filter")
  if [[ ( "$emit_mode" == "fmt" || "$emit_mode" == "lowered" ) && -s "$flat.map" ]]; then
    driver_env+=("ELISA_STAGE1_OFFSET_MAP=$(cat "$flat.map")")
  fi
  exec > "$out"
fi
# stdin protocol: output path line, then source. Materialize the request so the compiler can
# be monitored directly; this is bounded by the already-created flattened source, not an
# unbounded shell pipe buffer.
{ printf '%s\n' "$out"; cat "$flat"; } >"$stage1_request"
if [[ "$noalias" == 1 && "$bounds_check" == 1 ]]; then
  driver_env+=("ELISACORE_NOALIAS_MUTABLE_REFS=1" "ELISACORE_FORCE_BOUNDS_CHECK=1")
elif [[ "$noalias" == 1 ]]; then
  driver_env+=("ELISACORE_NOALIAS_MUTABLE_REFS=1")
elif [[ "$bounds_check" == 1 ]]; then
  driver_env+=("ELISACORE_FORCE_BOUNDS_CHECK=1")
fi
run_stage1_driver_guarded
compile_rc=$?
if [[ -n "$link_out" ]]; then
  [[ "$compile_rc" == 0 && -f "$out" ]] || { rm -f "$out"; exit "${compile_rc:-1}"; }
  [[ -x "$ELISA_CLANG_TOOL" ]] || {
    echo "-emit exe requires clang compatible with LLVM_CONFIG=$LLVM_CONFIG (set ELISA_CLANG)" >&2
    rm -f "$out"
    exit 2
  }
  "$ELISA_CLANG_TOOL" -Wl,-dead_strip -o "$link_out" "$out" "$runtime_obj" || { rm -f "$out"; exit 1; }
  rm -f "$out"
fi
exit "$compile_rc"
