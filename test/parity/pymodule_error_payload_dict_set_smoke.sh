#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'mv "$WORK" "/tmp/pymodule_error_payload_dict_set_smoke.$$"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dictionary-of-sets error payload smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_error_payload_dict_set.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/error_payload_dict_set.json" "$SOURCE" >/dev/null
"$PYTHON_BIN" - "$WORK/error_payload_dict_set.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail"]["raises"] == "DictSetPayloadError"
assert functions["fail"]["payload"] == "dict[i64,set[i64]]"
assert functions["fail_structured"]["raises"] == "StructuredDictSetPayloadError"
assert functions["fail_structured"]["payload"] == "struct"
assert functions["fail_structured"]["payload_variants"] == [{
    "name": "Bad",
    "fields": [
        {"name": "code", "type": "i64"},
        {"name": "values", "type": "dict[i64,set[i64]]"},
    ],
}]
assert functions["fail_nested"]["raises"] == "NestedDictSetPayloadError"
assert functions["fail_nested"]["payload"] == "dict[i64,dict[cstr,set[i64]]]"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/error_payload_dict_set.pyi" "$SOURCE" >/dev/null
grep -Fq 'values: dict[int, set[int]]' "$WORK/error_payload_dict_set.pyi"
grep -Fq 'payload: dict[int, set[int]]' "$WORK/error_payload_dict_set.pyi"
grep -Fq 'payload: StructuredDictSetPayloadErrorPayload' "$WORK/error_payload_dict_set.pyi"
grep -Fq 'payload: dict[int, dict[str, set[int]]]' "$WORK/error_payload_dict_set.pyi"
grep -Fq 'def fail(values: Mapping[int, Iterable[int]]) -> int: ...' "$WORK/error_payload_dict_set.pyi"
grep -Fq 'def fail_structured(code: int, values: Mapping[int, Iterable[int]]) -> int: ...' "$WORK/error_payload_dict_set.pyi"
grep -Fq 'def fail_nested(values: Mapping[int, Mapping[str | bytes, Iterable[int]]]) -> int: ...' "$WORK/error_payload_dict_set.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_dict_set.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_dict_set.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_dict_set as module

values = {1: {2, 3}, 4: set()}
try:
    module.fail(values)
except module.DictSetPayloadError as exc:
    assert exc.payload == values
    assert exc.function == "fail"
else:
    raise AssertionError("dictionary-of-sets error payload should raise DictSetPayloadError")

try:
    module.fail_structured(17, values)
except module.StructuredDictSetPayloadError as exc:
    assert exc.payload == {
        "variant": "Bad",
        "code": 17,
        "values": values,
    }
else:
    raise AssertionError("structured dictionary-of-sets error payload should raise StructuredDictSetPayloadError")

nested_values = {1: {"a": {2, 3}, "b": set()}, 4: {}}
try:
    module.fail_nested(nested_values)
except module.NestedDictSetPayloadError as exc:
    assert exc.payload == nested_values
else:
    raise AssertionError("nested dictionary-of-sets error payload should raise NestedDictSetPayloadError")

# Nested set conversion intentionally accepts any iterable, matching standalone set parameters.
try:
    module.fail({1: [2, 3]})
except module.DictSetPayloadError as exc:
    assert exc.payload == {1: {2, 3}}
else:
    raise AssertionError("iterable dictionary-of-set payload should reach Elisa")

for bad in ({1: {2**70}}, {"bad": {1}}):
    try:
        module.fail(bad)
    except (OverflowError, TypeError, ValueError):
        pass
    else:
        raise AssertionError((type(bad).__name__, bad))

print("pymodule dictionary-of-sets error payload smoke OK")
PY
