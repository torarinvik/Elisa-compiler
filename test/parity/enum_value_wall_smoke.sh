#!/usr/bin/env bash
# Enum-to-enum value walls. A value that is firmly of enum `B` cannot be stored where enum
# `A` is expected unless `B`'s `is`-parent chain reaches `A`. stage0 rejects every shape
# below; stage1 used to reject none of them, and for a payload variant into a plain enum, or
# a parent value into a sub-enum slot, silently compiled a wrong program.
#
# Two-compiler check: every case runs through both compilers, exit codes must agree, and a
# rejection must carry stage0's first message. Controls: a sub-enum value into its parent
# (`S is A`, both directions of the call/let shapes) must stay silent.
#
# Deliberate declines (stage0 rejects, stage1 stays silent; not gated):
#   - a local spelled like the enum (`B: Bx = ...; v: A = B.P`): stage0 still resolves `B`
#     to the enum there, stage1 treats the local as shadowing it;
#   - a local of a PARENT enum into a sub-enum slot (`a: A` then `v: S = a`): a `match` arm
#     can narrow a local's declared type (docs/81), so a local is only judged across enums
#     that share no value.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "enum-value-wall smoke FAIL: $1" >&2; exit 1; }

S1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$S1" || exit $?
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

PRE='enum A:\n    X\n    Y\n\nenum B:\n    P\n    Q\n\nenum S is A:\n    Z\n\n'
MAIN='\ndef main() -> i64:\n    return 0\n'
rejections=0
controls=0

# case NAME WORDING("-" = must compile under both) BODY
case_() {
  local name="$1" wording="$2" src="$3" s0_out s1_out s0_rc s1_rc
  printf "${PRE}${src}${MAIN}" > "$work/$name.elisa"
  s0_out=$(cd "$work" && "$ELISACORE_BIN" -emit llvm -o /dev/null "$name.elisa" 2>&1); s0_rc=$?
  s1_out=$(cd "$work" && env -u ELISA_STAGE1_RUNTIME_STD "$S1" -emit llvm -o /dev/null "$name.elisa" 2>&1); s1_rc=$?
  [ "$s1_rc" = "$s0_rc" ] || fail "$name: stage1 rc=$s1_rc, stage0 rc=$s0_rc
stage0: $s0_out
stage1: $s1_out"
  if [ "$wording" = "-" ]; then
    [ "$s0_rc" = 0 ] || fail "$name: control rejected by stage0: $s0_out"
    controls=$((controls + 1))
    return 0
  fi
  grep -qF "$wording" <<< "$s0_out" || fail "$name: stage0 no longer says '$wording': $s0_out"
  grep -qF "$wording" <<< "$s1_out" || fail "$name: stage1 lacks '$wording': $s1_out"
  rejections=$((rejections + 1))
}

case_ direct 'variable "v" expects A, got B' \
  'def f() -> A:\n    v: A = B.P\n    return v\n'
case_ optional 'variable "v" expects A?, got B' \
  'def f() -> A?:\n    v: A? = B.P\n    return v\n'
case_ payload 'variable "v" expects A, got C' \
  'enum C:\n    K(n: i64)\n\ndef f() -> A:\n    v: A = C.K(n: 1)\n    return v\n'
case_ parent_into_sub 'variable "v" expects S, got A' \
  'def f() -> S:\n    v: S = A.X\n    return v\n'
case_ local 'variable "v" expects A, got B' \
  'def f(b: B) -> A:\n    v: A = b\n    return v\n'
case_ call_result 'variable "v" expects A, got B' \
  'def g() -> B:\n    return B.P\n\ndef f() -> A:\n    v: A = g()\n    return v\n'
case_ assign 'cannot assign B to A' \
  'def f() -> A:\n    v: mutable A = A.X\n    v <- B.P\n    return v\n'
case_ return 'return type expects A, got B' \
  'def f() -> A:\n    return B.P\n'
case_ return_match 'return type expects A, got B' \
  'def f(n: i64) -> A:\n    return match n:\n        0: B.P\n        _: B.Q\n'
case_ argument 'argument 1 to "g" expects A, got B' \
  'def g(a: A) -> i64:\n    return 1\n\ndef f() -> i64:\n    return g(B.P)\n'
case_ struct_field 'struct literal field "a" expects A, got B' \
  'struct H:\n    a: A\n\ndef f() -> H:\n    return H{a: B.P}\n'
case_ ternary_agree 'variable "v" expects A, got B' \
  'def f(c: bool) -> A:\n    v: A = B.P if c else B.Q\n    return v\n'
case_ ternary_disagree 'ternary branches are incompatible: B and A' \
  'def f(c: bool) -> A:\n    v: A = B.P if c else A.X\n    return v\n'
case_ match_agree 'variable "v" expects A, got B' \
  'def f(n: i64) -> A:\n    v: A = match n:\n        0: B.P\n        _: B.Q\n    return v\n'
case_ match_block_arm 'match expression arms are incompatible: B and A' \
  'def f(n: i64) -> A:\n    v: A = match n:\n        0:\n            t: i64 = n + 1\n            B.P\n        _: A.Y\n    return v\n'
case_ catch_arms 'catch expression arms are incompatible: A and B' \
  'error Problem:\n    Failed\n\ndef g(n: i64) -> A error[Problem]:\n    raise Problem.Failed if n < 0\n    return A.X\n\ndef f(n: i64) -> A:\n    v: A = catch g(n):\n        value: value\n        Problem.Failed: B.P\n    return v\n'
case_ sub_into_parent - \
  'def f() -> A:\n    v: A = S.Z\n    return v\n'
case_ sub_argument - \
  'def g(a: A) -> i64:\n    return 1\n\ndef f() -> i64:\n    return g(S.Z)\n'
case_ same_enum_match - \
  'def f(n: i64) -> A:\n    v: A = match n:\n        0: A.X\n        _: S.Z\n    return v\n'

# 0 findings across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE 'expects [A-Za-z_]+\??, got [A-Za-z_]+$|arms are incompatible|branches are incompatible|cannot assign [A-Za-z_]+ to' || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t enum-wall false positives across frontend+stdlib"

echo "enum-value-wall smoke OK: $((rejections + controls)) cases agree with stage0 ($rejections rejections, $controls controls), 0 FP across frontend+stdlib"
