#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/scripts/easm_enforcement_fuzz.py" --cases 100 || {
    echo "easm_enforcement_fuzz_smoke FAILED"
    exit 1
}
echo "easm_enforcement_fuzz_smoke OK"
