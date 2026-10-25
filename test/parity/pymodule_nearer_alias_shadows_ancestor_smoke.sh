#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_nearer_alias_shadows_ancestor.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["nearer_alias_wins"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "11"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/manifest.pyi" "$SOURCE" >/dev/null
grep -Fq 'def nearer_alias_wins(value: int = 11) -> int: ...' "$WORK/manifest.pyi"
python3 -m py_compile "$WORK/manifest.pyi"

echo "pymodule ancestor lexical module precedes nearer alias smoke OK"
