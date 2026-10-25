#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_private_extend_enum_root_fallback.elisa"

python3 "$ROOT/test/proofs/check_pymodule_private_enum_visibility.py"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/private_extend_enum_root_fallback.json" "$SOURCE" >/dev/null
python3 - "$WORK/private_extend_enum_root_fallback.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "pymodule_private_extend_enum_root_fallback"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["root_fallback"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "97"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/private_extend_enum_root_fallback.pyi" "$SOURCE" >/dev/null
grep -Fq 'def root_fallback(value: int = 97) -> int: ...' "$WORK/private_extend_enum_root_fallback.pyi"
python3 -m py_compile "$WORK/private_extend_enum_root_fallback.pyi"

echo "pymodule private extend enum root fallback smoke OK"
