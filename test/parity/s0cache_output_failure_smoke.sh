#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/test/parity/s0cache_output_failure_cases.py" "$ROOT/tools/s0cache"
