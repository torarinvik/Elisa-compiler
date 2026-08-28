#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nested darray error payload smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/error_payload_nested_darray.json" \
    "$ROOT/test/repro/pymodule_error_payload_nested_darray.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/error_payload_nested_darray.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail_nested"]["raises"] == "NestedListPayloadError"
assert functions["fail_nested"]["payload"] == "darray[darray[i64]]"
assert functions["fail_structured"]["raises"] == "StructuredNestedListPayloadError"
assert functions["fail_structured"]["payload"] == "struct"
assert functions["fail_deep"]["raises"] == "DeepNestedListPayloadError"
assert functions["fail_deep"]["payload"] == "darray[darray[darray[i64]]]"
assert functions["fail_list_sets"]["raises"] == "ListSetsPayloadError"
assert functions["fail_list_sets"]["payload"] == "darray[set[i64]]"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_nested_darray.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_payload_nested_darray.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_nested_darray

values = [[1, 2], [], [3, -4, 5]]
try:
    error_payload_nested_darray.fail_nested(values)
except error_payload_nested_darray.ElisaError as exc:
    assert exc.function == "fail_nested"
    assert exc.payload == values
else:
    raise AssertionError("nested darray error payload should raise ElisaError")

try:
    error_payload_nested_darray.fail_structured(values, "row data")
except error_payload_nested_darray.ElisaError as exc:
    assert exc.payload == {"variant": "Empty", "items": values, "label": "row data"}
else:
    raise AssertionError("structured nested darray error payload should raise ElisaError")

deep_values = [[[1, 2], []], [], [[3, -4, 5]]]
try:
    error_payload_nested_darray.fail_deep(deep_values)
except error_payload_nested_darray.ElisaError as exc:
    assert exc.payload == deep_values
else:
    raise AssertionError("deep nested darray error payload should raise ElisaError")

set_values = [{1, 2}, frozenset(), [3, 4]]
try:
    error_payload_nested_darray.fail_list_sets(set_values)
except error_payload_nested_darray.ElisaError as exc:
    assert exc.payload == [{1, 2}, set(), {3, 4}]
else:
    raise AssertionError("list-of-sets error payload should raise ElisaError")

try:
    error_payload_nested_darray.fail_nested([[2**80]])
except OverflowError:
    pass
else:
    raise AssertionError("nested darray payload should preserve integer range checks")

try:
    error_payload_nested_darray.fail_list_sets([{2**80}])
except OverflowError:
    pass
else:
    raise AssertionError("list-of-sets payload should preserve integer range checks")
PY

echo "pymodule nested darray error payload smoke OK"
