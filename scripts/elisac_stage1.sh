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
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o)
      out="${2:-}"; shift 2 ;;
    -emit)
      # accept -emit obj for familiarity; only obj is supported
      [[ "${2:-}" == "obj" ]] || { echo "only -emit obj is supported" >&2; exit 2; }
      shift 2 ;;
    -fnoalias)
      noalias=1; shift ;;
    -fbounds-check)
      bounds_check=1; shift ;;
    # stage1 runs NO LLVM pass pipeline (see src/driver/elisac.elisa: `default<O2>` has
    # trapped on large self-host modules). `-O0` is therefore the truth and is accepted.
    # An optimisation level we cannot honour is REJECTED rather than silently ignored:
    # accepting it made `-O0` and `-O3` produce byte-identical objects while the caller
    # believed otherwise — a wrong answer to a question the user asked, not a missing
    # feature. Optimise the emitted object with host `opt`/`clang` instead.
    -O0|-permissive) shift ;;
    -O1|-O2|-O3|-Os|-Oz)
      echo "$1: stage1 emits unoptimised objects (no LLVM pass pipeline); use -O0, or run host opt/clang on the object" >&2
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
# stdin protocol: output path line, then source
if [[ "$noalias" == 1 && "$bounds_check" == 1 ]]; then
  { printf '%s\n' "$out"; cat "$flat"; } | ELISACORE_NOALIAS_MUTABLE_REFS=1 ELISACORE_FORCE_BOUNDS_CHECK=1 "$BIN"
elif [[ "$noalias" == 1 ]]; then
  { printf '%s\n' "$out"; cat "$flat"; } | ELISACORE_NOALIAS_MUTABLE_REFS=1 "$BIN"
elif [[ "$bounds_check" == 1 ]]; then
  { printf '%s\n' "$out"; cat "$flat"; } | ELISACORE_FORCE_BOUNDS_CHECK=1 "$BIN"
else
  { printf '%s\n' "$out"; cat "$flat"; } | "$BIN"
fi
