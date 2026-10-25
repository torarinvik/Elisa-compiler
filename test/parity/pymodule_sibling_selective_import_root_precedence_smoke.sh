#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_sibling_selective_import_root_precedence.elisa"

python3 "$ROOT/test/proofs/check_pymodule_enum_import_precedence.py"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/sibling_selective_import_root_precedence.json" "$SOURCE" >/dev/null
python3 - "$WORK/sibling_selective_import_root_precedence.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "sibling_selective_import_root_precedence"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["sibling_import"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "41"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/sibling_selective_import_root_precedence.pyi" "$SOURCE" >/dev/null
grep -Fq 'def sibling_import(value: int = 41) -> int: ...' \
    "$WORK/sibling_selective_import_root_precedence.pyi"
python3 -m py_compile "$WORK/sibling_selective_import_root_precedence.pyi"

echo "pymodule sibling selective import precedence smoke OK"
