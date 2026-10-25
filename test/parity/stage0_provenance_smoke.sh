#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

# The provenance unit suite mocks `go build` and `go version -m`, so this gate
# exercises receipt creation and freshness checks without rebuilding Stage0.
python3 -B "$REPO_ROOT/scripts/test_stage0_provenance.py"
printf 'stage0 provenance smoke OK\n'
