#!/usr/bin/env bash
# Type compatibility checks on variable declarations and assignments.
# Tests that:
# 1. `x: T = v` where v's type is incompatible with T is flagged as TypeMismatch
# 2. `x <- v` where v's type is incompatible with binding's type is flagged
# 3. `return v` where v's type is incompatible with declared return type is flagged
# 4. `s.f <- v` where v's type is incompatible with field's type is flagged
# All checks are conservative: only when BOTH types are firm/known. No false positives.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "assign-type smoke FAIL: $1" >&2; exit 1; }

# 1. VarDecl with bool expecting literal int MUST flag TypeMismatch.
out=$(printf 'def f() -> void:\n    x: bool = 5\n' | "$RPT")
# The semantic oracle spells an unsuffixed integer literal `int`; older products rendered the
# same firm scalar as `i64`. Accept both spellings—the invariant is the bool-vs-integer mismatch,
# not the diagnostic alias chosen by the current type renderer.
grep -qE "expects bool, got (i64|int)" <<< "$out" || fail "VarDecl literal mismatch not flagged: $out"

# 2. VarDecl with i64 expecting literal bool MUST flag TypeMismatch.
out=$(printf 'def f() -> void:\n    y: i64 = true\n' | "$RPT")
grep -q "expects i64, got bool" <<< "$out" || fail "VarDecl bool->int not flagged: $out"

# 3. VarDecl with matching types must NOT flag.
out=$(printf 'def f() -> void:\n    z: i64 = 5\n' | "$RPT")
grep -q "expects i64" <<< "$out" && fail "false positive on matching VarDecl: $out"

# 4. Assignment rebind with <- and type mismatch MUST flag.
# stage0's sentence for a local `<-` (MEASURED: `3:5-6: cannot assign int to bool`).
out=$(printf 'def f() -> void:\n    a: mutable bool = false\n    a <- 10\n' | "$RPT")
grep -q "cannot assign int to bool" <<< "$out" || fail "Assign <- mismatch not flagged: $out"

# 5. Assignment rebind with matching type must NOT flag.
out=$(printf 'def f() -> void:\n    b: mutable i64 = 0\n    b <- 10\n' | "$RPT")
grep -qE "expects i64|cannot assign" <<< "$out" && fail "false positive on matching Assign <-: $out"

# A void call cannot satisfy a value-returning function's return type.
out=$(printf 'def helper() -> void:\n    return\ndef f() -> i64:\n    return helper()\n' | "$RPT")
grep -q "return type expects i64, got void" <<< "$out" || fail "void call return mismatch not flagged: $out"

# An unannotated empty array binding has no element-type context.
out=$(printf 'def f() -> void:\n    values = []\n' | "$RPT")
grep -q "empty list literal requires an expected array or darray type" <<< "$out" || fail "context-free empty array not flagged: $out"
out=$(printf 'def f() -> void:\n    values: darray[i64] = []\n' | "$RPT")
grep -q "empty list literal requires" <<< "$out" && fail "typed empty array false positive: $out"

# 6. Return value type mismatch MUST flag.
out=$(printf 'def f() -> i64:\n    return true\n' | "$RPT")
grep -q "return type expects i64, got bool" <<< "$out" || fail "Return mismatch not flagged: $out"

# 7. Return bool->bool must NOT flag.
out=$(printf 'def f() -> bool:\n    return true\n' | "$RPT")
grep -q "return type expects bool" <<< "$out" && fail "false positive on matching Return: $out"

# 8. Field assignment type mismatch MUST flag.
out=$(printf 'struct S:\n    x: mutable bool\ndef f() -> void:\n    s: mutable S = S{}\n    s.x <- 5\n' | "$RPT")
grep -qE "(cannot assign (i64|int) to bool|expects bool, got (i64|int))" <<< "$out" || fail "Field assign mismatch not flagged: $out"

# 9. Structural generic-container mismatch MUST flag (darray <- dict).
out=$(printf 'def f() -> void:\n    a: mutable darray[i64] = []\n    b: dict[cstr, i64] = {}\n    a <- b\n' | "$RPT")
grep -q "expects darray, got dict" <<< "$out" || fail "generic container mismatch not flagged: $out"

# 10. A by-reference darray parameter must be compared by its referent element type.
# Both outer types lower as references in the function body, but darray[i64]& cannot be
# passed to a function that reads/writes the same buffer as darray[sview]&.
MISMATCH_FIXTURE="$REPO_ROOT/test/fixtures/diagnostics/darray_ref_call_element_mismatch.pos.elisa"
out=$("$RPT" < "$MISMATCH_FIXTURE")
grep -q 'argument 1 to "take_texts" expects darray\[sview\], got darray\[i64\]' <<< "$out" || fail "by-reference darray element mismatch not flagged: $out"
if "$STAGE1_BIN" -emit obj -O0 -o /dev/null "$MISMATCH_FIXTURE" > /dev/null 2>&1; then
  fail "stage1 accepted by-reference darray element mismatch"
fi
if stage0_out=$("$ELISACORE_BIN" -emit obj -O0 -o /dev/null "$MISMATCH_FIXTURE" 2>&1); then
  fail "stage0 accepted by-reference darray element mismatch"
fi
grep -q 'expects darray\[sview\].*darray\[i64\]' <<< "$stage0_out" || fail "stage0 rejected mismatch for an unexpected reason: $stage0_out"

# Matching by-reference element types remain accepted.
out=$(printf 'def take_texts(values: darray[sview]&) -> void:\n    pass\ndef good_call(values: darray[sview]&):\n    take_texts(values)\n' | "$RPT")
grep -q 'expects darray\[sview\]' <<< "$out" && fail "false positive on matching by-reference darray element types: $out"

# Formal resolution must follow argument labels, not source argument indices. Reordered
# named arguments that match their formal darray element types are accepted; a swapped pair
# must report both actual/formal mismatches.
out=$("$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_named_reorder.pos.elisa")
grep -q 'expects darray\[' <<< "$out" && fail "false positive on matching reordered named darray arguments: $out"
"$ELISACORE_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_named_reorder.pos.elisa" >/dev/null 2>&1 || fail "stage0 rejected matching reordered named darray arguments"
"$STAGE1_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_named_reorder.pos.elisa" >/dev/null 2>&1 || fail "stage1 rejected matching reordered named darray arguments"
out=$("$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_named_mismatch.neg.elisa")
grep -q 'expects darray\[sview\], got darray\[i64\]' <<< "$out" || fail "named darray mismatch not mapped to its formal: $out"
grep -q 'expects darray\[i64\], got darray\[sview\]' <<< "$out" || fail "reordered named darray mismatch not mapped to its formal: $out"
named_mismatch_count=$(grep -c 'expects darray\[' <<< "$out" || true)
[ "$named_mismatch_count" -eq 2 ] || fail "named argument matching emitted unexpected darray findings: $out"
if stage0_out=$("$ELISACORE_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_named_mismatch.neg.elisa" 2>&1); then
  fail "stage0 accepted mismatched named darray arguments"
fi
grep -q 'expects darray\[sview\].*darray\[i64\]' <<< "$stage0_out" || fail "stage0 rejected named darray mismatch for another reason: $stage0_out"
if stage1_out=$("$STAGE1_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_named_mismatch.neg.elisa" 2>&1); then
  fail "stage1 accepted mismatched named darray arguments"
fi
grep -q 'expects darray\[sview\].*darray\[i64\]' <<< "$stage1_out" || fail "stage1 rejected named darray mismatch for another reason: $stage1_out"

# A local non-function that shadows a top-level callable is not that function's actual
# callee. The independent callability diagnostic may reject it, but this check must not
# borrow the global declaration's darray signature and add a misleading type finding.
out=$("$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_shadowed_callee.invalid.elisa")
grep -q 'expects darray\[' <<< "$out" && fail "shadowed local callee was checked against a global function signature: $out"

# Module qualification must select the exact declaration even where two modules declare
# the same bare function name with different darray formals. Both a matching qualified call
# and a mismatching qualified call appear in this source; only the latter may be diagnosed.
out=$("$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_qualified_same_name.neg.elisa")
grep -q 'expects darray\[sview\], got darray\[i64\]' <<< "$out" || fail "qualified North::store mismatch not found: $out"
grep -q 'expects darray\[i64\], got darray\[sview\]' <<< "$out" || fail "qualified South::store mismatch not found: $out"
qualified_mismatch_count=$(grep -c 'expects darray\[' <<< "$out" || true)
[ "$qualified_mismatch_count" -eq 2 ] || fail "qualified resolution or ambiguous bare-name fail-closed control produced unexpected darray findings: $out"
if stage0_out=$("$ELISACORE_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_qualified_same_name.neg.elisa" 2>&1); then
  fail "stage0 accepted mismatched same-name qualified module calls"
fi
qualified_stage0_count=$(grep -c 'expects darray\[' <<< "$stage0_out" || true)
[ "$qualified_stage0_count" -eq 2 ] || fail "stage0 qualified module controls produced unexpected errors: $stage0_out"
if stage1_out=$("$STAGE1_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_qualified_same_name.neg.elisa" 2>&1); then
  fail "stage1 accepted mismatched same-name qualified module calls"
fi
qualified_stage1_count=$(grep -c 'expects darray\[' <<< "$stage1_out" || true)
[ "$qualified_stage1_count" -eq 2 ] || fail "stage1 qualified module controls produced unexpected errors: $stage1_out"
"$ELISACORE_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_qualified_same_name.pos.elisa" >/dev/null 2>&1 || fail "stage0 rejected matching same-name qualified module calls"
"$STAGE1_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_qualified_same_name.pos.elisa" >/dev/null 2>&1 || fail "stage1 rejected matching same-name qualified module calls"

# The parser canonicalizes nested module declarations as fully qualified owner paths
# (Outer::Inner). The collector and call checker must use the same path without rebuilding
# or truncating it. Matching calls pass; the two payload-layout mismatches are diagnosed.
out=$("$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_nested_module.neg.elisa")
grep -q 'expects darray\[sview\], got darray\[i64\]' <<< "$out" || fail "nested module darray mismatch not found: $out"
grep -q 'expects darray\[i64\], got darray\[sview\]' <<< "$out" || fail "nested module darray mismatch not found: $out"
nested_module_mismatch_count=$(grep -c 'expects darray\[' <<< "$out" || true)
[ "$nested_module_mismatch_count" -eq 2 ] || fail "nested module controls produced unexpected darray findings: $out"
for compiler in "$ELISACORE_BIN" "$STAGE1_BIN"; do
  if nested_out=$("$compiler" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_nested_module.neg.elisa" 2>&1); then
    fail "$(basename "$compiler") accepted nested-module darray element mismatches"
  fi
  nested_compiler_count=$(grep -c 'expects darray\[' <<< "$nested_out" || true)
  [ "$nested_compiler_count" -eq 2 ] || fail "$(basename "$compiler") nested module controls produced unexpected errors: $nested_out"
done

# Reference normalization peels nested reference wrappers but still compares the underlying
# buffer element layout. The positive file has identical nested-ref element types; the
# negative file differs only in the darray element type.
out=$("$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_nested_match.pos.elisa")
grep -q 'expects darray\[' <<< "$out" && fail "false positive on matching nested-reference darray types: $out"
"$ELISACORE_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_nested_match.pos.elisa" >/dev/null 2>&1 || fail "stage0 rejected matching nested-reference darray types"
"$STAGE1_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_nested_match.pos.elisa" >/dev/null 2>&1 || fail "stage1 rejected matching nested-reference darray types"
out=$("$RPT" < "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_nested_mismatch.neg.elisa")
grep -q 'expects darray\[sview\], got darray\[i64\]' <<< "$out" || fail "nested-reference element mismatch not found: $out"
if stage0_out=$("$ELISACORE_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_nested_mismatch.neg.elisa" 2>&1); then
  fail "stage0 accepted nested-reference darray element mismatch"
fi
grep -q 'expects darray\[sview\].*darray\[i64\]' <<< "$stage0_out" || fail "stage0 rejected nested-ref mismatch for another reason: $stage0_out"
if stage1_out=$("$STAGE1_BIN" -emit obj -O0 -o /dev/null "$REPO_ROOT/test/fixtures/diagnostics/darray_ref_nested_mismatch.neg.elisa" 2>&1); then
  fail "stage1 accepted nested-reference darray element mismatch"
fi
grep -q 'expects darray\[sview\].*darray\[i64\]' <<< "$stage1_out" || fail "stage1 rejected nested-ref mismatch for another reason: $stage1_out"

# 11. 0 findings across frontend + stdlib (self-contained resolution set).
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE " expects .*, got | cannot assign .* to " || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t type-mismatch false positives across frontend+stdlib"

echo "assign-type smoke OK: VarDecl/Assign/<-/return/field all type-checked, conservative (firm types only), 0 FP across frontend+stdlib"
