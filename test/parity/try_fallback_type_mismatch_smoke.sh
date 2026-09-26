#!/usr/bin/env bash
# `try CALL else FALLBACK` where FALLBACK is a `.cast[T]` whose T is not the call's payload
# type. stage0 rejects it as "try fallback expects EXPECTED, got ACTUAL"; stage1 used to let
# `try read_file(path) else "".cast[u8&]` through to the backend with no diagnostic.
#
# Two-compiler check: every case runs through both compilers and the exit codes must agree.
# A rejection must carry stage0's message, except where noted. Controls cover the shapes the
# check must stay silent on: matching types, numeric widening (stage0 accepts
# `i32` vs `.cast[i64]`) and an extern whose `-> u8&` return is side-tabled as a bare `u8`
# head (the check once read that head alone and rejected a matching `.cast[u8&]`).
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "try-fallback-type-mismatch smoke FAIL: $1" >&2; exit 1; }

S1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$S1" || exit $?
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

ERR='error Problem:\n    Failed\n\n'
G_I64='def g(x: i64) -> i64 error[Problem]:\n    raise Problem.Failed if x < 0\n    return x\n\n'

# case NAME WORDING(ignored when "-") SOURCE
case_() {
  local name="$1" wording="$2" src="$3" s0_out s1_out s0_rc s1_rc
  printf "${ERR}${src}" > "$work/$name.elisa"
  s0_out=$(cd "$work" && "$ELISACORE_BIN" -emit llvm -o /dev/null "$name.elisa" 2>&1); s0_rc=$?
  s1_out=$(cd "$work" && env -u ELISA_STAGE1_RUNTIME_STD "$S1" -emit llvm -o /dev/null "$name.elisa" 2>&1); s1_rc=$?
  [ "$s1_rc" = "$s0_rc" ] || fail "$name: stage1 rc=$s1_rc, stage0 rc=$s0_rc
stage0: $s0_out
stage1: $s1_out"
  [ "$wording" = "-" ] && return 0
  grep -qF "$wording" <<< "$s0_out" || fail "$name: stage0 no longer says '$wording': $s0_out"
  grep -qF "$wording" <<< "$s1_out" || fail "$name: stage1 lacks '$wording': $s1_out"
}

case_ def_mismatch 'try fallback expects i64, got u8&' \
  "${G_I64}"'def f(x: i64) -> i64:\n    v: i64 = try g(x) else "".cast[u8&]\n    return v\n\ndef main() -> i64:\n    return f(1)\n'
case_ paren_mismatch 'try fallback expects i64, got u8&' \
  "${G_I64}"'def f(x: i64) -> i64:\n    return try g(x) else ("".cast[u8&])\n\ndef main() -> i64:\n    return f(1)\n'
# stage1 spells the extern's expected side as its side-tabled head (`darray`, stage0 says
# `darray[u8]`), so this case gates the verdict only.
case_ extern_mismatch - \
  'extern read_it(path: cstr) -> darray[u8] error[Problem]\n\ndef f(path: cstr) -> i64:\n    data: darray[u8] = try read_it(path) else "".cast[u8&]\n    return data.count.i64()\n\ndef main() -> i64:\n    return 0\n'
case_ def_ref_match - \
  'def g(x: u8&) -> u8& error[Problem]:\n    raise Problem.Failed if x[0] == 0\n    return x\n\ndef f(x: u8&) -> u8&:\n    return try g(x) else "".cast[u8&]\n\ndef main() -> i64:\n    _ = f("a".cast[u8&])\n    return 0\n'
case_ numeric_widen - \
  'def g(x: i64) -> i32 error[Problem]:\n    raise Problem.Failed if x < 0\n    return 1\n\ndef f(x: i64) -> i32:\n    return try g(x) else x.cast[i64]\n\ndef main() -> i64:\n    return f(1).i64()\n'
case_ extern_ref_match - \
  'extern read_it(path: cstr) -> u8& error[Problem]\n\ndef f(path: cstr) -> u8&:\n    return try read_it(path) else "".cast[u8&]\n\ndef main() -> i64:\n    return 0\n'

# 0 findings across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -c "try fallback expects" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t try-fallback false positives across frontend+stdlib"

echo "try-fallback-type-mismatch smoke OK: 6 cases agree with stage0 (3 rejections, 3 controls), 0 FP across frontend+stdlib"
