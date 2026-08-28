#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/invalid_export.c" \
    "$ROOT/test/repro/pymodule_invalid_export_name.elisa" >"$WORK/export.log" 2>&1; then
    echo "invalid Python export name unexpectedly accepted" >&2
    exit 1
fi
grep -Fq 'export name `class` must be a valid Python identifier' "$WORK/export.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/invalid_export.pyi" \
    "$ROOT/test/repro/pymodule_invalid_export_name.elisa" >"$WORK/pyi.log" 2>&1; then
    echo "invalid Python export name unexpectedly accepted by pyi mode" >&2
    exit 1
fi
grep -Fq 'export name `class` must be a valid Python identifier' "$WORK/pyi.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/invalid_module.c" \
    "$ROOT/test/repro/pymodule_invalid_module_name.elisa" >"$WORK/module.log" 2>&1; then
    echo "invalid Python module name unexpectedly accepted" >&2
    exit 1
fi
grep -Fq 'module name `class` must be a valid Python identifier' "$WORK/module.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/invalid_error_family.json" \
    "$ROOT/test/repro/pymodule_invalid_error_family.elisa" >"$WORK/error_family.log" 2>&1; then
    echo "invalid Python error family name unexpectedly accepted" >&2
    exit 1
fi
grep -Fq 'error family name `class` must be a valid Python identifier' "$WORK/error_family.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/invalid_parameter.c" \
    "$ROOT/test/repro/pymodule_invalid_parameter_name.elisa" >"$WORK/parameter.log" 2>&1; then
    echo "invalid Python parameter name unexpectedly accepted" >&2
    exit 1
fi
grep -Fq 'parameter name `class` in exported function `value` must be a valid Python identifier' "$WORK/parameter.log"

echo "pymodule Python names smoke OK"
