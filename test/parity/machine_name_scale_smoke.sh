#!/usr/bin/env bash
# Synthesized machine names must remain unique beyond the historical 0..255 table.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-machine-name-scale.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

{
  printf 'def machine_name_scale(input: i64) -> i64:\n'
  for index in $(seq 0 299); do
    printf '    machine over input:\n'
    printf '        state Only_%s\n' "$index"
    printf '        start Only_%s\n' "$index"
    printf '        Only_%s, _:\n' "$index"
    printf '            break\n'
  done
  printf '    return 0\n'
} >"$WORK/scale.elisa"

out="$("$RPT" <"$WORK/scale.elisa")"
echo "$out" | grep -q '^P 0$' || {
  echo "machine-name scale smoke FAIL: parse errors" >&2
  echo "$out" >&2
  exit 1
}
echo "$out" | grep -q '^D 0$' || {
  echo "machine-name scale smoke FAIL: synthesized names collided above 255" >&2
  echo "$out" >&2
  exit 1
}

echo "machine-name scale smoke OK: 300 synthesized machine enums are unique"
