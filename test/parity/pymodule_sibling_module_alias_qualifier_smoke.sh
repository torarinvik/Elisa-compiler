#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_sibling_module_alias_qualifier.elisa"

python3 "$ROOT/test/proofs/check_pymodule_enum_import_precedence.py"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/sibling_module_alias_qualifier.json" "$SOURCE" >/dev/null
python3 - "$WORK/sibling_module_alias_qualifier.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "sibling_module_alias_qualifier"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["sibling_alias"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "41"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/sibling_module_alias_qualifier.pyi" "$SOURCE" >/dev/null
grep -Fq 'def sibling_alias(value: int = 41) -> int: ...' \
    "$WORK/sibling_module_alias_qualifier.pyi"
python3 -m py_compile "$WORK/sibling_module_alias_qualifier.pyi"

echo "pymodule sibling module alias qualifier smoke OK"
