#!/usr/bin/env bash
# Parser-generated names longer than the name store's spare room.
#
# removed_sentence / standalone_layout_sentence reserved the shared name store ONCE and then
# appended; the handler / effect-clone / typestate / protocol writers did the same on
# handler_name_storage. A name larger than the spare room grew the buffer, which can move it
# under every earlier sview. Every writer now calls name_store_make_room /
# handler_store_make_room, which retire a full buffer (never freed) and start a fresh one.
#
# This is a REGRESSION GUARD, not a fail-before reproducer: arena_realloc never reclaims a
# moved block (docs/84), so on today's runtime the old bytes stay readable and 0033fbcc passes
# too (also with the reclaim path scribbling freed spans). It fails the moment either the
# runtime starts reusing moved blocks or a writer appends past its room into a reclaimed span.
# Inputs carry 100k-700k byte names; the diagnostic text (which echoes the stored name) and a
# run of the handler program must come out intact.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
[ -x "$BIN" ] || { echo "long_generated_name FAIL: no stage1 binary" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
python3 - "$TMP" <<'PY'
import sys
d = sys.argv[1]
pad = "".join(f"    v{i}: i32 = {i}\n" for i in range(5000))
b = "b" * 400000
open(f"{d}/shorthand.elisa", "w").write(
    f"def f(a: i32, {b}: i32) -> i32:\n    return a\n\ndef main() -> i32:\n{pad}"
    f"    a: i32 = 1\n    {b}: i32 = 2\n    return f(a:, {b}:)\n")
q = "Q" * 700000
open(f"{d}/layout.elisa", "w").write(f"def main() -> i32:\n{pad}    return 0\nlayout {q}\n")
h = "H" * 100000
op = "p" * 100000
open(f"{d}/handler.elisa", "w").write(
    f"effect Tick:\n    def {op}() -> void\n\nhandler static {h}() for Tick:\n"
    f"    def {op}() -> void:\n        resume()\n\ndef main() -> i32:\n{pad}"
    f"    can Tick with {h}:\n        Tick.{op}()\n    return 0\n")
PY
fail=0
check_diag() { # file char length
    "$BIN" -emit llvm "$TMP/$1.elisa" -o "$TMP/$1.ll" >"$TMP/$1.err" 2>&1; rc=$?
    n="$(python3 -c 'import sys; print(open(sys.argv[1]).read().count(sys.argv[2] * int(sys.argv[3])))' "$TMP/$1.err" "$2" "$3")"
    if [ "$rc" -ne 1 ] || [ "$n" = 0 ]; then
        echo "long_generated_name FAIL: $1 rc=$rc, no intact copy of the long name in the diagnostic" >&2; fail=1
    fi
}
check_diag shorthand b 400000
check_diag layout Q 700000
RT="$ROOT/build/runtime/elisacore_runtime.o"
[ -f "$RT" ] || { echo "long_generated_name FAIL: no runtime object" >&2; exit 1; }
if ! { "$BIN" -emit obj -O0 "$TMP/handler.elisa" -o "$TMP/handler.o" && clang -Wl,-dead_strip -o "$TMP/handler" "$TMP/handler.o" "$RT"; } >"$TMP/h.log" 2>&1; then
    echo "long_generated_name FAIL: handler program did not build" >&2; head -c 2000 "$TMP/h.log" >&2; fail=1
else
    "$TMP/handler"; hrc=$?
    [ "$hrc" -eq 0 ] || { echo "long_generated_name FAIL: handler program exited $hrc" >&2; fail=1; }
fi
[ "$fail" -eq 0 ] && echo "long_generated_name OK: shorthand, layout and handler names intact"
exit "$fail"
