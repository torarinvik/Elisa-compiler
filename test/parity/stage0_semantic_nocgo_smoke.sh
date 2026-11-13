#!/usr/bin/env bash
# The semantic analyzer is pure Go and must remain buildable without cgo.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
cd "$CORE/compiler"
CGO_ENABLED=0 go build ./src/semantic
echo "Stage0 semantic package builds without cgo"
