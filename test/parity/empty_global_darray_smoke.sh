#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
POSITIVE="$ROOT/test/repro/empty_global_darray.elisa"
NEGATIVE="$ROOT/test/repro/nonempty_global_darray_refused.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-empty-global-darray.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for optimization in 0 2; do
	output="$WORK/empty-O$optimization"
	bash "$WRAPPER" "-O$optimization" -emit exe -o "$output" "$POSITIVE"
	"$output"
done

negative_output="$WORK/nonempty.log"
if bash "$WRAPPER" -emit obj -o "$WORK/nonempty.o" "$NEGATIVE" >"$negative_output" 2>&1; then
	echo "nonempty DArray global initializer unexpectedly compiled" >&2
	exit 1
fi
if ! rg -q 'global initializer nonempty' "$negative_output"; then
	cat "$negative_output" >&2
	echo "nonempty DArray was refused without the expected initializer diagnostic" >&2
	exit 1
fi

echo "empty global DArray initializer smoke OK: O0/O2 runtime and nonempty refusal"
