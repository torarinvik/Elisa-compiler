#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for emit_mode in pymodule pymodule-c; do
    if bash "$ROOT/scripts/elisac_stage1.sh" -emit "$emit_mode" \
        -o "$WORK/$emit_mode.out" \
        "$ROOT/test/repro/pymodule_unsupported_constant.elisa" \
        >"$WORK/$emit_mode.log" 2>&1; then
        echo "$emit_mode unexpectedly accepted an unsupported constant" >&2
        exit 1
    fi
    grep -Fq "error: -emit $emit_mode supports scalar, text, and byte constants (target \`MASKS\`)" "$WORK/$emit_mode.log"
done

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/missing.json" \
    "$ROOT/test/repro/pymodule_constant_target_missing.elisa" \
    >"$WORK/missing.log" 2>&1; then
    echo "pymodule unexpectedly accepted an undefined constant target" >&2
    exit 1
fi
grep -Fq 'export target "Missing::VALUE" is undefined' "$WORK/missing.log"

echo "pymodule unsupported-constant diagnostic OK"
