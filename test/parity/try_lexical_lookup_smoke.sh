#!/usr/bin/env bash
# Try propagation lookup must follow lexical parents, visible imports, and alias prefixes.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try lexical lookup smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_lexical_lookup.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted incompatible propagations"

stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L15
L28
L51
L57
L69
L74
L90
L108
EOF
)"

[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 lexical/import diagnostics changed:\n$stage0_rows"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 lexical/import diagnostics differ:\n$stage1_rows"

shadow_line="$(rg -n '^                    return try shadow_load' "$FIXTURE" | cut -d: -f1)"
if printf '%s\n' "$stage1_rows" | grep -q "^L${shadow_line}$"; then
    fail "a nearer nonfallible declaration borrowed its parent's fallible family"
fi

mixed_line="$(rg -n '^            return try mixed' "$FIXTURE" | cut -d: -f1)"
if printf '%s\n' "$stage1_rows" | grep -q "^L${mixed_line}$"; then
    fail "a same-arity infallible overload borrowed its fallible sibling's family"
fi

grep -q 'try requires a fallible expression' <<< "$stage1_output" || fail "named-argument overload selection missed the infallible overload"

echo "try lexical lookup smoke OK: scopes, imports, aliases, arity and named overloads agree"
