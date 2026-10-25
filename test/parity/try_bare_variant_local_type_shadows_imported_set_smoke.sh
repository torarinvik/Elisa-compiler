#!/usr/bin/env bash
# A local type shadows an imported same-named error set, leaving a unique bare variant.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/try_bare_variant_local_type_shadows_imported_set.elisa"
report="$("$RPT" < "$FIXTURE")"
rows="$(printf '%s\n' "$report" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L27
EOF
)"

grep -q '^D 1$' <<< "$report" || {
  printf 'local-type shadowing smoke expected one controlled Try mismatch:\n%s\n' "$report" >&2
  exit 1
}
[[ "$rows" == "$expected_rows" ]] || {
  printf 'local-type shadowing smoke diagnostics differ:\n%s\n%s\n' "$rows" "$report" >&2
  exit 1
}
grep -q 'cannot propagate Expected from a function returning Other' <<< "$report" || {
  printf 'Try did not resolve the bare variant after local type shadowing:\n%s\n' "$report" >&2
  exit 1
}

printf 'bare-variant local-type/import precedence smoke OK\n'
