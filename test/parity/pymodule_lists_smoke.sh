#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule lists smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/lists.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_lists.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import lists

assert lists.count([1, 2, 3]) == 3
assert lists.count(values=[1, 2, 3]) == 3
assert lists.count(()) == 0
try:
    lists.count(42)
except TypeError as exc:
    assert "Elisa function 'count' argument 'values':" in str(exc)
    assert exc.function == "count"
    assert exc.parameter == "values"
    assert exc.expected == "sequence"
    assert exc.path is None
else:
    raise AssertionError("non-sequence list input should fail with parameter context")
assert lists.count_i8([127, -128]) == 2
try:
    lists.count_i8([128])
except OverflowError:
    pass
else:
    raise AssertionError("narrow integer list overflow should fail")
assert lists.first([41, 42]) == 41
assert lists.first(values=[41, 42]) == 41
assert lists.echo_f64([1.25, 2.5]) == [1.25, 2.5]
assert lists.echo_f64([]) == []
assert lists.echo_i8([-128, 127]) == [-128, 127]
assert lists.echo_u16([0, 65535]) == [0, 65535]
assert lists.echo_bool([True, False, True]) == [True, False, True]
assert lists.echo_f32([1.25, 2.5]) == [1.25, 2.5]
assert lists.first_bool([True, False]) is True
assert lists.list_and_text([1, 2], "ok") == "ok"
assert lists.list_and_text(values=[1, 2], text="ok") == "ok"
value = {"kept": True}
assert lists.list_and_object([1, 2], value) is value
try:
    lists.count([1, object()])
except TypeError as exc:
    assert "Elisa function 'count' argument 'values' at path [1]:" in str(exc)
    assert exc.function == "count"
    assert exc.parameter == "values"
    assert exc.expected == "sequence"
    assert exc.path == "[1]"
else:
    raise AssertionError("invalid numeric list element should fail")
PY

echo "pymodule lists smoke OK"
