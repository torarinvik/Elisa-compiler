#!/usr/bin/env bash
# `-emit unsafe` BYTE PARITY.
#
# The report is a SAFETY claim — which functions hold which Unsafe.* capabilities — so this
# demands EXACT equality with stage0 on every fixture where stage0 produces a report. No
# ratchet: an under-reporting audit ("no unsafe operations" about code that has them) is
# worse than no audit, and that is precisely how a first attempt at this mode failed.
#
# The capability set is a TRANSITIVE CLOSURE, not a reading of each `can[...]`: a function
# calling an extern holds Unsafe.RawExtern without declaring it. The model is documented in
# test/parity/unsafe_permission_model_probe.py, which independently scores it at 40/40 with
# ZERO over-claim.
#
# SKIPPED fixtures are those where stage0's own audit REJECTS the program and it writes no
# report, so there is nothing to compare. stage1's strict audit disagrees with stage0's on
# those (see the emit-unsafe memory) — a separate, still-open divergence that this gate
# deliberately does not paper over.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
differ=0
skipped=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    if ! "$ELISACORE_BIN" -emit unsafe "$src" </dev/null > "$WORK/s0" 2>/dev/null; then
        skipped=$((skipped + 1)); continue
    fi
    if ! bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit unsafe -o "$WORK/s1" "$src" >/dev/null 2>&1; then
        differ=$((differ + 1)); echo "FAILED: $name — stage0 reported, stage1 did not"; continue
    fi
    if cmp -s "$WORK/s0" "$WORK/s1"; then
        same=$((same + 1))
    else
        differ=$((differ + 1)); echo "DIFF: $name"; diff "$WORK/s0" "$WORK/s1" | head -6
    fi
done

echo "emit_unsafe parity: $same byte-identical, $differ divergent, $skipped skipped"
[ "$differ" -eq 0 ] || { echo "emit_unsafe parity FAILED"; exit 1; }
echo "emit_unsafe parity OK"
