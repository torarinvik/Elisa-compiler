#!/usr/bin/env bash
# Pure-Go analysis and the LLVM-unavailable backend stub must compile without cgo.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
cd "$CORE/compiler"
CGO_ENABLED=0 go build ./src/semantic ./src/backend
CGO_ENABLED=0 go test ./src/backendstubcheck -count=1
echo "Stage0 analysis and backend stub build without cgo"
