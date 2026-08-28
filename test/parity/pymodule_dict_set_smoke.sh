#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
SOURCE="$ROOT/test/repro/pymodule_dict_set_probe.elisa"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dict-set smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["roundtrip"]["parameters"] == [{"name": "values", "type": "dict[i64,set[i64]]"}]
assert functions["roundtrip"]["return"] == "dict[i64,set[i64]]"
assert functions["roundtrip_text"]["parameters"] == [{"name": "values", "type": "dict[cstr,set[sview]]"}]
assert functions["roundtrip_text"]["return"] == "dict[cstr,set[sview]]"
assert functions["roundtrip_nested"]["parameters"] == [{"name": "values", "type": "dict[i64,dict[i64,set[i64]]]"}]
assert functions["roundtrip_nested"]["return"] == "dict[i64,dict[i64,set[i64]]]"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/dict_set_probe.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip(values: Mapping[int, Iterable[int]]) -> dict[int, set[int]]: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def roundtrip_text(values: Mapping[str | bytes, Iterable[str | bytes]]) -> dict[str, set[str]]: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def roundtrip_nested(values: Mapping[int, Mapping[int, Iterable[int]]]) -> dict[int, dict[int, set[int]]]: ...' "$WORK/dict_set_probe.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/dict_set_probe.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dict_set_probe.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import dict_set_probe

value = {1: {2, 3}, 4: set()}
assert dict_set_probe.roundtrip(value) == value
assert dict_set_probe.roundtrip({1: [2, 3], 4: ()}) == value
text_value = {"α": {"one", "two"}, "empty": set()}
assert dict_set_probe.roundtrip_text(text_value) == text_value
assert dict_set_probe.roundtrip_text({"α": ["one", "two"]}) == {"α": {"one", "two"}}
nested_value = {1: {10: {20, 30}, 11: set()}, 2: {}}
assert dict_set_probe.roundtrip_nested(nested_value) == nested_value

for function, bad in (
    (dict_set_probe.roundtrip, {"bad": {1}}),
    (dict_set_probe.roundtrip, {1: {2**70}}),
    (dict_set_probe.roundtrip_text, {"bad": {1}}),
    (dict_set_probe.roundtrip_text, {"bad\x00": {"ok"}}),
):
    try:
        function(bad)
    except (TypeError, OverflowError, ValueError):
        pass
    else:
        raise AssertionError((function.__name__, bad))

try:
    dict_set_probe.roundtrip_text({"bad": {1}})
except TypeError as exc:
    assert "at path ['bad'][1]:" in str(exc)
    assert exc.function == "roundtrip_text"
    assert exc.parameter == "values"
    assert exc.path == "['bad'][1]"
else:
    raise AssertionError("nested set element error did not include mapping and value paths")

print("pymodule dictionary-of-sets smoke OK")
PY
