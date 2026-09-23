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

for stage in stage0 stage1; do
    if [[ "$stage" == stage0 ]]; then compiler="$STAGE0"; else compiler="$STAGE1"; fi
    "$compiler" -emit llvm -O0 -o "$WORK/$stage-good.ll" "$WORK/good.elisa" >"$WORK/$stage-good.log" 2>&1 \
        || fail "$stage rejected lifetime-preserving or unannotated forwarding: $(tail -n 8 "$WORK/$stage-good.log")"
    for bad in bad_drop bad_mismatch; do
        if "$compiler" -emit llvm -O0 -o "$WORK/$stage-$bad.ll" "$WORK/$bad.elisa" >"$WORK/$stage-$bad.log" 2>&1; then
            fail "$stage accepted explicit sview region erasure in $bad"
        fi
        grep -Eq 'tied to region|sview parameter' "$WORK/$stage-$bad.log" \
            || fail "$stage rejected $bad for an unrelated reason: $(tail -n 8 "$WORK/$stage-$bad.log")"
    done
done

echo "sview region tie smoke OK: explicit lifetime erasure and mismatched returns are rejected"
