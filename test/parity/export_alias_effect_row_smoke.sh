#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="$ROOT/test/repro/export_alias_with_effects.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-export-alias-effects.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh"
for optimization in 0 2; do
	output="$WORK/export-alias-O$optimization"
	bash "$ROOT/scripts/elisac_stage1.sh" "-O$optimization" -emit exe -o "$output" "$FIXTURE"
	"$output"
done

echo "export alias effect-row smoke OK: O0/O2 target selection and execution"
