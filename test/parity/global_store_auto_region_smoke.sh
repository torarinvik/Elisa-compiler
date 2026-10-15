#!/usr/bin/env bash
# Values stored into module globals (and everything reachable from them) must not be
# allocated in the storing function's auto region, which is freed at return.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/scripts/platform.sh"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
[[ -x "$STAGE1" ]] || { echo "global-store auto-region smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
cd "$ROOT"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-global-store.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
for fixture in global_store_auto_region global_store_region_handoff; do
    for opt in 0 2; do
        "$STAGE1" -emit exe "-O$opt" -o "$WORK/$fixture.p$opt" "$ROOT/test/parity/fixtures/$fixture.elisa" >"$WORK/log" 2>&1 || { cat "$WORK/log" >&2; echo "global-store auto-region smoke FAIL: $fixture compile O$opt" >&2; exit 1; }
        rc=0; "$WORK/$fixture.p$opt" || rc=$?
        [[ "$rc" -eq 42 ]] || { echo "global-store auto-region smoke FAIL: $fixture O$opt exit $rc, want 42 (globals read freed memory)" >&2; exit 1; }
    done
done
# Instrument the generated code too: the by-value handoff must remain live after
# the caller's short-lived region is freed, not merely happen to retain readable
# bytes in an ordinary build.
"$STAGE1" -emit llvm -O0 -o "$WORK/asan.ll" "$ROOT/test/parity/fixtures/global_store_region_handoff.elisa" >"$WORK/asan-emit.log" 2>&1 || { cat "$WORK/asan-emit.log" >&2; echo "global-store auto-region smoke FAIL: ASan IR emit" >&2; exit 1; }
"$CLANG" -O1 -g -fsanitize=address -fno-omit-frame-pointer $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS "$WORK/asan.ll" "$ROOT/build/runtime/elisacore_runtime.o" -o "$WORK/asan" >"$WORK/asan-link.log" 2>&1 || { cat "$WORK/asan-link.log" >&2; echo "global-store auto-region smoke FAIL: ASan link" >&2; exit 1; }
rc=0; ASAN_OPTIONS=detect_leaks=0 "$WORK/asan" || rc=$?
[[ "$rc" -eq 42 ]] || { echo "global-store auto-region smoke FAIL: ASan exit $rc, want 42 (global retained caller-region storage)" >&2; exit 1; }
echo "global-store auto-region smoke OK"
