#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule sview dict keys smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_sview_dict_keys.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["functions"] == [
    {
        "name": "roundtrip",
        "target": "roundtrip",
        "parameters": [{"name": "values", "type": "dict[sview,sview]"}],
        "return": "dict[sview,sview]",
    },
    {
        "name": "roundtrip_points",
        "target": "roundtrip_points",
        "parameters": [{"name": "values", "type": "dict[sview,Point]"}],
        "return": "dict[sview,Point]",
    },
    {
        "name": "count",
        "target": "count",
        "parameters": [{"name": "values", "type": "dict[sview,i64]"}],
        "return": "usize",
    },
]
assert manifest["structs"] == [{
    "name": "Point",
    "fields": [{"name": "x", "type": "i64"}, {"name": "label", "type": "sview"}],
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/sview_dict_keys.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip(values: Mapping[str | bytes, str | bytes]) -> dict[str, str]: ...' "$WORK/sview_dict_keys.pyi"
grep -Fq 'class Point(TypedDict):' "$WORK/sview_dict_keys.pyi"
grep -Fq 'def roundtrip_points(values: Mapping[str | bytes, Point | PointInput]) -> dict[str, Point]: ...' "$WORK/sview_dict_keys.pyi"
grep -Fq 'def count(values: Mapping[str | bytes, int]) -> int: ...' "$WORK/sview_dict_keys.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/sview_dict_keys.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/sview_dict_keys.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import sview_dict_keys

values = {"a\x00key": "x\x00value", "empty": "", "unicode-λ": "ok"}
assert sview_dict_keys.roundtrip(values) == values
assert sview_dict_keys.roundtrip({b"bytes": b"\xce\xb1", "mixed": b"value"}) == {
    "bytes": "α", "mixed": "value"
}
points = {"point\x00key": {"x": -4, "label": "inside\x00"}}
assert sview_dict_keys.roundtrip_points(points) == points
assert sview_dict_keys.roundtrip_points({b"point": {"x": 4, "label": b"inside"}}) == {
    "point": {"x": 4, "label": "inside"}
}
assert sview_dict_keys.count({"one\x00": 1, "two": 2}) == 2
assert sview_dict_keys.count({b"one": 1, b"two": 2}) == 2

for bad in ({1: "value"}, {"key": 42}):
    try:
        sview_dict_keys.roundtrip(bad)
    except TypeError:
        pass
    else:
        raise AssertionError("invalid sview dictionary key/value accepted")
try:
    sview_dict_keys.count({b"\xff": 1})
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("invalid UTF-8 sview dictionary key accepted")

print("pymodule sview dict keys smoke OK")
PY
