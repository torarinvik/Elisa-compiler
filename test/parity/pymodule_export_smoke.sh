#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

MANIFEST="$WORK/nested/manifest/fastmath.json"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$MANIFEST" \
    "$ROOT/test/repro/pymodule_export.elisa" >/dev/null

test -f "$MANIFEST"
python3 - "$MANIFEST" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert manifest == {
    "module": "fastmath",
    "functions": [
        {
            "name": "add",
            "target": "add_impl",
            "parameters": [
                {"name": "a", "type": "i64"},
                {"name": "b", "type": "i64"},
            ],
            "return": "i64",
        },
        {
            "name": "negate",
            "target": "negate_impl",
            "parameters": [{"name": "value", "type": "bool"}],
            "return": "bool",
        },
        {
            "name": "ping",
            "target": "ping",
            "parameters": [],
            "return": "i64",
        },
    ],
    "constants": [],
    "structs": [],
}
PY

echo "pymodule export smoke OK"
