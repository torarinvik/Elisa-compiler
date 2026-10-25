#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_selective_import_shadows_root.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/selective_import_shadows_root.json" "$SOURCE" >/dev/null
python3 - "$WORK/selective_import_shadows_root.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "selective_import_shadows_root"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["imported_beats_root"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "41"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/selective_import_shadows_root.pyi" "$SOURCE" >/dev/null
grep -Fq 'def imported_beats_root(value: int = 41) -> int: ...' \
    "$WORK/selective_import_shadows_root.pyi"
python3 -m py_compile "$WORK/selective_import_shadows_root.pyi"
