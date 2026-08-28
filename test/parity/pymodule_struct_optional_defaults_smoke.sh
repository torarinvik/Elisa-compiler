#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
SOURCE="$ROOT/test/repro/pymodule_struct_optional_defaults.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/struct_optional_defaults.json" "$SOURCE" >/dev/null
python3 - "$WORK/struct_optional_defaults.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["structs"] == [{
    "name": "Config",
    "fields": [
        {"name": "retries", "type": "i64?", "optional": True, "default": "7"},
        {"name": "ratio", "type": "f64?", "optional": True, "default": "0.5"},
        {"name": "enabled", "type": "bool?", "optional": True, "default": "True"},
        {"name": "name", "type": "sview?", "optional": True, "default": '"hello"'},
        {"name": "c_name", "type": "cstr?", "optional": True, "default": '"world"'},
        {"name": "missing", "type": "py::Object?", "optional": True, "default": "None"},
    ],
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_optional_defaults.pyi" "$SOURCE" >/dev/null
grep -Fq 'retries: NotRequired[int | None]' "$WORK/struct_optional_defaults.pyi"
grep -Fq "# optional attribute 'retries': int | None" "$WORK/struct_optional_defaults.pyi"
grep -Fq 'name: NotRequired[str | None]' "$WORK/struct_optional_defaults.pyi"
grep -Fq 'c_name: NotRequired[str | None]' "$WORK/struct_optional_defaults.pyi"
grep -Fq 'def roundtrip(config: Config | ConfigInput) -> Config: ...' "$WORK/struct_optional_defaults.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_optional_defaults.pyi"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct optional defaults smoke OK (runtime build skipped)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_optional_defaults.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_optional_defaults as module

expected = {
    "retries": 7,
    "ratio": 0.5,
    "enabled": True,
    "name": "hello",
    "c_name": "world",
    "missing": None,
}
assert module.roundtrip({}) == expected
assert module.roundtrip({"retries": None, "ratio": None, "enabled": None, "name": None, "c_name": None, "missing": None}) == {
    "retries": None, "ratio": None, "enabled": None, "name": None, "c_name": None, "missing": None,
}
assert module.roundtrip({"retries": 9, "name": "override", "c_name": b"bytes"}) == {
    "retries": 9, "ratio": 0.5, "enabled": True, "name": "override", "c_name": "bytes", "missing": None,
}
assert module.roundtrip({}) == expected
print("pymodule struct optional defaults smoke OK")
PY
