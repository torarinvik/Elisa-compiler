#!/usr/bin/env bash
# Diagnostic POSITIONS, which diagnostics_diff.sh is structurally blind to.
#
# That gate strips the `PATH:LINE:COL-ENDCOL:` prefix before comparing, on purpose — it is
# about message TEXT. So stage1 spent a long time printing `file:2:` where stage0 prints
# `file:2:5-6` with every message gate green. Positions need their own instrument.
#
# Three outcomes per diagnostic, the same discipline the easm-lint differential uses:
#
#   AGREE    stage1 printed a span and it is stage0's, character for character.
#   PENDING  stage1 printed the line but no span. Sound: the reporting check has not been
#            threaded to the AST node's `Ast::Pos` yet, and a missing column misleads no one.
#   DIVERGED stage1 printed a span that is NOT stage0's. Never acceptable — a wrong column
#            sends a reader (or an editor's jump-to-error) to the wrong place, which is worse
#            than no column at all. Any divergence fails this gate.
#
# PENDING is reported, not tolerated silently: the count is the remaining work, and it is
# printed on every run so it cannot quietly stop shrinking.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$BIN" || exit $?
EC="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$EC" || exit $?
FIXTURES="${DIAGNOSTIC_DIFF_FIXTURES:-$ROOT/test/fixtures/diagnostics}"

[ -x "$BIN" ] || { echo "diagnostic_columns_smoke FAIL: no stage1 binary at $BIN" >&2; exit 1; }
[ -x "$EC" ] || { echo "diagnostic_columns_smoke FAIL: no elisac at $EC" >&2; exit 1; }
[ -d "$FIXTURES" ] || { echo "diagnostic_columns_smoke SKIP: no fixtures at $FIXTURES"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

# `LINE MESSAGE` and `LINE:COLSTART-COLEND MESSAGE`, one per diagnostic, message collapsed to
# its first four words so the pairing survives the wording gaps the other gate tracks.
positions() { # <compiler> <fixture>
    "$1" -emit obj "$2" -o "$WORK/out.o" 2>&1 \
        | grep -vE '^[^:]*:[0-9]+(:[0-9-]+)*: warning:' \
        | sed -nE 's#^[^:]*:([0-9]+):([0-9]+-[0-9]+)?:?[[:space:]]*(([^ ]+ ){0,3}).*#\1|\2|\3#p'
}

agree=0; pending=0; diverged=0; fixtures=0
for fixture in "$FIXTURES"/*.elisa; do
    [ -f "$fixture" ] || continue
    fixtures=$((fixtures + 1))
    positions "$EC" "$fixture" > "$WORK/a" 2>/dev/null
    positions "$BIN" "$fixture" > "$WORK/b" 2>/dev/null
    counts=$(awk -F'|' -v fx="${fixture##*/}" -v shown="$diverged" '
        NR == FNR { key = $1 "|" $3; seen[key]++; span[key, seen[key]] = $2; next }
        {
            key = $1 "|" $3
            used[key]++
            if (used[key] > seen[key]) next          # stage1 row stage0 never printed
            a = span[key, used[key]]; b = $2
            if (b == "") { pending++ }
            else if (a == b) { agree++ }
            else {
                diverged++
                if (shown + diverged <= 10)
                    printf "  DIVERGED %s line %s: stage0 %s, stage1 %s\n", fx, $1, a, b > "/dev/stderr"
            }
        }
        END { printf "%d %d %d", agree + 0, pending + 0, diverged + 0 }
    ' "$WORK/a" "$WORK/b")
    agree=$((agree + ${counts%% *}))
    rest="${counts#* }"
    pending=$((pending + ${rest%% *}))
    diverged=$((diverged + ${rest##* }))
done

echo "diagnostic_columns_smoke: $fixtures fixtures — $agree agreeing, $pending pending (line only), $diverged diverged"
if [ "$diverged" -ne 0 ]; then
    echo "diagnostic_columns_smoke FAILED: $diverged diagnostics report a column that is not stage0's." >&2
    echo "  A wrong column is worse than none — fix the span at its source, do not drop it." >&2
    exit 1
fi
