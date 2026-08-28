#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/top-level.c" \
    "$ROOT/test/repro/pymodule_unsupported_view.elisa" >"$WORK/top-level-c.log" 2>&1; then
    echo "unsupported view element unexpectedly compiled in pymodule-c mode" >&2
    exit 1
fi
grep -Fq 'the view element contains an unsupported Python aggregate shape' "$WORK/top-level-c.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/top-level.json" \
    "$ROOT/test/repro/pymodule_unsupported_view.elisa" >"$WORK/top-level-manifest.log" 2>&1; then
    echo "unsupported view element unexpectedly compiled in pymodule manifest mode" >&2
    exit 1
fi
grep -Fq 'the view element contains an unsupported Python aggregate shape' "$WORK/top-level-manifest.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/recursive.c" \
    "$ROOT/test/repro/pymodule_recursive_view.elisa" >"$WORK/recursive-c.log" 2>&1; then
    echo "recursive view unexpectedly compiled in pymodule-c mode" >&2
    exit 1
fi
grep -Fq 'the named struct contains an unsupported Python aggregate shape' "$WORK/recursive-c.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/recursive.json" \
    "$ROOT/test/repro/pymodule_recursive_view.elisa" >"$WORK/recursive-manifest.log" 2>&1; then
    echo "recursive view unexpectedly compiled in pymodule manifest mode" >&2
    exit 1
fi
grep -Fq 'the named struct contains an unsupported Python aggregate shape' "$WORK/recursive-manifest.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/recursive-branching.c" \
    "$ROOT/test/repro/pymodule_recursive_branching.elisa" >"$WORK/recursive-branching-c.log" 2>&1; then
    echo "branching recursive struct unexpectedly compiled in pymodule-c mode" >&2
    exit 1
fi
grep -Fq 'the named struct contains an unsupported Python aggregate shape' "$WORK/recursive-branching-c.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/recursive-branching.json" \
    "$ROOT/test/repro/pymodule_recursive_branching.elisa" >"$WORK/recursive-branching-manifest.log" 2>&1; then
    echo "branching recursive struct unexpectedly compiled in pymodule manifest mode" >&2
    exit 1
fi
grep -Fq 'the named struct contains an unsupported Python aggregate shape' "$WORK/recursive-branching-manifest.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/nested.c" \
    "$ROOT/test/repro/pymodule_unsupported_nested_view.elisa" >"$WORK/nested-c.log" 2>&1; then
    echo "nested darray view unexpectedly compiled in pymodule-c mode" >&2
    exit 1
fi
grep -Fq 'supports nested darray dictionary values up to eight levels with representable aggregate elements' "$WORK/nested-c.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/nested.json" \
    "$ROOT/test/repro/pymodule_unsupported_nested_view.elisa" >"$WORK/nested-manifest.log" 2>&1; then
    echo "nested darray view unexpectedly compiled in pymodule manifest mode" >&2
    exit 1
fi
grep -Fq 'supports nested darray dictionary values up to eight levels with representable aggregate elements' "$WORK/nested-manifest.log"

echo "pymodule unsupported view diagnostics OK"
