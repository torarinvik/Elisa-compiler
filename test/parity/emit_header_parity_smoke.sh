#!/usr/bin/env bash
# `-emit header` BYTE PARITY.
#
# The published header IS the C ABI contract, so a divergence here is not cosmetic: a
# by-value struct where the object takes a pointer, or `intptr_t` where the object uses
# `int64_t`, silently miscompiles every caller. This gate therefore demands EXACT equality
# on every fixture where stage0 produces a header at all — no ratchet.
#
# A file with no exports still produces the guard/extern-"C" skeleton, so most of the
# corpus participates; files stage0 rejects (or that need a type with no C ABI form) are
# skipped on BOTH sides, and stage1 is separately required not to emit where stage0 fails.
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
permissive=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    if ! "$ELISACORE_BIN" -emit header -o "$WORK/$name.s0" "$src" </dev/null >/dev/null 2>&1; then
        # stage0 declines. stage1 must decline too — publishing a header stage0 refuses to
        # write is exactly the "disagrees with the object ABI" failure this mode must not have.
        if bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit header -o "$WORK/$name.s1" "$src" >/dev/null 2>&1; then
            permissive=$((permissive + 1))
            echo "PERMISSIVE: $name — stage0 emits no header, stage1 does"
        fi
        skipped=$((skipped + 1))
        continue
    fi
    if ! bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit header -o "$WORK/$name.s1" "$src" >/dev/null 2>&1; then
        differ=$((differ + 1))
        echo "FAILED: $name — stage0 emitted a header, stage1 did not"
        continue
    fi
    if cmp -s "$WORK/$name.s0" "$WORK/$name.s1"; then
        same=$((same + 1))
    else
        differ=$((differ + 1))
        echo "DIFF: $name"
        diff "$WORK/$name.s0" "$WORK/$name.s1" | head -6
    fi
done

echo "emit_header parity: $same byte-identical, $differ divergent, $skipped skipped, $permissive permissive"
if [ "$differ" -ne 0 ] || [ "$permissive" -ne 0 ]; then
    echo "emit_header parity FAILED"
    exit 1
fi
echo "emit_header parity OK"
