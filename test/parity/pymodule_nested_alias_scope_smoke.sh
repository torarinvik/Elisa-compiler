#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_nested_alias_scope.elisa"
TARGET_SCOPE_SOURCE="$ROOT/test/repro/pymodule_nested_alias_target_scope.elisa"
MISSING_TARGET_SOURCE="$ROOT/test/repro/pymodule_nested_alias_missing_target_scope.elisa"
MISSING_VARIANT_SOURCE="$ROOT/test/repro/pymodule_nested_alias_missing_variant_scope.elisa"

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

# A nested Target must win over the same-named root Target when Scope declares
# `using Target as Alias`. The distinct values catch accidental root selection.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/nested_alias_target_scope.json" "$TARGET_SCOPE_SOURCE" >/dev/null
python3 - "$WORK/nested_alias_target_scope.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["nested_target_scope"]["parameters"] == [
    {"name": "value", "type": "i64", "default": "92"}
]
PY
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/nested_alias_target_scope.pyi" "$TARGET_SCOPE_SOURCE" >/dev/null
grep -Fq 'def nested_target_scope(value: int = 92) -> int: ...' "$WORK/nested_alias_target_scope.pyi"
python3 -m py_compile "$WORK/nested_alias_target_scope.pyi"

# A nested alias with no module target anywhere must remain unresolved.
for emit_mode in obj pymodule; do
    if bash "$ROOT/scripts/elisac_stage1.sh" -emit "$emit_mode" \
        -o "$WORK/missing_target.$emit_mode" "$MISSING_TARGET_SOURCE" \
        >"$WORK/missing_target.$emit_mode.log" 2>&1; then
        echo "$emit_mode unexpectedly resolved a missing alias target" >&2
        exit 1
    fi
    grep -Fq 'undefined identifier "Alias.Mode"' "$WORK/missing_target.$emit_mode.log"
done

# A nearer nested enum with no High variant shadows the root enum that has High.
if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/missing_variant.json" "$MISSING_VARIANT_SOURCE" \
    >"$WORK/missing_variant.log" 2>&1; then
    echo "pymodule unexpectedly used a root enum variant hidden by a nearer enum" >&2
    exit 1
fi
grep -Fq 'const enum "Scope.X.Nested.Mode" has no member "High"' "$WORK/missing_variant.log"

echo "pymodule nested alias scope smoke OK"
