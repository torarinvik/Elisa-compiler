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
STAGE0_BIN="${ELISACORE_BIN:-${HOME}/.elisac/elisac}"

flatten_includes() {
  # Writes the flattened source to stdout. When $2 is given, also writes an OFFSET MAP
  # there: stage0 expands includes into a buffer with `#line <n> <abs path>` directives
  # spliced in (writeSourceWithIncludesWithOptionsActive), and its synthesized auto-region
  # names are `__auto_<offset in THAT buffer>`. The map records, at each flat-buffer
  # offset where the two buffers diverge, the byte DELTA (stage0 offset - flat offset), as
  # ascending `flatoff:delta` pairs — the driver's fmt adds the covering delta to a token
  # offset to recover stage0's number. Indented include directives (stage0 re-indents the
  # spliced lines) are not modeled; this repo's includes are all at column 0.
  python3 - "$1" "${2:-}" <<'PY'
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

seed_build() {
  local libdir
  libdir="$("$LLVM_CONFIG" --libdir)"
  mkdir -p "$ROOT/bin" "$ROOT/build"
  if [[ ! -x "$STAGE0_BIN" ]]; then
    echo "seed requires stage0 elisac at ELISACORE_BIN=$STAGE0_BIN" >&2
    exit 2
  fi
  echo "seed: building product with stage0 $STAGE0_BIN" >&2
  "$STAGE0_BIN" -emit obj -O2 -o "$ROOT/build/elisac_stage1.o" "$ROOT/src/driver/elisac.elisa"
  # -stack_size: a deeply left-nested expression (adversarial input, see
  # malformed_input_fuzz.py / the depth guard in codegen_scope.elisa's expression_type)
  # recurses once per AST level through emit_expression. 0x20000000 (512MB) is the max
  # ld64 allows on arm64 and gives the compiler's own main thread far more headroom than
  # the default ~8MB before a pathological input can overflow the native stack.
  [[ -x "$ELISA_CLANG_TOOL" ]] || {
    echo "seed requires clang compatible with LLVM_CONFIG=$LLVM_CONFIG (set ELISA_CLANG)" >&2
    exit 2
  }
  "$ELISA_CLANG_TOOL" -o "$BIN" "$ROOT/build/elisac_stage1.o" -L"$libdir" -lLLVM -Wl,-rpath,"$libdir" -Wl,-stack_size,0x20000000
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
        *) echo "only -emit obj, -emit llvm, -emit bc, -emit exe, -emit wasm, -emit tokens, -emit ast, -emit iface, -emit fmt, -emit doc, -emit header, -emit test-runner, -emit tests, -emit benches, -emit fixtures, -emit test, -emit c-bind-check, -emit c-bind-check-json, -emit packed, -emit unsafe, -emit c-archive, -emit lowered, -emit progress, -emit ir, -emit interpret, -emit deps and -emit deps-json are supported" >&2; exit 2 ;;
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
[[ -n "$out" && -n "$src" ]] || { echo "usage: $0 -o out.o source.elisa" >&2; exit 2; }
[[ -f "$src" ]] || { echo "missing source: $src" >&2; exit 2; }

flat="$(mktemp)"
trap 'rm -f "$flat" "$flat.map"' EXIT
flatten_includes "$src" "$flat.map" >"$flat"
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
if [[ "$emit_mode" == "tokens" || "$emit_mode" == "ast" || "$emit_mode" == "iface" || "$emit_mode" == "fmt" || "$emit_mode" == "doc" || "$emit_mode" == "header" || "$emit_mode" == "test-runner" || "$emit_mode" == "c-bind-check" || "$emit_mode" == "c-bind-check-json" || "$emit_mode" == "packed" || "$emit_mode" == "unsafe" || "$emit_mode" == "lowered" || "$emit_mode" == "progress" || "$emit_mode" == "deps" || "$emit_mode" == "deps-json" || "$emit_mode" == "ir" ]]; then
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
# stdin protocol: output path line, then source
if [[ "$noalias" == 1 && "$bounds_check" == 1 ]]; then
  { printf '%s\n' "$out"; cat "$flat"; } | env "${driver_env[@]+"${driver_env[@]}"}" ELISACORE_NOALIAS_MUTABLE_REFS=1 ELISACORE_FORCE_BOUNDS_CHECK=1 "$BIN"
elif [[ "$noalias" == 1 ]]; then
  { printf '%s\n' "$out"; cat "$flat"; } | env "${driver_env[@]+"${driver_env[@]}"}" ELISACORE_NOALIAS_MUTABLE_REFS=1 "$BIN"
elif [[ "$bounds_check" == 1 ]]; then
  { printf '%s\n' "$out"; cat "$flat"; } | env "${driver_env[@]+"${driver_env[@]}"}" ELISACORE_FORCE_BOUNDS_CHECK=1 "$BIN"
else
  { printf '%s\n' "$out"; cat "$flat"; } | env "${driver_env[@]+"${driver_env[@]}"}" "$BIN"
fi
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
