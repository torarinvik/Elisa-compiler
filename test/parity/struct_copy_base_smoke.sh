#!/usr/bin/env bash
# Copy-update struct literal `T{..base, field: value}` (docs/119 §copy-update). The parser
# expands it into an ordinary full literal (src/parser/parser_struct_copy_base.elisa);
# semantic checks the base's type (src/semantic/check_struct_copy_base.elisa).
#   1. runtime fixtures compile, link, and exit 42 (values, base unchanged, darray/sview
#      fields, `T{..b}`, field-path base, forward-declared struct, module-qualified and
#      generic structs, reference-parameter base);
#   2. every malformed or ill-typed form is refused with its own message;
#   3. `-emit fmt` prints what was written (the unexpanded `..base`).
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
FIXTURES="$ROOT/test/fixtures/struct_copy_base"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-struct-copy-base.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fail() { echo "struct copy base smoke FAIL: $1" >&2; exit 1; }

for name in runtime qualified_generic; do
    "$ROOT/scripts/elisac_stage1.sh" -emit exe -o "$WORK/$name" "$FIXTURES/$name.elisa" >"$WORK/$name.log" 2>&1 \
        || fail "$name did not compile: $(cat "$WORK/$name.log")"
    "$WORK/$name"
    status=$?
    [[ "$status" -eq 42 ]] || fail "$name exited $status, expected 42"
done

expect_error() {
    local name="$1" message="$2"
    local out
    out=$("$ROOT/scripts/elisac_stage1.sh" -emit obj -o "$WORK/$name.o" "$FIXTURES/$name.neg.elisa" 2>&1) \
        && fail "$name compiled; expected: $message"
    grep -qF -- "$message" <<< "$out" || fail "$name: missing \"$message\" in: $out"
}
expect_error not_first 'struct literal copy source `..base` must be the first entry'
expect_error more_than_one 'struct literal may have at most one `..base` copy source'
expect_error base_call 'struct literal copy source `..base` must be an identifier or field path (`a.b.c`); bind other expressions to a local first'
expect_error base_index 'struct literal copy source `..base` must be an identifier or field path'
expect_error unknown_field 'struct literal "P" has no field "z"'
expect_error duplicate_field 'struct literal "P" field "x" is specified more than once'
expect_error base_type 'struct literal "P" copy source `..base` must have type P, got Q'
expect_error missing_struct 'struct literal copy source `..base` needs the struct'"'"'s declaration'

fmt=$("$ROOT/scripts/elisac_stage1.sh" -emit fmt "$FIXTURES/runtime.elisa" 2>&1) || fail "fmt failed: $fmt"
grep -qF 'Outer{..base, x: 10}' <<< "$fmt" || fail "fmt lost the copy-update form: $fmt"
grep -qF 'Inner{..base.inner, tag: 99}' <<< "$fmt" || fail "fmt lost the field-path base: $fmt"

echo "struct copy base smoke OK: copy-update literals expand, run, and refuse every malformed form"
