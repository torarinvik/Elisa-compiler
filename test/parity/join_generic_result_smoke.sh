#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
SOURCE="$ROOT/test/repro/join_generic_result.elisa"
source "$ROOT/test/parity/run_timeout.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-join-generic-result.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for optimization in 0 2; do
	output="$WORK/join-O$optimization"
	bash "$WRAPPER" "-O$optimization" -emit exe -o "$output" "$SOURCE"
	elisa_run_timeout 20 "$output"
done

echo "generic join result smoke OK: scalar and aggregate join results emit at O0/O2"
