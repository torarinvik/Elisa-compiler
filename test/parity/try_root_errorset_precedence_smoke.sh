#!/usr/bin/env bash
# A root error-set name wins Core's exact-name lookup before a nested same-named set.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/try_root_errorset_precedence.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || {
  printf 'root error-set precedence smoke expected one controlled Try mismatch:\n%s\n' "$stage0_output" >&2
  exit 1
}

stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L14
EOF
)"

[[ "$stage0_rows" == "$expected_rows" ]] || {
  printf 'Stage0 root error-set precedence diagnostics differ:\n%s\n%s\n' "$stage0_rows" "$stage0_output" >&2
  exit 1
}
[[ $(grep -cF "$FIXTURE:" <<< "$stage0_output") == 1 ]] || {
  printf 'Stage0 reported an unexpected diagnostic count:\n%s\n' "$stage0_output" >&2
  exit 1
}
grep -q 'cannot propagate Clash from a function returning LocalShadow.Clash' <<< "$stage0_output" || {
  printf 'Stage0 did not preserve the root ErrorSet as the source identity:\n%s\n' "$stage0_output" >&2
  exit 1
}
grep -q '^D 1$' <<< "$stage1_output" || {
  printf 'Stage1 reported an unexpected diagnostic count:\n%s\n' "$stage1_output" >&2
  exit 1
}
[[ "$stage1_rows" == "$expected_rows" ]] || {
  printf 'Stage1 root error-set precedence diagnostics differ:\n%s\n%s\n' "$stage1_rows" "$stage1_output" >&2
  exit 1
}
grep -q 'cannot propagate Clash from a function returning LocalShadow.Clash' <<< "$stage1_output" || {
  printf 'Stage1 did not preserve the root ErrorSet as the source identity:\n%s\n' "$stage1_output" >&2
  exit 1
}

printf 'root error-set precedence smoke OK: bare and qualified declarations remain distinct\n'
