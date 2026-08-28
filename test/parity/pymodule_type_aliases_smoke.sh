#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule type-alias smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/type_aliases.json" \
    "$ROOT/test/repro/pymodule_type_aliases.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/type_aliases.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
rows = {row["name"]: row for row in manifest["functions"]}
assert rows["identity_id"]["parameters"] == [{"name": "value", "type": "i64"}]
assert rows["identity_id"]["return"] == "i64"
assert rows["identity_count"]["parameters"] == [{"name": "value", "type": "u8"}]
assert rows["identity_count"]["return"] == "u8"
assert rows["identity_name"]["parameters"] == [{"name": "value", "type": "sview"}]
assert rows["identity_name"]["return"] == "sview"
assert rows["identity_optional"]["parameters"] == [{"name": "value", "type": "i64?", "default": "None"}]
assert rows["identity_optional"]["return"] == "i64?"
assert rows["identity_ids"]["parameters"] == [{"name": "values", "type": "darray[i64]"}]
assert rows["identity_ids"]["return"] == "darray[i64]"
assert rows["identity_map"]["parameters"] == [{"name": "values", "type": "dict[cstr,i64]"}]
assert rows["identity_map"]["return"] == "dict[cstr,i64]"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/type_aliases.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_type_aliases.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import type_aliases

assert type_aliases.identity_id(42) == 42
assert type_aliases.identity_count(255) == 255
assert type_aliases.identity_name("på\x00東京") == "på\x00東京"
assert type_aliases.identity_optional() is None
assert type_aliases.identity_optional(7) == 7
assert type_aliases.identity_ids([1, 2, 3]) == [1, 2, 3]
assert type_aliases.identity_map({"first": 1, "second": 2}) == {"first": 1, "second": 2}
try:
    type_aliases.identity_count(256)
except OverflowError:
    pass
else:
    raise AssertionError("u8 alias should retain narrow range checking")

print("pymodule type-alias smoke OK")
PY
