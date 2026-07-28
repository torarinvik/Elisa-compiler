#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/scripts/easm_relation_property.py" --cases 200 || {
    echo "easm_relation_property_smoke FAILED"
    exit 1
}
echo "easm_relation_property_smoke OK"
