#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# A non-generic overload whose parameter is `T&` is an EXACT match for a plain `T` argument
# and must beat a generic. exact_overload_row_matches compared Ref against the value kind, so
# a user `def has(m: dict[i64, i64]&, k: i64)` lost `has(m, k)` to the std's generic
# `has[T](items: Flags[T]&, value: T)` and aborted in flags_mask (stage0 calls the user
# function). Each fixture is compiled by stage0 AND stage1, linked, RUN, and exit codes must
# agree. The fixtures `include` the runtime source: linked without elisacore_runtime.o and
# with no-op profiler hooks + ctx_streq.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run_timeout.sh"
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISAC_STAGE1:-$ROOT/bin/elisac-stage1}"
S0="${ELISACORE_BIN:-$HOME/.elisac/elisac-stage0}"
DIR="$ROOT/test/fixtures/backend/overload_ref_exact"
# Not under /private/tmp: stage0 writes an empty object for those paths.
TMP="$(mktemp -d "$HOME/.overload_ref_exact.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/stub.c" <<'C'
#include <stdint.h>
#include <string.h>
void elisa_profile_allocation_event_v1(uint32_t a, uintptr_t b, size_t c, uintptr_t d, size_t e, uintptr_t f, size_t g) {}
uint32_t elisa_profile_allocation_negotiate(uint32_t v) { return 0; }
uint32_t elisa_profile_region_layout_negotiate(uint32_t v) { return 0; }
void elisa_profile_region_layout_v1(void) {}
_Bool ctx_streq(const char *a, const char *b) { return strcmp(a, b) == 0; }
C
clang -c "$TMP/stub.c" -o "$TMP/stub.o" || { echo "overload_ref_exact_smoke FAILED: stub"; exit 1; }
run_with() {
    local compiler="$1" src="$2" tag="$3"
    "$compiler" -emit obj "$src" -o "$TMP/$tag.o" >"$TMP/$tag.log" 2>&1 || { echo "compile-fail"; return; }
    [ -s "$TMP/$tag.o" ] || { echo "no-object"; return; }
    clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$TMP/$tag" "$TMP/$tag.o" "$TMP/stub.o" 2>/dev/null || { echo "link-fail"; return; }
    elisa_run_timeout 30 "$TMP/$tag" >/dev/null 2>&1; echo "rc=$?"
}
fail=0; n=0
for f in "$DIR"/*.elisa; do
    n=$((n + 1)); name="$(basename "$f" .elisa)"
    want="$(run_with "$S0" "$f" "s0_$name")"; got="$(run_with "$BIN" "$f" "s1_$name")"
    case "$want" in rc=*) ;; *) echo "FAIL $name: FIXTURE INVALID, stage0 $want"; fail=1; continue;; esac
    if [ "$want" != "$got" ]; then
        echo "FAIL $name: stage0 $want, stage1 $got"; grep -v 'warning:' "$TMP/s1_$name.log" | head -3; fail=1
    fi
done
[ $fail -eq 0 ] && echo "overload-ref-exact OK ($n fixtures run and agree with stage0)" || exit 1
