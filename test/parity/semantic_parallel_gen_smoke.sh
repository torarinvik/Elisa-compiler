#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 "$ROOT/scripts/test_semantic_parallel_gen.py"
python3 "$ROOT/scripts/semantic_parallel_gen.py" --check
