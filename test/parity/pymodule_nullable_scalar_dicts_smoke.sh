#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nullable-scalar-dict smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 8) else 1)
PY
then
    echo "pymodule nullable-scalar-dict smoke SKIP (Python too old)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/nullable_scalar_dicts.json" \
    "$ROOT/test/repro/pymodule_nullable_scalar_dicts.elisa" >/dev/null

"$PYTHON_BIN" - "$WORK/nullable_scalar_dicts.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1]))
expected = {
    "optional_signed": ("dict[cstr,i64?]", "dict[cstr,i64?]"),
    "optional_unsigned": ("dict[cstr,u8?]", "dict[cstr,u8?]"),
    "optional_bool": ("dict[cstr,bool?]", "dict[cstr,bool?]"),
    "optional_float": ("dict[cstr,f32?]", "dict[cstr,f32?]"),
}
rows = {row["name"]: row for row in manifest["functions"]}
assert set(rows) == set(expected)
for name, (param_type, return_type) in expected.items():
    assert rows[name]["parameters"] == [{"name": "values", "type": param_type}]
    assert rows[name]["return"] == return_type
PY

if ! PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so -o "$WORK/nullable_scalar_dicts.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_nullable_scalar_dicts.elisa" >/dev/null; then
    echo "pymodule nullable-scalar-dict smoke SKIP (Python extension toolchain unavailable)"
    exit 0
fi

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nullable_scalar_dicts

assert nullable_scalar_dicts.optional_signed({"a": -2, "none": None, "z": 7}) == {"a": -2, "none": None, "z": 7}
assert nullable_scalar_dicts.optional_unsigned({"zero": 0, "none": None, "max": 255}) == {"zero": 0, "none": None, "max": 255}
assert nullable_scalar_dicts.optional_bool({"yes": True, "none": None, "no": False}) == {"yes": True, "none": None, "no": False}
assert nullable_scalar_dicts.optional_float({"pi": 1.25, "none": None, "neg": -2.5}) == {"pi": 1.25, "none": None, "neg": -2.5}

for bad in (256, -1):
    try:
        nullable_scalar_dicts.optional_unsigned({"bad": bad})
    except OverflowError:
        pass
    else:
        raise AssertionError("u8 dictionary value should range-check")

try:
    nullable_scalar_dicts.optional_signed({"bad": "text"})
except TypeError:
    pass
else:
    raise AssertionError("integer dictionary value should reject text")

print("pymodule nullable-scalar-dict smoke OK")
PY
