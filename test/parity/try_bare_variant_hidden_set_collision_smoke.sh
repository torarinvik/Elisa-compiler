#!/usr/bin/env bash
# A hidden sibling error set must not shadow a visible bare error variant.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/try_bare_variant_hidden_set_collision.elisa"
report="$("$RPT" < "$FIXTURE")"
rows="$(printf '%s\n' "$report" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L22
EOF
)"

grep -q '^D 1$' <<< "$report" || {
  printf 'bare-variant visibility smoke expected one controlled Try mismatch:\n%s\n' "$report" >&2
  exit 1
}
[[ "$rows" == "$expected_rows" ]] || {
  printf 'bare-variant visibility smoke diagnostics differ:\n%s\n%s\n' "$rows" "$report" >&2
  exit 1
}
grep -q 'cannot propagate Fault from a function returning Other' <<< "$report" || {
  printf 'hidden sibling errorset shadowed the visible bare variant:\n%s\n' "$report" >&2
  exit 1
}

printf 'bare-variant hidden-set visibility smoke OK\n'
