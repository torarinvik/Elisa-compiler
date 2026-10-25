#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_alias_import_source_spelling.elisa"

python3 "$ROOT/test/proofs/check_pymodule_enum_import_precedence.py"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/alias_import_source_spelling.json" "$SOURCE" >/dev/null
python3 - "$WORK/alias_import_source_spelling.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "alias_import_source_spelling"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["selective_alias_source"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "47"}
]
assert functions["wildcard_alias_source"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "67"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/alias_import_source_spelling.pyi" "$SOURCE" >/dev/null
grep -Fq 'def selective_alias_source(value: int = 47) -> int: ...' \
    "$WORK/alias_import_source_spelling.pyi"
grep -Fq 'def wildcard_alias_source(value: int = 67) -> int: ...' \
    "$WORK/alias_import_source_spelling.pyi"
python3 -m py_compile "$WORK/alias_import_source_spelling.pyi"

echo "pymodule alias import source spelling smoke OK"
