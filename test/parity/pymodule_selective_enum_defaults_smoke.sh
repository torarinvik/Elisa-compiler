#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
SOURCE="$ROOT/test/repro/pymodule_selective_enum_defaults.elisa"
FALLBACK_SOURCE="$ROOT/test/repro/pymodule_alias_module_fallback.elisa"
SAME_LEAF_SOURCE="$ROOT/test/repro/pymodule_alias_module_same_leaf.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/selective_enum_defaults.json" "$SOURCE" >/dev/null
python3 - "$WORK/selective_enum_defaults.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "selective_enum_defaults"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["imported"]["parameters"] == [{"name": "value", "type": "i64", "default": "41"}]
assert functions["nearest"]["parameters"] == [{"name": "value", "type": "i64", "default": "31"}]
assert functions["local"]["parameters"] == [{"name": "value", "type": "i64", "default": "93"}]
assert functions["parent_beats_import"]["parameters"] == [{"name": "value", "type": "i64", "default": "17"}]
assert functions["nested_qualified"]["parameters"] == [{"name": "value", "type": "i64", "default": "82"}]
assert functions["alias_wins"]["parameters"] == [{"name": "value", "type": "i64", "default": "66"}]
assert functions["chained_alias"]["parameters"] == [{"name": "value", "type": "i64", "default": "71"}]
assert functions["qualified_target_alias"]["parameters"] == [{"name": "value", "type": "i64", "default": "83"}]
assert functions["long_chained_alias"]["parameters"] == [{"name": "value", "type": "i64", "default": "71"}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/selective_enum_defaults.pyi" "$SOURCE" >/dev/null
grep -Fq 'def imported(value: int = 41) -> int: ...' "$WORK/selective_enum_defaults.pyi"
grep -Fq 'def nearest(value: int = 31) -> int: ...' "$WORK/selective_enum_defaults.pyi"
grep -Fq 'def local(value: int = 93) -> int: ...' "$WORK/selective_enum_defaults.pyi"
grep -Fq 'def parent_beats_import(value: int = 17) -> int: ...' "$WORK/selective_enum_defaults.pyi"
grep -Fq 'def nested_qualified(value: int = 82) -> int: ...' "$WORK/selective_enum_defaults.pyi"
grep -Fq 'def alias_wins(value: int = 66) -> int: ...' "$WORK/selective_enum_defaults.pyi"
grep -Fq 'def chained_alias(value: int = 71) -> int: ...' "$WORK/selective_enum_defaults.pyi"
grep -Fq 'def qualified_target_alias(value: int = 83) -> int: ...' "$WORK/selective_enum_defaults.pyi"
grep -Fq 'def long_chained_alias(value: int = 71) -> int: ...' "$WORK/selective_enum_defaults.pyi"
python3 -m py_compile "$WORK/selective_enum_defaults.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/alias_module_fallback.json" "$FALLBACK_SOURCE" >/dev/null
python3 - "$WORK/alias_module_fallback.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "alias_module_fallback"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["alias_fallback"]["parameters"] == [{"name": "value", "type": "i64", "default": "57"}]
PY
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/alias_module_same_leaf.json" "$SAME_LEAF_SOURCE" >/dev/null
python3 - "$WORK/alias_module_same_leaf.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "alias_module_same_leaf"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["alias_wins"]["parameters"] == [{"name": "value", "type": "i64", "default": "57"}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/alias_module_fallback.pyi" "$FALLBACK_SOURCE" >/dev/null
grep -Fq 'def alias_fallback(value: int = 57) -> int: ...' "$WORK/alias_module_fallback.pyi"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/alias_module_same_leaf.pyi" "$SAME_LEAF_SOURCE" >/dev/null
grep -Fq 'def alias_wins(value: int = 57) -> int: ...' "$WORK/alias_module_same_leaf.pyi"
python3 -m py_compile "$WORK/alias_module_fallback.pyi" "$WORK/alias_module_same_leaf.pyi"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule selective enum defaults smoke OK (runtime build skipped)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/selective_enum_defaults.cpython-314-darwin.so" \
    "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import selective_enum_defaults as module
import alias_module_fallback as fallback
import alias_module_same_leaf as same_leaf

assert module.imported() == 41
assert str(inspect.signature(module.imported)) == "(value=41)"
assert module.nearest() == 31
assert str(inspect.signature(module.nearest)) == "(value=31)"
assert module.local() == 93
assert str(inspect.signature(module.local)) == "(value=93)"
assert module.parent_beats_import() == 17
assert str(inspect.signature(module.parent_beats_import)) == "(value=17)"
assert module.nested_qualified() == 82
assert str(inspect.signature(module.nested_qualified)) == "(value=82)"
assert module.alias_wins() == 66
assert str(inspect.signature(module.alias_wins)) == "(value=66)"
assert module.chained_alias() == 71
assert str(inspect.signature(module.chained_alias)) == "(value=71)"
assert module.qualified_target_alias() == 83
assert str(inspect.signature(module.qualified_target_alias)) == "(value=83)"
assert module.long_chained_alias() == 71
assert str(inspect.signature(module.long_chained_alias)) == "(value=71)"
assert fallback.alias_fallback() == 57
assert str(inspect.signature(fallback.alias_fallback)) == "(value=57)"
assert same_leaf.alias_wins() == 57
assert str(inspect.signature(same_leaf.alias_wins)) == "(value=57)"
PY

echo "pymodule selective enum defaults smoke OK"
