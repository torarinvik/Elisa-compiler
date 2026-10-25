#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_param_public_member_in_private_module.elisa"
report="$("$RPT" < "$FIXTURE")"
warning_rows="$(printf '%s\n' "$report" \
  | sed -n -E '/shadows the declared error set/s/^[[:space:]]+L([0-9]+) .*/L\1/p' \
  | LC_ALL=C sort)"
if [[ "$warning_rows" != 'L8' ]]; then
  printf 'errorset private-module visibility smoke failed; only the owning-module control at L8 should warn:\n%s\n' "$report" >&2
  exit 1
fi

printf 'errorset private-module visibility smoke OK\n'
