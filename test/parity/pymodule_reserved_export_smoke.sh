#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/reserved.c" \
    "$ROOT/test/repro/pymodule_reserved_export.elisa" >"$WORK/reserved.log" 2>&1; then
    echo "reserved pymodule export should be rejected" >&2
    exit 1
fi
grep -Fq 'export name `ConflictError` conflicts with its generated error class' "$WORK/reserved.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/reserved.json" \
    "$ROOT/test/repro/pymodule_reserved_export.elisa" >"$WORK/manifest.log" 2>&1; then
    echo "reserved pymodule manifest export should be rejected" >&2
    exit 1
fi
grep -Fq 'export name `ConflictError` conflicts with its generated error class' "$WORK/manifest.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/reserved_all.c" \
    "$ROOT/test/repro/pymodule_reserved_all.elisa" >"$WORK/all.log" 2>&1; then
    echo "reserved __all__ export should be rejected" >&2
    exit 1
fi
grep -Fq 'export name `__all__` conflicts with the generated module attribute' "$WORK/all.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/error_family.c" \
    "$ROOT/test/repro/pymodule_reserved_error_family.elisa" >"$WORK/error_family.log" 2>&1; then
    echo "reserved error family unexpectedly accepted" >&2
    exit 1
fi
grep -Fq 'error family `__all__` conflicts with the generated module attribute' "$WORK/error_family.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/duplicate.c" \
    "$ROOT/test/repro/pymodule_duplicate_export.elisa" >"$WORK/duplicate.log" 2>&1; then
    echo "duplicate pymodule export should be rejected" >&2
    exit 1
fi
grep -Fq 'duplicate Python module export name "value": public module names must be unique' "$WORK/duplicate.log"

if ELISA_STAGE1_NO_SEMANTIC_GATE=1 bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/duplicate_compiler_owned.c" \
    "$ROOT/test/repro/pymodule_duplicate_export.elisa" >"$WORK/duplicate_compiler_owned.log" 2>&1; then
    echo "obsolete semantic-gate environment variable must not allow artifact emission" >&2
    exit 1
fi
grep -Fq 'duplicate Python module export name "value": public module names must be unique' "$WORK/duplicate_compiler_owned.log"
test ! -s "$WORK/duplicate_compiler_owned.c"

if ELISA_STAGE1_NO_SEMANTIC_GATE=1 bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/duplicate.pyi" \
    "$ROOT/test/repro/pymodule_duplicate_export.elisa" >"$WORK/duplicate_pyi.log" 2>&1; then
    echo "obsolete semantic-gate environment variable must not allow a Python stub" >&2
    exit 1
fi
grep -Fq 'duplicate Python module export name "value": public module names must be unique' "$WORK/duplicate_pyi.log"
test ! -s "$WORK/duplicate.pyi"

mkdir -p "$WORK/tmp"
if TMPDIR="$WORK/tmp" ELISA_STAGE1_NO_SEMANTIC_GATE=1 bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/duplicate_export.so" \
    "$ROOT/test/repro/pymodule_duplicate_export.elisa" >"$WORK/duplicate_so.log" 2>&1; then
    echo "duplicate Python module export must not produce an extension" >&2
    exit 1
fi
grep -Fq 'duplicate Python module export name "value": public module names must be unique' "$WORK/duplicate_so.log"
test ! -e "$WORK/duplicate_export.so"
leftover_pymodule_work="$(find "$WORK/tmp" -mindepth 1 -maxdepth 1 -type d -name 'elisa-pymodule-*' -print -quit)"
test -z "$leftover_pymodule_work"

echo "pymodule reserved-export diagnostic OK"
