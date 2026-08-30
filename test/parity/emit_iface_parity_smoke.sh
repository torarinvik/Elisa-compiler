#!/usr/bin/env bash
# `-emit iface` BYTE PARITY: the public-interface rendering must match stage0 byte for
# byte — defs as `extern` signatures with stage0's inferred `@__rg_*` region woven into
# growable ref param types (suppressed under explicit generics), globals as
# `extern NAME: T`, enum/error/struct bodies verbatim, decls in source order separated by
# blank lines. Token rendering is SOURCE-GAP based: a single space wherever the source
# had whitespace, which on canonical source IS stage0's normalized spelling.




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
    "$ELISACORE_BIN" -emit iface "$src" </dev/null > "$WORK/$name.s0" 2>/dev/null || continue
    if ! bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit iface -o "$WORK/$name.s1" "$src" >/dev/null 2>&1; then
        echo "  FAIL $name: stage1 -emit iface failed"
        failed=$((failed + 1)); continue
    fi
    if cmp -s "$WORK/$name.s0" "$WORK/$name.s1"; then
        same=$((same + 1))
    else
        echo "  FAIL $name: interface summaries differ"
        diff "$WORK/$name.s0" "$WORK/$name.s1" | head -6 | sed 's/^/    /'
        failed=$((failed + 1))
    fi
done

if [ "$failed" -gt 0 ]; then
    echo "emit_iface parity FAILED: $failed of $((same + failed)) fixtures differ"
    exit 1
fi
echo "emit_iface parity OK: $same fixtures byte-identical to stage0"
