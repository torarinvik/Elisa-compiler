#!/usr/bin/env bash
# Try's overload-family lookup must follow Core's first-argument + arity rule even
# when a later argument is accepted by optional-reference widening.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/try_overload_error_set_arg0_optional_ref.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || {
    echo "try overload arg0 optional-ref smoke failed: Stage0 accepted the mismatched destination" >&2
    exit 1
}
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|return type expects).*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L24
EOF
)"
[[ "$stage0_rows" == "$expected_rows" ]] || {
    echo "try overload arg0 optional-ref Stage0 diagnostics changed:\n$stage0_rows\n$stage0_output" >&2
    exit 1
}

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
grep -q '^D 1$' <<< "$stage1_output" || {
    echo "try overload arg0 optional-ref smoke expected one selected-overload diagnostic in Stage1:\n$stage1_output" >&2
    exit 1
}
[[ "$stage1_rows" == "$expected_rows" ]] || {
    echo "try overload arg0 optional-ref Stage1 diagnostics differ:\n$stage1_rows\n$stage1_output" >&2
    exit 1
}

echo "try overload arg0 optional-ref selection smoke OK"
