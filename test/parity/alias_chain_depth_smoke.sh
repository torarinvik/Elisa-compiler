#!/usr/bin/env bash
# A long valid alias chain is a positive control for cycle detection: it must not
# recurse through the chain, reject a valid type, or rescan the chain for every
# repeated annotation use.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
S0="${ELISA_STAGE0_BIN:-$ELISACORE_BIN}"
S1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$S0" || exit $?
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$S1" || exit $?
work="$(mktemp -d)"
trap 'status=$?; if [ "$status" -eq 0 ]; then rm -rf "$work"; else echo "alias chain logs retained at: $work" >&2; fi' EXIT

fail() { echo "alias chain depth FAIL: $1" >&2; exit 1; }
source="$work/long_valid_alias_chain.elisa"
count=1024
index=$((count - 1))
while [ "$index" -ge 0 ]; do
  current="Chain$(printf '%04d' "$index")"
  next_index=$((index + 1))
  if [ "$next_index" -lt "$count" ]; then
    target="Chain$(printf '%04d' "$next_index")"
  else
    target=i64
  fi
  printf 'type %s = %s\n' "$current" "$target" >>"$source"
  index=$((index - 1))
done
printf '\ndef long_valid_alias_chain(value: Chain0000) -> bool:\n    return true\n' >>"$source"
index=0
while [ "$index" -lt 512 ]; do
  printf 'const RepeatedUse%04d: Chain0000 = 0\n' "$index" >>"$source"
  index=$((index + 1))
done

rc=0
"$S0" -emit llvm -o /dev/null "$source" >"$work/long.s0" 2>&1 || rc=$?
[ "$rc" -eq 0 ] || fail "Stage0 rejected a 1024-link valid chain (exit $rc): $(tail -12 "$work/long.s0")"
rc=0
env -u ELISA_STAGE1_RUNTIME_STD "$S1" -emit llvm -o /dev/null "$source" >"$work/long.s1" 2>&1 || rc=$?
[ "$rc" -eq 0 ] || fail "Stage1 rejected a 1024-link valid chain (exit $rc): $(tail -12 "$work/long.s1")"
if grep -qF 'backend could not produce a linkable unit' "$work/long.s1" || grep -qF 'backend emitted no functions' "$work/long.s1"; then
  fail "Stage1 reached backend decline: $(tail -12 "$work/long.s1")"
fi
echo 'alias chain depth OK: 1024-link acyclic chain and 512 repeated uses accepted by Stage0 and Stage1'
