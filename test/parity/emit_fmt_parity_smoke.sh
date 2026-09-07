#!/usr/bin/env bash
# `-emit fmt` BYTE PARITY, RATCHETED: the unparser port is landing arm by arm, and every
# unported shape prints a loud <fmt-*-todo> marker — so the honest gate is a RATCHET on
# the count of fixtures that round-trip byte-identically against stage0. Going below the
# baseline fails; raising it is a one-line commit when new arms land. (`__auto_<N>` is no
# longer a ceiling: N is the `def` token's byte offset in stage0's directive-bearing
# expansion, and since the driver splices the same directives the offset is stage1's own.)
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

BASELINE_FILE="$REPO_ROOT/test/fixtures/emit_fmt.baseline"
baseline="$(tr -d '[:space:]' < "$BASELINE_FILE")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    "$ELISACORE_BIN" -emit fmt "$src" </dev/null > "$WORK/$name.s0" 2>/dev/null || continue
    bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit fmt -o "$WORK/$name.s1" "$src" >/dev/null 2>&1 || continue
    cmp -s "$WORK/$name.s0" "$WORK/$name.s1" && same=$((same + 1))
done

if [ "$same" -lt "$baseline" ]; then
    echo "emit_fmt parity FAILED: $same byte-identical, ratchet requires >= $baseline"
    exit 1
fi
echo "emit_fmt parity OK: $same fixtures byte-identical (ratchet $baseline)"
