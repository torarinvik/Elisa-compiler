#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_wildcard_enum_defaults.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/wildcard_enum_defaults.json" "$SOURCE" >/dev/null
python3 - "$WORK/wildcard_enum_defaults.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "wildcard_enum_defaults"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["wildcard_first"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "41"},
]
assert functions["wildcard_alias"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "54"},
]
assert functions["selective_alias"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "64"},
]
assert functions["local_shadow"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "93"},
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/wildcard_enum_defaults.pyi" "$SOURCE" >/dev/null
grep -Fq 'def wildcard_first(value: int = 41) -> int: ...' "$WORK/wildcard_enum_defaults.pyi"
grep -Fq 'def wildcard_alias(value: int = 54) -> int: ...' "$WORK/wildcard_enum_defaults.pyi"
grep -Fq 'def selective_alias(value: int = 64) -> int: ...' "$WORK/wildcard_enum_defaults.pyi"
grep -Fq 'def local_shadow(value: int = 93) -> int: ...' "$WORK/wildcard_enum_defaults.pyi"
python3 -m py_compile "$WORK/wildcard_enum_defaults.pyi"

echo "pymodule wildcard enum defaults smoke OK"
