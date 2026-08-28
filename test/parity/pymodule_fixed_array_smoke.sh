#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -x "$ROOT/bin/elisac-stage1" ]]; then
    echo "pymodule fixed-array smoke SKIP (Python 3.14/Homebrew clang/stage1 unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/fixed_array_refs.json" \
    "$ROOT/test/repro/pymodule_fixed_array_refs.elisa" >/dev/null
grep -Fq '"type": "array[i64,3]"' "$WORK/fixed_array_refs.json"
grep -Fq '"name": "sum_fixed_postfix"' "$WORK/fixed_array_refs.json"
grep -Fq '"name": "sum_fixed_value"' "$WORK/fixed_array_refs.json"
grep -Fq '"name": "sum_darray_ref"' "$WORK/fixed_array_refs.json"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/fixed_array_refs.c" \
    "$ROOT/test/repro/pymodule_fixed_array_refs.elisa" >/dev/null
grep -Fq 'extern int64_t elisa_pymodule_fixed_array_refs_sum_fixed(int64_t *);' "$WORK/fixed_array_refs.c"
grep -Fq 'extern int64_t elisa_pymodule_fixed_array_refs_sum_fixed_value(int64_t *);' "$WORK/fixed_array_refs.c"
grep -Fq 'extern int64_t elisa_pymodule_fixed_array_refs_sum_darray_ref(ElisaDArray *, ElisaArena *);' "$WORK/fixed_array_refs.c"
# Borrowed darray inputs allocate a temporary element buffer with PyMem_Malloc.  Keep the
# cleanup visible in generated C so a ref-wrapped type cannot regress into a per-call leak.
grep -Fq 'Py_XDECREF(arg0_seq);' "$WORK/fixed_array_refs.c"
grep -Fq 'PyMem_Free(arg0_items);' "$WORK/fixed_array_refs.c"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/fixed_array_refs.pyi" \
    "$ROOT/test/repro/pymodule_fixed_array_refs.elisa" >/dev/null
grep -Fq 'def sum_fixed(xs: Sequence[int]) -> int: ...' "$WORK/fixed_array_refs.pyi"
grep -Fq 'def sum_fixed_value(xs: Sequence[int]) -> int: ...' "$WORK/fixed_array_refs.pyi"
grep -Fq 'def sum_darray_ref(xs: Sequence[int]) -> int: ...' "$WORK/fixed_array_refs.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/fixed_array_refs.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/fixed_array_refs.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_fixed_array_refs.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import fixed_array_refs

assert fixed_array_refs.sum_fixed([1, 2, 3]) == 6
assert fixed_array_refs.sum_fixed_postfix([1, 2, 3]) == 6
assert fixed_array_refs.sum_fixed_value([1, 2, 3]) == 6
assert fixed_array_refs.sum_darray_ref([1, 2, 3]) == 6
assert fixed_array_refs.sum_fixed((4, 5, 6)) == 15
assert fixed_array_refs.sum_fixed(range(7, 10)) == 24

try:
    fixed_array_refs.sum_fixed([1, 2])
except ValueError as exc:
    assert "expected fixed array of length 3" in str(exc)
    assert exc.function == "sum_fixed"
    assert exc.parameter == "xs"
else:
    raise AssertionError("wrong fixed-array length should fail")

try:
    fixed_array_refs.sum_fixed([1, object(), 3])
except TypeError as exc:
    assert exc.function == "sum_fixed"
    assert exc.parameter == "xs"
else:
    raise AssertionError("bad fixed-array element should fail")
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/fixed_array_returns.json" \
    "$ROOT/test/repro/pymodule_fixed_array_returns.elisa" >/dev/null
grep -Fq '"return": "array[i64,3]"' "$WORK/fixed_array_returns.json"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/fixed_array_returns.c" \
    "$ROOT/test/repro/pymodule_fixed_array_returns.elisa" >/dev/null
grep -Fq 'extern void elisa_pymodule_fixed_array_returns_make_fixed(int64_t *out);' "$WORK/fixed_array_returns.c"
grep -Fq 'extern void elisa_pymodule_fixed_array_returns_make_fixed_from(int64_t *out, int64_t);' "$WORK/fixed_array_returns.c"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/fixed_array_returns.pyi" \
    "$ROOT/test/repro/pymodule_fixed_array_returns.elisa" >/dev/null
grep -Fq 'def make_fixed() -> list[int]: ...' "$WORK/fixed_array_returns.pyi"
grep -Fq 'def make_fixed_from(seed: int) -> list[int]: ...' "$WORK/fixed_array_returns.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/fixed_array_returns.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/fixed_array_returns.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_fixed_array_returns.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import fixed_array_returns

assert fixed_array_returns.make_fixed() == [10, 20, 30]
assert fixed_array_returns.make_fixed_from(7) == [7, 8, 9]
PY

echo "pymodule fixed-array smoke OK"
