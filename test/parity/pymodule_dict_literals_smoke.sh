#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dict literals smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

# Private generic helper structs used to implement the native dictionary literal must not make
# the public manifest fail: their erased fields are marked <unsupported> for introspection, while
# the exported functions remain fully representable.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/dict_literals.json" \
    "$ROOT/test/repro/pymodule_dict_literals.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/dict_literals.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
assert manifest["module"] == "dict_literals"
assert [function["name"] for function in manifest["functions"]] == ["literal_i64", "comprehension_i64"]
dyn_dict = next(struct for struct in manifest["structs"] if struct["name"] == "DynDict")
items_field = next(field for field in dyn_dict["fields"] if field["name"] == "items")
assert items_field["type"] == "<unsupported>"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dict_literals.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_dict_literals.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import dict_literals

assert dict_literals.literal_i64() == {1: 40, 2: 2}
assert dict_literals.comprehension_i64() == {1: 2, 2: 4, 3: 6}
PY

echo "pymodule dict literals smoke OK"
