#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_duplicate_unresolved_alias_root_fallback.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/duplicate_unresolved_alias_root_fallback.json" "$SOURCE" >/dev/null
python3 - "$WORK/duplicate_unresolved_alias_root_fallback.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "duplicate_unresolved_alias_root_fallback"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["duplicate_unresolved_alias_fallback"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "77"},
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/duplicate_unresolved_alias_root_fallback.pyi" "$SOURCE" >/dev/null
grep -Fq 'def duplicate_unresolved_alias_fallback(value: int = 77) -> int: ...' "$WORK/duplicate_unresolved_alias_root_fallback.pyi"
python3 -m py_compile "$WORK/duplicate_unresolved_alias_root_fallback.pyi"

echo "pymodule duplicate unresolved alias root fallback smoke OK"
