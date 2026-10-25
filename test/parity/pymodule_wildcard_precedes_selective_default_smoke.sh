#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_wildcard_precedes_selective_default.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/wildcard_precedes_selective_default.json" "$SOURCE" >/dev/null
python3 - "$WORK/wildcard_precedes_selective_default.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "wildcard_precedes_selective_default"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["wildcard_beats_selective"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "73"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/wildcard_precedes_selective_default.pyi" "$SOURCE" >/dev/null
grep -Fq 'def wildcard_beats_selective(value: int = 73) -> int: ...' \
    "$WORK/wildcard_precedes_selective_default.pyi"
python3 -m py_compile "$WORK/wildcard_precedes_selective_default.pyi"
