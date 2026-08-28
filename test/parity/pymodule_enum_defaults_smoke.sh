#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
SOURCE="$ROOT/test/repro/pymodule_enum_defaults.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/enum_defaults.json" "$SOURCE" >/dev/null
python3 - "$WORK/enum_defaults.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "enum_defaults"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["defaulted"]["parameters"] == [{
    "name": "mode", "type": "i64", "default": "7",
}]
assert functions["list_default"]["parameters"] == [{
    "name": "modes", "type": "darray[i64]", "default": "[2, 7, 8]",
}]
assert functions["dict_default"]["parameters"] == [{
    "name": "modes", "type": "dict[i64,i64]", "default": "{1: 7, 2: 8}",
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/enum_defaults.pyi" "$SOURCE" >/dev/null
grep -Fq 'def defaulted(mode: int = 7) -> int: ...' "$WORK/enum_defaults.pyi"
grep -Fq 'def list_default(modes: Sequence[int] = [2, 7, 8]) -> list[int]: ...' "$WORK/enum_defaults.pyi"
grep -Fq 'def dict_default(modes: Mapping[int, int] = {1: 7, 2: 8}) -> dict[int, int]: ...' "$WORK/enum_defaults.pyi"
"${PYTHON_BIN:-python3}" -m py_compile "$WORK/enum_defaults.pyi"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule enum defaults smoke OK (runtime build skipped)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/enum_defaults.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import enum_defaults as module

assert module.defaulted() == 7
assert module.defaulted(2) == 2
assert module.defaulted(0) == 0
assert module.list_default() == [2, 7, 8]
assert module.dict_default() == {1: 7, 2: 8}

first = module.list_default()
first.append(99)
assert module.list_default() == [2, 7, 8]
first_map = module.dict_default()
first_map[3] = 10
assert module.dict_default() == {1: 7, 2: 8}
assert module.list_default([4, 5]) == [4, 5]
assert module.dict_default({9: 10}) == {9: 10}
print("pymodule enum defaults smoke OK")
PY
