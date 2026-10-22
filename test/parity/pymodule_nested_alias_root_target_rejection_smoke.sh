#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
SOURCE="$ROOT/test/repro/pymodule_nested_alias_root_target_rejection.elisa"

# `Left` is a root module, but the alias target is resolved under `LeftAlias`.
# An unresolved `LeftAlias::Left` must not silently become the root `Left`.
for emit_mode in obj pymodule; do
    output="$WORK/unresolved.$emit_mode"
    if bash "$ROOT/scripts/elisac_stage1.sh" -emit "$emit_mode" \
        -o "$output" "$SOURCE" >"$WORK/unresolved.$emit_mode.log" 2>&1; then
        echo "$emit_mode unexpectedly resolved the root module as a nested alias target" >&2
        exit 1
    fi
    [[ ! -e "$output" ]] || { echo "$emit_mode rejection left an artifact" >&2; exit 1; }
    grep -Fq 'undefined identifier "X.Mode"' "$WORK/unresolved.$emit_mode.log" || {
        cat "$WORK/unresolved.$emit_mode.log" >&2
        exit 1
    }
done

echo "pymodule nested alias root-target rejection smoke OK"
