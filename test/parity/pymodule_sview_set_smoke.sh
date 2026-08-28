#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule sview set smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_sview_set.elisa"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["functions"] == [{
    "name": "roundtrip",
    "target": "roundtrip",
    "parameters": [{"name": "values", "type": "set[sview]"}],
    "return": "set[sview]",
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/sview_set.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip(values: Iterable[str | bytes]) -> set[str]: ...' "$WORK/sview_set.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/sview_set.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/sview_set.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import sview_set

values = {"a\x00key", "empty", "unicode-λ"}
assert sview_set.roundtrip(values) == values
assert sview_set.roundtrip({b"bytes", b"\xce\xb1"}) == {"bytes", "α"}
assert sview_set.roundtrip(frozenset(values)) == values
assert sview_set.roundtrip(value for value in values) == values

for bad in ({1},):
    try:
        sview_set.roundtrip(bad)
    except TypeError:
        pass
    else:
        raise AssertionError("invalid sview set value accepted")
try:
    sview_set.roundtrip({b"\xff"})
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("invalid UTF-8 sview set value accepted")

print("pymodule sview set smoke OK")
PY
