#!/usr/bin/env bash
# A compiler must DIAGNOSE malformed input, never crash on it — see the header of
# test/breadth/malformed_input_fuzz.py for what this found and why nothing else could.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ] || { echo "malformed_input SKIP: no stage1 binary"; exit 0; }
out="$(REPO_ROOT="$ROOT" python3 "$ROOT/test/breadth/malformed_input_fuzz.py" 2>&1)"
status=$?
if [ "$status" -ne 0 ]; then
    echo "$out" >&2
    echo "malformed_input FAILED: stage1 crashed on input it should have diagnosed" >&2
    exit 1
fi
echo "malformed_input OK: $(echo "$out" | tail -1)"
