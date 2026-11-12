#!/usr/bin/env bash
# Check every Stage0-accepted fixture for exact fmt output parity.
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
failed=0
rejected=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    if s0 -emit fmt "$src" </dev/null > "$WORK/$name.s0" 2> "$WORK/$name.s0.err"; then
        :
    else
        status=$?
        if [ "$status" -gt 2 ]; then
            echo "  FAIL $src: Stage0 -emit fmt exited $status" >&2
            cat "$WORK/$name.s0.err" >&2
            failed=$((failed + 1))
        else
            echo "  UNCOMPARABLE $src: Stage0 rejected input (exit $status)" >&2
            rejected=$((rejected + 1))
        fi
        continue
    fi
    if ! s1 -emit fmt -o "$WORK/$name.s1" "$src" > /dev/null 2> "$WORK/$name.s1.err"; then
        echo "  FAIL $src: Stage1 -emit fmt failed" >&2
        cat "$WORK/$name.s1.err" >&2
        failed=$((failed + 1))
        continue
    fi
    if cmp -s "$WORK/$name.s0" "$WORK/$name.s1"; then
        same=$((same + 1))
    else
        echo "  FAIL $src: fmt output differs" >&2
        failed=$((failed + 1))
    fi
done

if [ "$((same + failed + rejected))" -eq 0 ]; then
    echo "emit_fmt parity FAILED: no fixtures found" >&2
    exit 1
fi
if [ "$failed" -ne 0 ]; then
    echo "emit_fmt parity FAILED: $same matched, $failed failed, $rejected Stage0-rejected"
    exit 1
fi
echo "emit_fmt parity OK: $same matched, $rejected Stage0-rejected"
