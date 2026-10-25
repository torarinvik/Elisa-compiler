#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_inherited_wildcard_precedes_local.elisa"

python3 "$ROOT/test/proofs/check_pymodule_enum_import_precedence.py"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/inherited_wildcard_precedes_local.json" "$SOURCE" >/dev/null
python3 - "$WORK/inherited_wildcard_precedes_local.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "inherited_wildcard_precedes_local"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["inherited_wildcard"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "17"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/inherited_wildcard_precedes_local.pyi" "$SOURCE" >/dev/null
grep -Fq 'def inherited_wildcard(value: int = 17) -> int: ...' \
    "$WORK/inherited_wildcard_precedes_local.pyi"
python3 -m py_compile "$WORK/inherited_wildcard_precedes_local.pyi"

echo "pymodule inherited wildcard precedence smoke OK"
