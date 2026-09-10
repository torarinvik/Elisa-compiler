#!/usr/bin/env bash
# Stage1 semantic regression: a generic reference-returning function must not expose its
# uninstantiated `T` row as a concrete caller type. The stage0 analyzer accepts this valid
# region-polymorphic call; stage1 must keep the structural compatibility check conservative.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RPT="${ELISA_PARSE_REPORT:-$ROOT/build/parse_report}"

[[ -x "$RPT" ]] || {
  echo "error: missing parse_report at $RPT (run a semantic parity check first)" >&2
  exit 2
}

output="$(awk 'BEGIN{on=1} on{print}' <<'ELISA_SOURCE' | "$RPT"
def id[T, @r](value: T& @r) -> T& @r:
	alias: T& @r = value
	return alias

def use(seed: i32) -> i32:
	region scratch(1024)
	value: i32& @scratch = new[scratch] seed + 1
	alias: i32& @scratch = id(value)
	return alias[0]
ELISA_SOURCE
)"

expected=$'P 0\nD 0'
if [[ "$output" != "$expected" ]]; then
  echo "generic region return smoke FAILED:" >&2
  printf '%s\n' "$output" >&2
  exit 1
fi

echo "generic region return smoke OK" >&2
