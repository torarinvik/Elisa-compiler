#!/usr/bin/env bash
# A region-qualified sview parameter cannot lose its explicit lifetime at a return.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"

fail() { echo "sview region tie smoke FAIL: $1" >&2; exit 1; }
[[ -x "$STAGE0" ]] || fail "missing Stage0 compiler: $STAGE0"
[[ -x "$STAGE1" ]] || fail "missing Stage1 compiler: $STAGE1"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-tie.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat >"$WORK/good.elisa" <<'ELISA'
def forward[@r](view: sview @r) -> sview @r:
    return view

def plain_forward(view: sview) -> sview:
    return view

def main() -> i64:
    return 0
ELISA

cat >"$WORK/bad_drop.elisa" <<'ELISA'
def bad[@r](view: sview @r) -> sview:
    return view

def main() -> i64:
    return 0
ELISA

cat >"$WORK/bad_mismatch.elisa" <<'ELISA'
def bad[@r, @s](view: sview @r) -> sview @s:
    return view

def main() -> i64:
    return 0
ELISA

# Opaque pointer callbacks carry no typed region fact. They are legal to forward
# unchanged across the foreign-function boundary; only typed references and views
# participate in inferred region-return checks.
cat >"$WORK/opaque_callback.elisa" <<'ELISA'
def worker(arg: mutable void&?) -> mutable void&?:
    return arg

def main() -> i64:
    return 0
ELISA

cat >"$WORK/typed_reference_field.elisa" <<'ELISA'
struct Box:
    value: i64

def expose(box: mutable Box&) -> i64&:
    return &box.value

def main() -> i64:
    return 0
ELISA

for stage in stage0 stage1; do
    if [[ "$stage" == stage0 ]]; then compiler="$STAGE0"; else compiler="$STAGE1"; fi
    "$compiler" -emit llvm -O0 -o "$WORK/$stage-good.ll" "$WORK/good.elisa" >"$WORK/$stage-good.log" 2>&1 \
        || fail "$stage rejected lifetime-preserving or unannotated forwarding: $(tail -n 8 "$WORK/$stage-good.log")"
    "$compiler" -emit llvm -O0 -o "$WORK/$stage-opaque-callback.ll" "$WORK/opaque_callback.elisa" >"$WORK/$stage-opaque-callback.log" 2>&1 \
        || fail "$stage rejected opaque void-pointer callback forwarding: $(tail -n 8 "$WORK/$stage-opaque-callback.log")"
    for bad in bad_drop bad_mismatch; do
        if "$compiler" -emit llvm -O0 -o "$WORK/$stage-$bad.ll" "$WORK/$bad.elisa" >"$WORK/$stage-$bad.log" 2>&1; then
            fail "$stage accepted explicit sview region erasure in $bad"
        fi
        grep -Eq 'tied to region|sview parameter' "$WORK/$stage-$bad.log" \
            || fail "$stage rejected $bad for an unrelated reason: $(tail -n 8 "$WORK/$stage-$bad.log")"
    done
    if "$compiler" -emit llvm -O0 -o "$WORK/$stage-tied-call-return.ll" "$ROOT/test/repro/sview_region_tied_call_return.elisa" >"$WORK/$stage-tied-call-return.log" 2>&1; then
        fail "$stage accepted a view-producing method call that erased its @r parameter region"
    fi
    grep -Fq 'value tied to region parameter "r"' "$WORK/$stage-tied-call-return.log" \
        || fail "$stage failed to explain the erased method-call lifetime: $(tail -n 8 "$WORK/$stage-tied-call-return.log")"
done

if "$STAGE1" -emit llvm -O0 -o "$WORK/stage1-typed-reference-field.ll" "$WORK/typed_reference_field.elisa" >"$WORK/stage1-typed-reference-field.log" 2>&1; then
    fail "Stage1 accepted a region-erasing typed field-reference return"
fi
grep -Eq 'tied to region|reference parameter' "$WORK/stage1-typed-reference-field.log" \
    || fail "Stage1 rejected the typed field-reference return for an unrelated reason: $(tail -n 8 "$WORK/stage1-typed-reference-field.log")"

echo "sview region tie smoke OK: explicit lifetime erasure and mismatched returns are rejected"
