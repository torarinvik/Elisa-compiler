#!/usr/bin/env bash
# Host-facing CLI for the stage1 product compiler.
#
# Usage:
#   elisac_stage1.sh -o out.o source.elisa
#   elisac_stage1.sh --seed          # one-time seed build using stage0 (optional)
#   elisac_stage1.sh --emit-driver   # only build the product binary (needs seed elisac)
#
# Include expansion is a host packaging step (matches stage0's readSourceWithIncludes).
# The compiler binary itself is pure stage1 frontend+backend.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
STAGE0_BIN="${ELISACORE_BIN:-${HOME}/.elisac/elisac}"

flatten_includes() {
  python3 - "$1" <<'PY'
import re, pathlib, sys
path = pathlib.Path(sys.argv[1]).resolve()
include_re = re.compile(r'^[ \t]*(?:#\s*)?include[ \t]+"([^"]+)"[ \t]*$')
seen = set()

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
    for line in text.splitlines(keepends=True):
        m = include_re.match(line.rstrip("\n"))
        if m:
            rel = m.group(1)
            inc = pathlib.Path(rel) if pathlib.Path(rel).is_absolute() else (base / rel)
            if not inc.exists():
                raise SystemExit(f"missing include {rel!r} from {p}")
            flatten(inc, out, stack)
        else:
            out.append(line)
    stack.pop()

out: list[str] = []
flatten(path, out, [])
sys.stdout.write("".join(out))
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
  clang -o "$BIN" "$ROOT/build/elisac_stage1.o" -L"$libdir" -lLLVM -Wl,-rpath,"$libdir"
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

out=""
src=""
noalias=0
bounds_check=0
opt_level=0
emit_mode="obj"
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
        exe)    emit_mode="exe" ;;
        tokens) emit_mode="tokens" ;;
        ast)    emit_mode="ast" ;;
        iface)  emit_mode="iface" ;;
        deps)      emit_mode="deps" ;;
        deps-json) emit_mode="deps-json" ;;
        *) echo "only -emit obj, -emit llvm, -emit exe, -emit tokens, -emit ast, -emit iface, -emit deps and -emit deps-json are supported" >&2; exit 2 ;;
      esac
      shift 2 ;;
    -fnoalias)
      noalias=1; shift ;;
    -fbounds-check)
      bounds_check=1; shift ;;
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

[[ -n "$out" && -n "$src" ]] || { echo "usage: $0 -o out.o source.elisa" >&2; exit 2; }
[[ -f "$src" ]] || { echo "missing source: $src" >&2; exit 2; }

flat="$(mktemp)"
trap 'rm -f "$flat"' EXIT
flatten_includes "$src" >"$flat"
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
# `-emit deps` / `-emit deps-json`: the resolved include CLOSURE, root first then each
# include in first-encounter (pre-order) fingerprint — the same walk flatten_includes
# performs, printed instead of expanded, in stage0's two formats (absolute paths; the
# JSON shape of Go's encoder with two-space indent). No driver involved: dependency
# discovery is a wrapper concern exactly like include expansion.
if [[ "$emit_mode" == "deps" || "$emit_mode" == "deps-json" ]]; then
  python3 - "$src" "$emit_mode" > "$out" <<'DEPS_PY'
import json, pathlib, re, sys
path = pathlib.Path(sys.argv[1]).resolve()
mode = sys.argv[2]
include_re = re.compile(r'^[ \t]*(?:#\s*)?include[ \t]+"([^"]+)"[ \t]*$')
seen = set()
order = []
def walk(p):
    ap = p.resolve()
    if ap in seen:
        return
    seen.add(ap)
    order.append(str(ap))
    base = p.parent
    for line in p.read_text(encoding="utf-8").splitlines():
        m = include_re.match(line)
        if m:
            rel = m.group(1)
            inc = pathlib.Path(rel) if pathlib.Path(rel).is_absolute() else (base / rel)
            if inc.exists():
                walk(inc)
walk(path)
if mode == "deps":
    sys.stdout.write("".join(f + "\n" for f in order))
else:
    payload = {"root": str(path), "files": order}
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
DEPS_PY
  exit $?
fi

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
[[ "$opt_level" != 0 ]] && driver_env+=("ELISA_STAGE1_OPT=$opt_level")
[[ "$emit_mode" == "llvm" ]] && driver_env+=("ELISA_STAGE1_EMIT=llvm")
# `-emit tokens` prints the report on STDOUT (stage0's shape); redirect it to -o. The
# report names the ORIGINAL source path, which only the wrapper knows.
if [[ "$emit_mode" == "tokens" || "$emit_mode" == "ast" || "$emit_mode" == "iface" ]]; then
  driver_env+=("ELISA_STAGE1_EMIT=$emit_mode" "ELISA_STAGE1_SRC=$src")
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
  clang -Wl,-dead_strip -o "$link_out" "$out" "$runtime_obj" || { rm -f "$out"; exit 1; }
  rm -f "$out"
fi
exit "$compile_rc"
