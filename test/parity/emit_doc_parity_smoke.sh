#!/usr/bin/env bash
# `-emit doc` BYTE PARITY, RATCHETED — same shape as emit_fmt_parity_smoke.sh.
#
# stage0's docgen renders a markdown reference page per declaration. stage1 models a
# COARSER declaration set than stage0 (its `Extern` node covers stage0's whole
# extern/export family, for instance), so the unported kinds fall through to stage0's own
# DEFAULT arm — a bare `## Declaration` section with a `- surface:` line. That is a real
# stage0 output shape, not a placeholder, so a file whose declarations all land on ported
# kinds is byte-identical while the rest differ honestly rather than silently.
#
# The gate is therefore a RATCHET on the count that round-trips byte-identically. Going
# below the baseline fails; raising it is a one-line commit when new decl arms land.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

BASELINE_FILE="$REPO_ROOT/test/fixtures/emit_doc.baseline"
baseline="$(tr -d '[:space:]' < "$BASELINE_FILE")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
total=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    "$ELISACORE_BIN" -emit doc -o "$WORK/$name.s0" "$src" </dev/null >/dev/null 2>&1 || continue
    bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit doc -o "$WORK/$name.s1" "$src" >/dev/null 2>&1 || continue
    total=$((total + 1))
    cmp -s "$WORK/$name.s0" "$WORK/$name.s1" && same=$((same + 1))
done

if [ "$same" -lt "$baseline" ]; then
    echo "emit_doc parity FAILED: $same byte-identical of $total, ratchet requires >= $baseline"
    exit 1
fi
echo "emit_doc parity OK: $same fixtures byte-identical of $total comparable (ratchet $baseline)"
