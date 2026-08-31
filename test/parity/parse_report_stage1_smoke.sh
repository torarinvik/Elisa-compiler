#!/usr/bin/env bash
# The shared semantic reporter must be compiled by stage1. A stage0-backed reporter makes
# semantic parity checks appear useful while never exercising the self-hosted product.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

[[ -x "$STAGE1_BIN" ]] || { echo "parse_report_stage1_smoke SKIP: no stage1 product at $STAGE1_BIN"; exit 0; }
[[ -f "$RUNTIME_OBJ" ]] || { echo "parse_report_stage1_smoke SKIP: no runtime object at $RUNTIME_OBJ"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

fake_stage0="$WORK/stage0"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  "touch '$WORK/stage0-invoked'" \
  'exit 99' \
  > "$fake_stage0"
chmod +x "$fake_stage0"

if ! REPO_ROOT="$ROOT" \
     ELISA_STAGE1_BIN="$STAGE1_BIN" \
     ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" \
     ELISACORE_BIN="$fake_stage0" \
     ELISA_PARSE_REPORT="$WORK/parse_report" \
     bash -c 'source "$1"' bash "$ROOT/test/parity/build_parse_report.sh"; then
  echo "parse_report_stage1_smoke FAILED: stage1 reporter build failed" >&2
  exit 1
fi

[[ ! -e "$WORK/stage0-invoked" ]] || {
  echo "parse_report_stage1_smoke FAILED: build_parse_report invoked stage0" >&2
  exit 1
}
[[ -x "$WORK/parse_report" ]] || {
  echo "parse_report_stage1_smoke FAILED: no stage1 parse_report was published" >&2
  exit 1
}

report="$(printf 'def f(n: i64) -> i64:\n    return n + 1\n' | "$WORK/parse_report")"
printf '%s\n' "$report" | grep -qx 'P 0'
printf '%s\n' "$report" | grep -qx 'D 0'

# Trusted runtime units may contain direct calls to effectful libc helpers in low-level
# implementation code. The stage1-only local-effect walk must honor the same # std boundary
# as stage0 instead of turning those implementation details into user diagnostics.
runtime_report="$(printf '# std\nextern write(fd: int, buf: void&, count: usize) -> isize can[Console]\ndef trace() -> void:\n    write(2, zeroed, 0) can Console\n' | "$WORK/parse_report")"
printf '%s\n' "$runtime_report" | grep -qx 'P 0'
printf '%s\n' "$runtime_report" | grep -qx 'D 0'

# Enum-variant arms with only binders/wildcards cover their complete constructor. A
# later arm for that constructor is unreachable, while a guarded first arm remains
# reachable and must not shadow the following arm.
shadow_report="$(printf '%s\n' \
  'enum MaybeInt:' \
  '    None' \
  '    Some(int)' \
  '' \
  'def unwrap(value: MaybeInt) -> int:' \
  '    match value:' \
  '        MaybeInt.Some(first):' \
  '            return first' \
  '        MaybeInt.Some(second):' \
  '            return second' \
  '        MaybeInt.None:' \
  '            return 0' \
  '    return 0' | "$WORK/parse_report")"
printf '%s\n' "$shadow_report" | grep -qx 'P 0'
printf '%s\n' "$shadow_report" | grep -qx 'D 1'

guarded_report="$(printf '%s\n' \
  'enum MaybeInt:' \
  '    None' \
  '    Some(int)' \
  '' \
  'def unwrap(value: MaybeInt) -> int:' \
  '    match value:' \
  '        MaybeInt.Some(first) if first > 0:' \
  '            return first' \
  '        MaybeInt.Some(second):' \
  '            return second' \
  '        MaybeInt.None:' \
  '            return 0' \
  '    return 0' | "$WORK/parse_report")"
printf '%s\n' "$guarded_report" | grep -qx 'P 0'
printf '%s\n' "$guarded_report" | grep -qx 'D 0'

# Layout metadata is numeric metadata, not a source-token index. The guest overlay
# access below is valid at offset 40 in a 48-byte object and must not inherit a
# spurious `requires size >= 288` diagnostic from the stage1 parser.
overlay_report="$(printf '%s\n' \
  'struct Pixel layout(guest, size: 48):' \
  '    bytes: u64 at 40 requires size >= 48' \
  '' \
  'def read(pixel: Pixel) -> u64:' \
  '    return pixel.bytes' | "$WORK/parse_report")"
printf '%s\n' "$overlay_report" | grep -qx 'P 0'
printf '%s\n' "$overlay_report" | grep -qx 'D 0'

# Block-form laws must retain their contract AST. In particular, a quantified law
# should reach the local refinement checker and produce the same unproven-proof
# warning as stage0 when SMT is enabled; an opaque/Invalid block silently skipped it.
law_report="$(printf '%s\n' \
  '# smt' \
  'law AllEqualFirst(self: darray[i64], n: i64):' \
  '    claim = forall i: (0 <= i and i < n) implies self[i] == self[0]' \
  '    return claim' \
  '' \
  'def check(xs: darray[i64]) -> i64:' \
  '    y: darray[i64] is AllEqualFirst[10] = xs' \
  '    return 0' | "$WORK/parse_report")"
printf '%s\n' "$law_report" | grep -qx 'P 0'
printf '%s\n' "$law_report" | grep -qx 'D 1'
echo "parse_report_stage1_smoke OK"
