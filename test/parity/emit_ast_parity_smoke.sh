#!/usr/bin/env bash
# `-emit ast` BYTE PARITY: stage1's parse-tree summary must be byte-identical to stage0's
# for every include-free repro fixture plus the dedicated AST fixtures. The interesting
# parts of the format are NOT free: the stmt count reflects stage0's region inference (a
# body declaring an auto-region container prints as ONE wrapped stmt; a region-annotated
# one does not), inferred region params print as `[@__rg_<param>]`, module paths print
# with dots, `using` declarations live only in side tables, and an extern renders its
# decorators and return spelling from the source tokens.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
failed=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    grep -q '^include' "$src" && continue
    name="$(basename "$src" .elisa)"
    "$ELISACORE_BIN" -emit ast "$src" </dev/null > "$WORK/$name.s0" 2>/dev/null || continue
    if ! bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit ast -o "$WORK/$name.s1" "$src" >/dev/null 2>&1; then
        echo "  FAIL $name: stage1 -emit ast failed"
        failed=$((failed + 1)); continue
    fi
    if cmp -s "$WORK/$name.s0" "$WORK/$name.s1"; then
        same=$((same + 1))
    else
        echo "  FAIL $name: ast summaries differ"
        diff "$WORK/$name.s0" "$WORK/$name.s1" | head -6 | sed 's/^/    /'
        failed=$((failed + 1))
    fi
done

if [ "$failed" -gt 0 ]; then
    echo "emit_ast parity FAILED: $failed of $((same + failed)) fixtures differ"
    exit 1
fi
echo "emit_ast parity OK: $same fixtures byte-identical to stage0"
