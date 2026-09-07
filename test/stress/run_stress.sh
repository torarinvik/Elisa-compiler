#!/usr/bin/env bash
# Bounded, SEEDED stress of the module-private-state family through BOTH compilers (issue #4 of
# the 2026-09 correctness audit). Usage: test/stress/run_stress.sh [SEED] [COUNT]  (default 7, 15)
#
# A fresh corpus is generated per run into a temp dir (never a stale artifact). For each program:
#   good: stage0 -emit obj -O0 (oracle) and stage1 -emit obj; both link and EXECUTE; every program
#         asserts its own hand-computable values and returns 0; the two exit codes must agree.
#   bad:  a deliberately malformed variant (a private-global access): BOTH must reject it, and
#         stage1's first finding must be stage0's wording on the same line.
# A failure record keeps: the source (copied), the exact command, seed/index, both compiler
# revisions, the exit code and stderr, and a native backtrace when a compiler crashed (rc >= 128)
# and lldb is present. Classification is separate from failure: TOOL_MISSING (clang, node,
# runtime object, a compiler) exits 2 before any case runs; RESOURCE (timeout, ulimit kill) is
# counted apart from FAIL (wrong answer, wrong acceptance, crash).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SEED="${1:-7}"; COUNT="${2:-15}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"; RUNTIME="$ROOT/build/runtime/elisacore_runtime.o"
command -v clang >/dev/null || { echo "TOOL_MISSING clang"; exit 2; }
command -v python3 >/dev/null || { echo "TOOL_MISSING python3"; exit 2; }
[[ -x "$STAGE0" ]] || { echo "TOOL_MISSING stage0 at $STAGE0 (set ELISACORE_BIN)"; exit 2; }
[[ -f "$RUNTIME" ]] || { echo "TOOL_MISSING runtime object $RUNTIME"; exit 2; }
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-stress.XXXXXX")"; CORPUS="$WORK/corpus"; OUT="$WORK/out"; mkdir -p "$OUT"
python3 "$ROOT/test/stress/gen_module_private.py" "$SEED" "$COUNT" "$CORPUS" || { echo "TOOL_MISSING generator failed"; exit 2; }
S0REV="$(git -C "$(dirname "$STAGE0")" rev-parse --short HEAD 2>/dev/null || echo unknown)"; S1REV="$(git -C "$ROOT" rev-parse --short HEAD)"
pass=0; fail=0; resource=0
record() { # name class rc cmd
  cp "$CORPUS/$1.elisa" "$OUT/$1.elisa"
  printf 'name=%s class=%s rc=%s seed=%s stage0=%s stage1=%s\nsource=%s\ncmd=%s\n' "$1" "$2" "$3" "$SEED" "$S0REV" "$S1REV" "$OUT/$1.elisa" "$4" > "$OUT/$1.record"
  cat "$OUT/$1.err" >> "$OUT/$1.record" 2>/dev/null; echo "  $2 $1 (rc=$3)"; }
first_line() { sed -n 1p "$1" | sed 's/^[^:]*:\([0-9]*\):[^ ]* /\1 /'; }
for src in "$CORPUS"/*.elisa; do
  name="$(basename "$src" .elisa)"
  cmd0="timeout 120 '$STAGE0' -emit obj -O0 -o '$OUT/$name.s0.o' '$src'"
  bash -c "$cmd0" > "$OUT/$name.s0.err" 2>&1; rc0=$?
  cmd="ulimit -v 6000000 2>/dev/null; timeout 120 '$STAGE1' -emit obj -o '$OUT/$name.o' '$src'"
  bash -c "$cmd" > "$OUT/$name.err" 2>&1; rc=$?
  if [[ "$name" == *.bad ]]; then
    if [[ $rc -eq 124 || $rc -ge 137 ]]; then record "$name" RESOURCE $rc "$cmd"; resource=$((resource+1))
    elif [[ $rc0 -eq 0 ]]; then echo "stage0 ACCEPTED the malformed variant" >> "$OUT/$name.err"; record "$name" FAIL "$rc/$rc0" "$cmd0"; fail=$((fail+1))
    elif [[ $rc -ne 0 && "$(first_line "$OUT/$name.err")" == "$(first_line "$OUT/$name.s0.err")" ]]; then pass=$((pass+1))
    else echo "want: $(first_line "$OUT/$name.s0.err")" >> "$OUT/$name.err"; record "$name" FAIL $rc "$cmd"; fail=$((fail+1)); fi
    continue
  fi
  if [[ $rc -eq 124 || $rc -eq 137 ]]; then record "$name" RESOURCE $rc "$cmd"; resource=$((resource+1)); continue; fi
  if [[ $rc0 -ne 0 ]]; then cat "$OUT/$name.s0.err" >> "$OUT/$name.err"; record "$name" FAIL "stage0=$rc0" "$cmd0"; fail=$((fail+1)); continue; fi
  if [[ $rc -ne 0 ]]; then
    [[ $rc -ge 128 && -n "$(command -v lldb)" ]] && lldb --batch -o run -o bt -- "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" -emit obj -o "$OUT/$name.o" "$src" >> "$OUT/$name.err" 2>&1
    record "$name" FAIL $rc "$cmd"; fail=$((fail+1)); continue; fi
  clang -Wl,-dead_strip -o "$OUT/$name.s1" "$OUT/$name.o" "$RUNTIME" >> "$OUT/$name.err" 2>&1 || { record "$name" FAIL link "$cmd"; fail=$((fail+1)); continue; }
  clang -Wl,-dead_strip -o "$OUT/$name.s0" "$OUT/$name.s0.o" >> "$OUT/$name.err" 2>&1 || clang -Wl,-dead_strip -o "$OUT/$name.s0" "$OUT/$name.s0.o" "$RUNTIME" >> "$OUT/$name.err" 2>&1
  timeout 20 "$OUT/$name.s1"; r1=$?; timeout 20 "$OUT/$name.s0"; r0=$?
  if [[ $r1 -eq 0 && $r0 -eq 0 ]]; then pass=$((pass+1)); else echo "run: stage1=$r1 stage0=$r0" >> "$OUT/$name.err"; record "$name" FAIL "$r1/$r0" "$cmd"; fail=$((fail+1)); fi
done
echo "stress(seed=$SEED, count=$COUNT): $pass passed, $fail failed, $resource resource-limited; work dir $WORK"
[[ $fail -eq 0 && $resource -eq 0 ]] && rm -rf "$WORK"
[[ $fail -eq 0 && $resource -eq 0 ]]
