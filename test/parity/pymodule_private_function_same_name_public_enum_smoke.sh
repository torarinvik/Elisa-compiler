#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_private_function_same_name_public_enum.elisa"

python3 "$ROOT/test/proofs/check_pymodule_private_function_enum_visibility.py"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/private_function_same_name_public_enum.json" "$SOURCE" >/dev/null
python3 - "$WORK/private_function_same_name_public_enum.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "pymodule_private_function_same_name_public_enum"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["imported_public_enum"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "11"}
]
PY
