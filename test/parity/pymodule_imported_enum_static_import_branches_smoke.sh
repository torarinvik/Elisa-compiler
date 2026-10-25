#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_imported_enum_static_import_branches.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/imported_enum_static_import_branches.json" "$SOURCE" >/dev/null
python3 - "$WORK/imported_enum_static_import_branches.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "pymodule_imported_enum_static_import_branches"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["selected_selective"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "22"}
]
assert functions["selected_wildcard"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "42"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/imported_enum_static_import_branches.pyi" "$SOURCE" >/dev/null
grep -Fq 'def selected_selective(value: int = 22) -> int: ...' "$WORK/imported_enum_static_import_branches.pyi"
grep -Fq 'def selected_wildcard(value: int = 42) -> int: ...' "$WORK/imported_enum_static_import_branches.pyi"
python3 -m py_compile "$WORK/imported_enum_static_import_branches.pyi"

echo "pymodule imported-enum static-import branch smoke OK"
