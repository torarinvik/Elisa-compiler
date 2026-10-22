#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_nested_alias_scope.elisa"
TARGET_SCOPE_SOURCE="$ROOT/test/repro/pymodule_nested_alias_target_scope.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/nested_alias_scope.json" "$SOURCE" >/dev/null
python3 - "$WORK/nested_alias_scope.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["nested_alias_fallback"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "20"}
]
assert functions["nested_alias_local_target"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "30"}
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/nested_alias_scope.pyi" "$SOURCE" >/dev/null
grep -Fq 'def nested_alias_fallback(value: int = 20) -> int: ...' "$WORK/nested_alias_scope.pyi"
grep -Fq 'def nested_alias_local_target(value: int = 30) -> int: ...' "$WORK/nested_alias_scope.pyi"
python3 -m py_compile "$WORK/nested_alias_scope.pyi"

# An unqualified target in a nested using declaration stays in its declaration
# scope. Root Target must not be selected as the target of Scope's `using Target`.
if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/nested_alias_target_scope.json" "$TARGET_SCOPE_SOURCE" >"$WORK/target_scope.log" 2>&1; then
    python3 - "$WORK/nested_alias_target_scope.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
parameter = functions["nested_target_scope"]["parameters"][0]
assert parameter.get("default") != "91", parameter
PY
else
    grep -Eq 'Alias|Mode' "$WORK/target_scope.log" || {
        cat "$WORK/target_scope.log"
        exit 1
    }
fi

echo "pymodule nested alias scope smoke OK"
