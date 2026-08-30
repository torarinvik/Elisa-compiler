#!/usr/bin/env bash
# `-emit tokens` BYTE PARITY: stage1's lexer-oracle report must be byte-identical to
# stage0's for every include-free repro fixture — same JSON shape, same stage0 kind
# ordinals and names (generated from lexer/token.go's tokenNames), same FNV-1a checksum,
# same Go-encoder HTML escaping (`->` renders as "->"). Include-free only: stage0
# expands includes itself while the wrapper expands for stage1, and the two expansions
# need not agree byte-for-byte about anything but the tokens of a single file.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
failed=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/lexer/machine_state_edge_cases.elisa; do
    grep -q '^include' "$src" && continue
    name="$(basename "$src" .elisa)"
    "$ELISACORE_BIN" -emit tokens "$src" </dev/null > "$WORK/$name.s0" 2>/dev/null || continue
    if ! bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit tokens -o "$WORK/$name.s1" "$src" >/dev/null 2>&1; then
        echo "  FAIL $name: stage1 -emit tokens failed"
        failed=$((failed + 1)); continue
    fi
    if cmp -s "$WORK/$name.s0" "$WORK/$name.s1"; then
        same=$((same + 1))
    else
        echo "  FAIL $name: token reports differ"
        diff "$WORK/$name.s0" "$WORK/$name.s1" | head -6 | sed 's/^/    /'
        failed=$((failed + 1))
    fi
done

if [ "$failed" -gt 0 ]; then
    echo "emit_tokens parity FAILED: $failed of $((same + failed)) fixtures differ"
    exit 1
fi
echo "emit_tokens parity OK: $same fixtures byte-identical to stage0"
