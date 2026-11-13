#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 -B "$ROOT/test/parity/test_compiler_rebuild_profile.py"
