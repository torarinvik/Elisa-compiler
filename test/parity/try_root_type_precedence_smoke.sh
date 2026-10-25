#!/usr/bin/env bash
# A root nominal type wins Core's exact-name lookup before a nested alias.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/try_root_type_precedence.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || {
  printf 'root-type precedence smoke expected controlled type diagnostics:\n%s\n' "$stage0_output" >&2
  exit 1
}

stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: (.*)$#L\1 \2#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) (.*)$#L\1 \2#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L13 error union expects an error set on the right-hand side, got <invalid>
L13 unknown error set or variant "Clash"
L17 try requires a fallible expression, got <invalid>
EOF
)"

[[ "$stage0_rows" == "$expected_rows" ]] || {
  printf 'Stage0 root-type precedence diagnostics differ:\n%s\n%s\n' "$stage0_rows" "$stage0_output" >&2
  exit 1
}
[[ $(grep -c '^D 3$' <<< "$stage1_output") == 1 ]] || {
  printf 'Stage1 root-type precedence smoke expected three type diagnostics:\n%s\n' "$stage1_output" >&2
  exit 1
}
[[ "$stage1_rows" == "$expected_rows" ]] || {
  printf 'Stage1 root-type precedence diagnostics differ:\n%s\n%s\n' "$stage1_rows" "$stage1_output" >&2
  exit 1
}
if grep -q 'cannot propagate' <<< "$stage1_output"; then
  printf 'Try treated the nested alias as an ErrorSet despite the root nominal type:\n%s\n' "$stage1_output" >&2
  exit 1
fi

printf 'root nominal-type precedence smoke OK: nested aliases do not override the root name\n'
