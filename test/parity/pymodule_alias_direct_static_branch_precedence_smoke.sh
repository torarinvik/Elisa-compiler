#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_alias_direct_static_branch_precedence.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/alias_precedence.json" "$SOURCE" >/dev/null
python3 - "$WORK/alias_precedence.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
for name in (
    "direct_alias_default",
    "chained_alias_default",
    "nested_branch_alias_cutoff_default",
):
    assert functions[name]["parameters"] == [
        {"name": "value", "type": "i64", "default": "41"}
    ], (name, functions[name]["parameters"])
assert functions["nested_global_alias_default"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "73"}
], functions["nested_global_alias_default"]["parameters"]
assert functions["nested_branch_alias_default"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "85"}
], functions["nested_branch_alias_default"]["parameters"]
assert functions["sibling_branch_alias_default"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "86"}
], functions["sibling_branch_alias_default"]["parameters"]
PY

echo "pymodule direct-over-static-branch alias precedence OK"
