#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
SOURCE="$ROOT/test/repro/pymodule_qualified_enum_defaults.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/qualified_enum_defaults.json" "$SOURCE" >/dev/null
python3 - "$WORK/qualified_enum_defaults.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "qualified_enum_defaults"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["left"]["parameters"] == [{"name": "value", "type": "i64", "default": "2"}]
assert functions["right"]["parameters"] == [{"name": "value", "type": "i64", "default": "77"}]
assert functions["local"]["parameters"] == [{"name": "value", "type": "i64", "default": "31"}]
assert functions["top"]["parameters"] == [{"name": "value", "type": "i64", "default": "2"}]
assert functions["alias"]["parameters"] == [{"name": "value", "type": "i64", "default": "2"}]
assert functions["narrowed"]["parameters"] == [{"name": "value", "type": "u8", "default": "44"}]
assert functions["nested"]["parameters"] == [{"name": "value", "type": "i64", "default": "45"}]
assert functions["parent"]["parameters"] == [{"name": "value", "type": "i64", "default": "91"}]
assert functions["shadow"]["parameters"] == [{"name": "value", "type": "i64", "default": "53"}]
assert functions["from_left"]["parameters"] == [{"name": "value", "type": "i64", "default": "2"}]
assert functions["from_right"]["parameters"] == [{"name": "value", "type": "i64", "default": "77"}]
assert functions["from_nested_alias_chain"]["parameters"] == [{"name": "value", "type": "i64", "default": "42"}]
assert functions["nested_module_wins"]["parameters"] == [{"name": "value", "type": "i64", "default": "82"}]
assert functions["nested_chain_module_wins"]["parameters"] == [{"name": "value", "type": "i64", "default": "95"}]
assert functions["nested_alias_suffix_fallback"]["parameters"] == [{"name": "value", "type": "i64", "default": "58"}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/qualified_enum_defaults.pyi" "$SOURCE" >/dev/null
grep -Fq 'def left(value: int = 2) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def right(value: int = 77) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def local(value: int = 31) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def top(value: int = 2) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def alias(value: int = 2) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def narrowed(value: int = 44) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def nested(value: int = 45) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def parent(value: int = 91) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def shadow(value: int = 53) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def from_left(value: int = 2) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def from_right(value: int = 77) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def from_nested_alias_chain(value: int = 42) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def nested_module_wins(value: int = 82) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def nested_chain_module_wins(value: int = 95) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
grep -Fq 'def nested_alias_suffix_fallback(value: int = 58) -> int: ...' "$WORK/qualified_enum_defaults.pyi"
python3 -m py_compile "$WORK/qualified_enum_defaults.pyi"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule qualified enum defaults smoke OK (runtime build skipped)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/qualified_enum_defaults.cpython-314-darwin.so" \
    "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import qualified_enum_defaults as module

assert module.left() == 2
assert str(inspect.signature(module.left)) == "(value=2)"
assert module.right() == 77
assert str(inspect.signature(module.right)) == "(value=77)"
assert module.local() == 31
assert str(inspect.signature(module.local)) == "(value=31)"
assert module.top() == 2
assert str(inspect.signature(module.top)) == "(value=2)"
assert module.alias() == 2
assert str(inspect.signature(module.alias)) == "(value=2)"
assert module.narrowed() == 44
assert str(inspect.signature(module.narrowed)) == "(value=44)"
assert module.nested() == 45
assert str(inspect.signature(module.nested)) == "(value=45)"
assert module.parent() == 91
assert str(inspect.signature(module.parent)) == "(value=91)"
assert module.shadow() == 53
assert str(inspect.signature(module.shadow)) == "(value=53)"
assert module.from_left() == 2
assert str(inspect.signature(module.from_left)) == "(value=2)"
assert module.from_right() == 77
assert str(inspect.signature(module.from_right)) == "(value=77)"
assert module.from_nested_alias_chain() == 42
assert str(inspect.signature(module.from_nested_alias_chain)) == "(value=42)"
assert module.nested_module_wins() == 82
assert str(inspect.signature(module.nested_module_wins)) == "(value=82)"
assert module.nested_chain_module_wins() == 95
assert str(inspect.signature(module.nested_chain_module_wins)) == "(value=95)"
assert module.nested_alias_suffix_fallback() == 58
assert str(inspect.signature(module.nested_alias_suffix_fallback)) == "(value=58)"
PY

echo "pymodule qualified enum defaults smoke OK"
