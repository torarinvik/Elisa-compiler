#!/usr/bin/env bash
# Behavioral smoke for docs/119 expression-unification forms (stage1 parity with
# stage0): bare block expressions, multi-line if/match value forms, loop-expression
# headers `|acc = 0| -> yield` with `|capture|`, and the `rebind` statement. Each must
# parse with zero parse errors, resolve cleanly, and flag an undefined identifier inside the
# new construct — while a bitwise `|` in an iterable is never misread as a header, and
# there are zero parse false positives across the frontend + stdlib. The form
# contract is documented in docs/119_expression_unification.md.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "docs119-forms smoke FAIL: $1" >&2; exit 1; }
perr() { printf "$1" | "$RPT" | awk 'NR == 1 { print $2 }'; }

# 1. bare block expression parses.
[ "$(perr 'def f() -> i64:\n    y: i64 =\n        a: i64 = 40\n        a + 2\n    return y\n')" = "0" ] || fail "bare block has parse errors"

# 2. multi-line if value form parses.
[ "$(perr 'def f(n: i64) -> i64:\n    r: i64 =\n        if n > 0:\n            1\n        else:\n            0\n    return r\n')" = "0" ] || fail "if-value form has parse errors"

# 3. loop-expression header (fold) parses.
[ "$(perr 'def f(xs: darray[i64]) -> i64:\n    s: i64 =\n        for x in xs |acc = 0| -> acc:\n            acc <- acc + x\n    return s\n')" = "0" ] || fail "loop header has parse errors"

# 4. loop header with a capture parses.
[ "$(perr 'def f(xs: darray[i64]) -> i64:\n    t: mutable i64 = 0\n    r: i64 =\n        for x in xs |acc = 0, t| -> acc:\n            t <- t + x\n            acc <- acc + 1\n    return t + r\n')" = "0" ] || fail "capture header has parse errors"

# 5. rebind parses.
[ "$(perr 'def f(p: mutable i64, v: i64) -> i64:\n    rebind p, applied: i64 =\n        p + v, v\n    return p + applied\n')" = "0" ] || fail "rebind has parse errors"

# 5b. a typed loop accumulator `|acc: u64 = 0|` parses.
[ "$(perr 'def f(xs: darray[i64]) -> u64:\n    s: u64 =\n        for x in xs |acc: u64 = 0| -> acc:\n            acc <- acc + 1\n    return s\n')" = "0" ] || fail "typed accumulator has parse errors"

# 5c. a captured value block `x: T = |caps|` NEWLINE INDENT … parses (docs/119 §6
#     applied to value blocks — the header licenses outer-mutable mutation, E4).
[ "$(perr 'def f(t: mutable i64) -> i64:\n    v: i64 = |t|\n        t <- t + 1\n        t\n    return v\n')" = "0" ] || fail "captured value block has parse errors"

# 5d. two captures + tuple-bind form parses.
[ "$(perr 'def f(a: mutable i64, b: mutable i64) -> i64:\n    x, y = |a, b|\n        a <- a + 1\n        b <- b + 1\n        a, b\n    return x + y\n')" = "0" ] || fail "multi-capture tuple value block has parse errors"

# 6. a bitwise `|` in an iterable is NOT misread as a header.
[ "$(perr 'def f(a: i64, b: i64) -> i64:\n    s: mutable i64 = 0\n    for x in 0..<(a | b):\n        s <- s + x\n    return s\n')" = "0" ] || fail "bitwise | in iterable misread as header"

# 7. resolution descends into the new constructs: an undefined identifier in a block/loop-
#    header body is flagged.
out=$(printf 'def f(xs: darray[i64]) -> i64:\n    s: i64 =\n        for x in xs |acc = 0| -> acc:\n            acc <- acc + nope\n    return s\n' | "$RPT")
grep -q "undefined identifier \"nope\"" <<< "$out" || fail "loop-header body not resolved: $out"

# 8. zero parse false positives across frontend + stdlib.
# Some files are include fragments or use declarations from earlier includes. Check
# those in the complete driver as well, and require every such file to be present in
# the expansion rather than dropping it from the corpus.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
: > "$WORK/context-files"
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | awk 'NR == 1 && $1 == "P" { print $2 }')
  status=$?
  [ "$status" -eq 0 ] || fail "parse reporter failed on $f (exit $status)"
  case "$c" in ''|*[!0-9]*) fail "invalid parse report on $f" ;; esac
  if [ "$c" -ne 0 ]; then
    printf '%s\n' "$f" >> "$WORK/context-files"
  fi
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa')
if [ "$t" -ne 0 ]; then
  python3 "$REPO_ROOT/scripts/expand_source_probe.py" "$REPO_ROOT/src/driver/elisac.elisa" "$WORK/driver.elisa" "$WORK/driver-map.json" || fail "cannot expand driver includes"
  python3 - "$WORK/context-files" "$WORK/driver-map.json" <<'PY' || fail "a source with standalone parse errors was not covered by the driver expansion"
import json
from pathlib import Path
import sys

covered = {Path(row["source"]).resolve() for row in json.loads(Path(sys.argv[2]).read_text())}
missing = [Path(line).resolve() for line in Path(sys.argv[1]).read_text().splitlines() if Path(line).resolve() not in covered]
for path in missing:
    print(f"  source missing from driver expansion: {path}", file=sys.stderr)
if missing:
    sys.exit(1)
PY
  printf 'using Ast\ninclude "%s"\n' "$REPO_ROOT/test/breadth/parse_probe.elisa" > "$WORK/parse-probe.elisa"
  "$STAGE1_BIN" -emit obj -O0 -permissive -o "$WORK/parse-probe.o" "$WORK/parse-probe.elisa" > "$WORK/probe-build.log" 2>&1 || { cat "$WORK/probe-build.log" >&2; fail "cannot build parser probe"; }
  probe_link_flags=()
  case "$(uname -s)" in
    Darwin) probe_link_flags=(-Wl,-undefined,dynamic_lookup -Wl,-stack_size,0x20000000) ;;
    Linux) probe_link_flags=(-no-pie) ;;
  esac
  clang -O2 "${probe_link_flags[@]}" "$WORK/parse-probe.o" "$RUNTIME_OBJ" "$REPO_ROOT/test/parity/profile_hooks.c" -o "$WORK/parse-probe" || fail "cannot link parser probe"
  if ! probe_output="$("$WORK/parse-probe" < "$WORK/driver.elisa")"; then
    printf 'Sources requiring include context:\n' >&2
    cat "$WORK/context-files" >&2
    fail "expanded driver has parse errors: $probe_output"
  fi
  [[ "$probe_output" == errors=0\ * ]] || fail "unexpected parser probe output: $probe_output"
fi

echo "docs119-forms smoke OK: bare block / if-value / loop headers / capture / rebind parse + resolve, bitwise | safe, 0 FP"
