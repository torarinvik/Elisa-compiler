#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
if command -v gtimeout >/dev/null 2>&1; then
  exec gtimeout -k 1s 29s python3 "$ROOT/test/parity/gate_cache_key_smoke.py"
fi
exec timeout 29s python3 "$ROOT/test/parity/gate_cache_key_smoke.py"
