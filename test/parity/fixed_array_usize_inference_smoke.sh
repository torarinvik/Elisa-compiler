#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
POSITIVE="$ROOT/test/repro/fixed_array_usize_inference.elisa"
CONFLICT="$ROOT/test/repro/fixed_array_usize_extent_conflict.elisa"
MODEL="$ROOT/test/proofs/fixed_array_extent_model.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-fixed-array-usize.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh"
bash "$WRAPPER" -emit check "$MODEL"

for optimization in 0 2; do
	output="$WORK/inference-O$optimization"
	bash "$WRAPPER" "-O$optimization" -emit exe -o "$output" "$POSITIVE"
	"$output"
done

if bash "$WRAPPER" -O0 -emit exe -o "$WORK/conflict" "$CONFLICT" >"$WORK/conflict.log" 2>&1; then
	echo "conflicting inferred extents unexpectedly compiled" >&2
	exit 1
fi
if ! rg -q 'backend could not produce a linkable unit; declined [0-9]+: main@8 \(call expression\)' "$WORK/conflict.log"; then
	cat "$WORK/conflict.log" >&2
	echo "extent conflict was refused without the expected call diagnostic" >&2
	exit 1
fi

echo "fixed-array usize inference smoke OK: O0/O2, equal extents, conflict refusal"
