#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/qualified_constant_ambiguous.c" \
    "$ROOT/test/repro/pymodule_qualified_constant_ambiguous.elisa" >"$WORK/ambiguous.log" 2>&1; then
    echo "ambiguous qualified constant should be rejected by pymodule-c" >&2
    exit 1
fi
grep -Fq 'cannot disambiguate qualified constant target `Math::VERSION`' "$WORK/ambiguous.log"

echo "pymodule qualified-constant-ambiguous smoke OK"
