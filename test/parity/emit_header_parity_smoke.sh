#!/usr/bin/env bash
# `-emit header` BYTE PARITY.
#
# The published header IS the C ABI contract, so a divergence here is not cosmetic: a
# by-value struct where the object takes a pointer, or `intptr_t` where the object uses
# `int64_t`, silently miscompiles every caller. This gate therefore demands EXACT equality
# on every fixture where stage0 produces a header at all — no ratchet.
#
# A file with no exports still produces the guard/extern-"C" skeleton, so most of the
# corpus participates. Stage1 is a deliberate superset while the self-hosted compiler
# grows: when stage0 declines a source, an empty stage1 skeleton is harmless and carries
# no ABI claim, but a declaration-bearing stage1 header remains a parity failure.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
differ=0
skipped=0
permissive=0

header_is_empty_skeleton() {
    # Remove only the boilerplate emitted by the header backend. Anything left over is a
    # declaration or an unexpected comment/directive and must not be accepted silently.
    local remainder
    remainder="$(sed -E '/^[[:space:]]*(#.*|extern "C" \{|\})[[:space:]]*$/d' "$1")"
    [ -z "$remainder" ]
}

for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    if ! "$ELISACORE_BIN" -emit header -o "$WORK/$name.s0" "$src" </dev/null >/dev/null 2>&1; then
        # stage0 declines. A declaration-free stage1 skeleton has no ABI surface and is safe;
        # any declaration here would publish an interface that stage0 refused to validate.
        if bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit header -o "$WORK/$name.s1" "$src" >/dev/null 2>&1; then
            if header_is_empty_skeleton "$WORK/$name.s1"; then
                permissive=$((permissive + 1))
                echo "SAFE SUPERSET: $name — stage1 emitted an empty header skeleton"
            else
                differ=$((differ + 1))
                echo "FAILED: $name — stage1 emitted declarations after stage0 declined"
            fi
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

echo "emit_header parity: $same byte-identical, $differ divergent, $skipped skipped, $permissive safe stage1-only skeletons"
if [ "$differ" -ne 0 ]; then
    echo "emit_header parity FAILED"
    exit 1
fi
echo "emit_header parity OK"
