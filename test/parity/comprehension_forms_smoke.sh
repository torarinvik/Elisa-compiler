#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Comprehension forms (STYLE_GUIDE.md §5; src/backend/codegen_comprehension*.elisa):
#
#   test/fixtures/comprehensions/nested.elisa    nested clauses with filters between them
#   test/fixtures/comprehensions/tuples.elisa    unlabeled tuple elements (`_0`, `_1`)
#   test/fixtures/comprehensions/dict_set.elisa  dict and set comprehensions, nested too
#   test/fixtures/comprehensions/reserve.elisa   an unfiltered darray source reserves its count
#
# Each program checks its own results: stage1 builds it at -O0 and -O2 and it must exit 0.
# stage1 only: stage0 has no nested comprehension.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
FIXTURES="$ROOT/test/fixtures/comprehensions"
fail() { printf 'comprehension forms smoke FAILED: %s\n' "$1" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-comprehensions.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

programs=0
for source in "$FIXTURES"/*.elisa; do
    base="$(basename "$source" .elisa)"
    for level in -O0 -O2; do
        bash "$WRAPPER" "$level" -emit exe -o "$WORK/$base" "$source" >"$WORK/$base.log" 2>&1 || fail "stage1 $level cannot build $base: $(cat "$WORK/$base.log")"
        set +e
        "$WORK/$base"
        status=$?
        set -e
        [[ "$status" -eq 0 ]] || fail "$base ($level) exited $status"
    done
    programs=$((programs + 1))
done
[[ "$programs" -ge 4 ]] || fail "expected at least 4 programs, found $programs"
echo "comprehension forms smoke OK: $programs programs at -O0 and -O2"
