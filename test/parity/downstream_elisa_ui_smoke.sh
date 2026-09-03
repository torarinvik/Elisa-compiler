#!/usr/bin/env bash
# Compile a REAL DOWNSTREAM PROGRAM with this compiler.
#
# Every gate beside this one feeds the compiler either a fixture or its own
# source. Both are blind in the same direction: the compiler does not build a
# widget tree, so nothing else here exercises a packed hierarchy with `common:`
# fields, an `is` binding through a global, a sealed hierarchy that lowers
# inline, a const enum as a payload, or a C ABI boundary.
#
# Six stage1 bugs in four days were found by writing elisa-ui and not by this
# suite -- a common write with no store in scope (miscompiled to a segfault), a
# repeat `is` binding losing its type, a user module named `Backend`, `-g` on any
# program with modules, conversions into a const enum, and a module-qualified
# struct in an extern parameter, which was invisible until a C program linked
# against the dropped symbol. Each one is now pinned by its own fixture, but the
# fixtures were written AFTER the fact. This is the gate that would have caught
# them first.
#
# elisa-ui is a sibling checkout, not a submodule, so this SKIPS when it is
# absent rather than failing: a stage1 checkout on its own is still gateable.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UI="${ELISA_UI_DIR:-$ROOT/../../elisa-ui}"

[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ] || { echo "downstream_elisa_ui_smoke SKIP: no stage1 binary"; exit 0; }
[ -d "$UI" ] || { echo "downstream_elisa_ui_smoke SKIP: no elisa-ui checkout at $UI"; exit 0; }
[ -f "$UI/scripts/run_tests.sh" ] || { echo "downstream_elisa_ui_smoke SKIP: $UI has no run_tests.sh"; exit 0; }
[ -f "$ROOT/build/runtime/elisacore_runtime.o" ] || { echo "downstream_elisa_ui_smoke SKIP: no runtime object; run scripts/build_runtime_object.sh"; exit 0; }

# Two of the tests link SDL3. Without it the failure would be the host's, not the
# compiler's, so say which it is rather than reporting a red gate.
SDL_LIB="${ELISA_UI_SDL_LIB:-/opt/homebrew/lib}"
[ -e "$SDL_LIB/libSDL3.dylib" ] || [ -e "$SDL_LIB/libSDL3.so" ] || {
    echo "downstream_elisa_ui_smoke SKIP: no SDL3 in $SDL_LIB (set ELISA_UI_SDL_LIB)"; exit 0; }

log="$ROOT/build/downstream_elisa_ui.log"
mkdir -p "$ROOT/build"
if ELISA_UI_STAGE1="$ROOT" bash "$UI/scripts/run_tests.sh" >"$log" 2>&1; then
    passes="$(grep -c '^PASS' "$log" || true)"
    echo "downstream_elisa_ui_smoke OK: elisa-ui builds and passes ($passes tests plus the C link check)"
    exit 0
fi

echo "downstream_elisa_ui_smoke FAIL: elisa-ui does not build or pass against this compiler." >&2
echo "  This gate exists because the compiler's own source does not exercise what a UI does." >&2
echo "  A decline or a crash here is a compiler regression until shown otherwise; check that" >&2
echo "  the failure is not an elisa-ui change by building it against the pushed stage1." >&2
grep -iE "error|declined|FAIL|Segmentation" "$log" | head -8 | sed 's/^/    /' >&2
echo "  full log: $log" >&2
exit 1
