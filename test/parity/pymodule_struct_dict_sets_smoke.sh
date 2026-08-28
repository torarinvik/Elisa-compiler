#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
SOURCE="$ROOT/test/repro/pymodule_struct_dict_sets.elisa"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct-dict-set smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["structs"] == [{
    "name": "DictSetBundle",
    "fields": [
        {"name": "numbers", "type": "dict[i64,set[i64]]"},
        {"name": "labels", "type": "dict[cstr,set[sview]]"},
        {"name": "nested", "type": "dict[i64,dict[i64,set[i64]]]"},
    ],
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_dict_sets.pyi" "$SOURCE" >/dev/null
grep -Fq 'class DictSetBundle(TypedDict):' "$WORK/struct_dict_sets.pyi"
grep -Fq 'numbers: dict[int, set[int]]' "$WORK/struct_dict_sets.pyi"
grep -Fq 'labels: dict[str, set[str]]' "$WORK/struct_dict_sets.pyi"
grep -Fq 'nested: dict[int, dict[int, set[int]]]' "$WORK/struct_dict_sets.pyi"
grep -Fq 'def echo(bundle: DictSetBundle | DictSetBundleInput) -> DictSetBundle: ...' "$WORK/struct_dict_sets.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_dict_sets.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_dict_sets.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_dict_sets

value = {
    "numbers": {1: {2, 3}, 4: set()},
    "labels": {"α": {"one", "two"}, "empty": set()},
    "nested": {1: {10: {20, 30}, 11: set()}, 2: {}},
}
assert struct_dict_sets.echo(value) == value
assert struct_dict_sets.echo({
    "numbers": {1: [2, 3]},
    "labels": {"α": ["one", "two"]},
    "nested": {1: {10: [20, 30]}},
}) == {
    "numbers": {1: {2, 3}},
    "labels": {"α": {"one", "two"}},
    "nested": {1: {10: {20, 30}}},
}

for bad in (
    {**value, "numbers": {"bad": {1}}},
    {**value, "numbers": {1: {2**70}}},
    {**value, "labels": {"bad": {1}}},
    {**value, "nested": {1: {10: {2**70}}}},
):
    try:
        struct_dict_sets.echo(bad)
    except (TypeError, OverflowError, ValueError):
        pass
    else:
        raise AssertionError(f"invalid struct dictionary-of-sets value accepted: {bad!r}")

print("pymodule struct dictionary-of-sets smoke OK")
PY
