#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule explicit null defaults smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_optional_null_defaults.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["scalar_default"]["parameters"][0]["default"] == "None"
assert functions["defaulted"]["parameters"][0]["default"] == "{}"
structs = {row["name"]: row for row in manifest["structs"]}
fields = structs["OptionalDefaults"]["fields"]
assert {field["name"]: field["default"] for field in fields} == {
    "signed": "None",
    "ratio": "None",
    "enabled": "None",
    "label": "None",
    "text": "None",
    "payload": "None",
}
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/optional_null_defaults.pyi" "$SOURCE" >/dev/null
grep -Fq 'def scalar_default(value: int | None = None) -> int | None: ...' "$WORK/optional_null_defaults.pyi"
grep -Fq 'def defaulted(options: OptionalDefaults | OptionalDefaultsInput = {}) -> OptionalDefaults: ...' "$WORK/optional_null_defaults.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/optional_null_defaults.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_null_defaults.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import optional_null_defaults as module

expected = {
    "signed": None,
    "ratio": None,
    "enabled": None,
    "label": None,
    "text": None,
    "payload": None,
}
assert module.roundtrip({}) == expected
assert module.defaulted() == expected
assert module.scalar_default() is None
assert module.scalar_default(9) == 9

marker = {"source": "python"}
present = {
    "signed": -7,
    "ratio": 1.5,
    "enabled": False,
    "label": "label",
    "text": "embedded\x00nul",
    "payload": marker,
}
assert module.roundtrip(present) == present
assert module.roundtrip(present)["payload"] is marker

print("pymodule explicit null defaults smoke OK")
PY
