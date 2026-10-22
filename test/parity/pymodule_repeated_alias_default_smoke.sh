#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_repeated_alias_default.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/repeated_alias_default.json" "$SOURCE" >/dev/null
python3 - "$WORK/repeated_alias_default.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["repeated_alias_default"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "94"}
]
assert functions["canonical_alias_default"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "94"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/repeated_alias_default.pyi" "$SOURCE" >/dev/null
grep -Fq 'def repeated_alias_default(value: int = 94) -> int: ...' "$WORK/repeated_alias_default.pyi"
grep -Fq 'def canonical_alias_default(value: int = 94) -> int: ...' "$WORK/repeated_alias_default.pyi"
python3 -m py_compile "$WORK/repeated_alias_default.pyi"

echo "pymodule repeated alias default smoke OK"
