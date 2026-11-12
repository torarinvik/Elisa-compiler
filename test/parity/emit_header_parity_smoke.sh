#!/usr/bin/env bash
# `-emit header` BYTE PARITY.
#
# The published header IS the C ABI contract, so a divergence here is not cosmetic: a
# by-value struct where the object takes a pointer, or `intptr_t` where the object uses
# `int64_t`, silently miscompiles every caller. This gate therefore demands EXACT equality
# on every fixture where stage0 produces a header at all — no ratchet.
#
# A Stage1-only empty skeleton is still an acceptance disagreement. Distinguish it from
# declarations in the report, but require both compilers to agree.
set -uo pipefail
shopt -s nullglob

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/emit_parity_lib.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
differ=0
rejected=0

header_is_empty_skeleton() {
    # Remove only the boilerplate emitted by the header backend. Anything left over is a
    # declaration or an unexpected comment/directive and must not be accepted silently.
    local remainder
    remainder="$(sed -E '/^[[:space:]]*(#.*|extern "C" \{|\})[[:space:]]*$/d' "$1")"
    [ -z "$remainder" ]
}

for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    if s0 -emit header -o "$WORK/$name.s0" "$src" </dev/null >/dev/null 2> "$WORK/$name.s0.err"; then
        :
    else
        status=$?
        if [ "$status" -gt 2 ]; then
            differ=$((differ + 1))
            echo "FAILED: $name — Stage0 header emission exited $status"
            cat "$WORK/$name.s0.err" >&2
            continue
        fi
        if s1 -emit header -o "$WORK/$name.s1" "$src" >/dev/null 2> "$WORK/$name.s1.err"; then
            differ=$((differ + 1))
            if header_is_empty_skeleton "$WORK/$name.s1"; then
                echo "FAILED: $name — Stage1 emitted an empty header after Stage0 rejected input"
            else
                echo "FAILED: $name — Stage1 emitted declarations after Stage0 rejected input"
            fi
        else
            stage1_status=$?
            if [ "$stage1_status" -gt 2 ]; then
                differ=$((differ + 1))
                echo "FAILED: $name — Stage1 header emission exited $stage1_status"
                cat "$WORK/$name.s1.err" >&2
            else
                rejected=$((rejected + 1))
                echo "UNCOMPARABLE: $name — both compilers rejected input"
            fi
        fi
        continue
    fi
    if ! s1 -emit header -o "$WORK/$name.s1" "$src" >/dev/null 2>&1; then
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

echo "emit_header parity: $same byte-identical, $differ divergent, $rejected rejected by both"
if [ "$((same + differ))" -eq 0 ]; then
    echo "emit_header parity FAILED: no comparable fixtures"
    exit 1
fi
if [ "$differ" -ne 0 ]; then
    echo "emit_header parity FAILED"
    exit 1
fi
echo "emit_header parity OK"
