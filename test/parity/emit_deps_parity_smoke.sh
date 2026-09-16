#!/usr/bin/env bash
# `-emit deps` / `-emit deps-json` BYTE PARITY: the resolved include closure (root first,
# pre-order, deduped, absolute paths) must match stage0's exactly — including on the
# compiler's own 111-file include graph, where a traversal-order or dedup difference
# would scramble the list.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

failed=0
same=0
for src in "$REPO_ROOT/test/breadth/easm_lockstep_parse_smoke.elisa" "$REPO_ROOT"/test/repro/*.elisa; do
    name="$(basename "$src" .elisa)"
    for mode in deps deps-json; do
        "$ELISACORE_BIN" -emit "$mode" "$src" </dev/null > "$WORK/$name.$mode.s0" 2>/dev/null || continue
        if ! bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit "$mode" -o "$WORK/$name.$mode.s1" "$src" >/dev/null 2>&1; then
            echo "  FAIL $name ($mode): stage1 failed"; failed=$((failed + 1)); continue
        fi
        if cmp -s "$WORK/$name.$mode.s0" "$WORK/$name.$mode.s1"; then
            same=$((same + 1))
        else
            echo "  FAIL $name ($mode): closures differ"
            diff "$WORK/$name.$mode.s0" "$WORK/$name.$mode.s1" | head -4 | sed 's/^/    /'
            failed=$((failed + 1))
        fi
    done
done

if [ "$failed" -gt 0 ]; then
    echo "emit_deps parity FAILED: $failed cases differ"
    exit 1
fi
echo "emit_deps parity OK: $same cases byte-identical to stage0"
