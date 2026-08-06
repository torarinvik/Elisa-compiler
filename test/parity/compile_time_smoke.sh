#!/usr/bin/env bash
# Compile-time regression guard — see test/breadth/compile_cpu_time.py for why it measures CPU
# time rather than wall time, and what a slowdown looks like when nothing is watching for one.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ] || { echo "compile_time SKIP: no stage1 binary"; exit 0; }
out="$(REPO_ROOT="$ROOT" python3 "$ROOT/test/breadth/compile_cpu_time.py" 2>&1)"
status=$?
echo "$out"
[ "$status" -eq 0 ] || exit 1
echo "compile_time OK"
