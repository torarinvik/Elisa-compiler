#!/usr/bin/env bash
# Require exact lowered-output parity for every Stage0-accepted fixture.
set -uo pipefail
shopt -s nullglob

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/emit_parity_lib.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

# `lowered` also uses the formatting-only parser option and must retain the exact grouping node.
cat > "$WORK/parenthesized.elisa" <<'CASE'
def f() -> i32:
    return (1)
CASE
s0 -emit lowered "$WORK/parenthesized.elisa" </dev/null > "$WORK/parenthesized.s0" 2>/dev/null || {
    echo "emit_lowered parity FAILED: stage0 parenthesis fixture"
    exit 1
}
s1 -emit lowered -o "$WORK/parenthesized.s1" "$WORK/parenthesized.elisa" >/dev/null 2>&1 || {
    echo "emit_lowered parity FAILED: stage1 parenthesis fixture"
    exit 1
}
cmp -s "$WORK/parenthesized.s0" "$WORK/parenthesized.s1" || {
    echo "emit_lowered parity FAILED: parenthesized output differs"
    exit 1
}
rg -Fq 'return (1)' "$WORK/parenthesized.s1" || {
    echo "emit_lowered parity FAILED: grouping node was not preserved"
    exit 1
}

same=0
failed=0
rejected=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    if s0 -emit lowered "$src" </dev/null > "$WORK/$name.s0" 2> "$WORK/$name.s0.err"; then
        :
    else
        status=$?
        if [ "$status" -gt 2 ]; then
            echo "  FAIL $src: Stage0 -emit lowered exited $status" >&2
            cat "$WORK/$name.s0.err" >&2
            failed=$((failed + 1))
        else
            echo "  UNCOMPARABLE $src: Stage0 rejected input (exit $status)" >&2
            rejected=$((rejected + 1))
        fi
        continue
    fi
    if ! s1 -emit lowered -o "$WORK/$name.s1" "$src" > /dev/null 2> "$WORK/$name.s1.err"; then
        echo "  FAIL $src: Stage1 -emit lowered failed" >&2
        cat "$WORK/$name.s1.err" >&2
        failed=$((failed + 1))
        continue
    fi
    if cmp -s "$WORK/$name.s0" "$WORK/$name.s1"; then
        same=$((same + 1))
    else
        echo "  FAIL $src: lowered output differs" >&2
        failed=$((failed + 1))
    fi
done

if [ "$((same + failed + rejected))" -eq 0 ]; then
    echo "emit_lowered parity FAILED: no fixtures found" >&2
    exit 1
fi
if [ "$((same + failed))" -eq 0 ]; then
    echo "emit_lowered parity FAILED: no fixtures were comparable" >&2
    exit 1
fi
if [ "$failed" -ne 0 ]; then
    echo "emit_lowered parity FAILED: $same matched, $failed failed, $rejected Stage0-rejected"
    exit 1
fi
echo "emit_lowered parity OK: $same matched, $rejected Stage0-rejected"
