#!/usr/bin/env bash
# Loop semantic checks smoke test for stage1.
#
# Tests the stage1 semantic layer's checks for:
# 1. Non-iterable for loop sources (NonIterableLoop)
# 2. Non-bool while conditions (NonBoolCondition with while loops)
#
# Builds loop_smoke.elisa (which includes the semantic layer), links it with a C driver,
# and validates the counts of each diagnostic kind.
#
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

source "$REPO_ROOT/test/parity/resolve_elisac.sh"

command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

FIX="$REPO_ROOT/test/parity/loop_smoke.elisa"
[[ -f "$FIX" ]] || { echo "error: missing loop smoke fixture: $FIX" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/driver.c" <<'EOF'
#include "loop_smoke.h"
#include <stdint.h>
#include <stdio.h>

int main(void) {
    /* Test code with expected diagnostics:
       - 4 NonIterableLoop (for x in n, for item in f, for flag in b, for f in flag)
       - 2 NonBoolCondition while (while n, while x)
    */
    const char *src =
        "def invalid_loop_int() -> void:\n"
        "    n: int = 42\n"
        "    for x in n:\n"
        "        pass\n"
        "\n"
        "def invalid_loop_float() -> void:\n"
        "    f: f32 = 3.14\n"
        "    for item in f:\n"
        "        pass\n"
        "\n"
        "def invalid_loop_bool() -> void:\n"
        "    b: bool = true\n"
        "    for flag in b:\n"
        "        pass\n"
        "\n"
        "def invalid_while_int() -> void:\n"
        "    n: int = 5\n"
        "    while n:\n"
        "        n <- n - 1\n"
        "\n"
        "def invalid_while_float() -> void:\n"
        "    x: f32 = 1.0\n"
        "    while x:\n"
        "        x <- x - 0.1\n"
        "\n"
        "def loop_combination() -> void:\n"
        "    a: darray[int] = []\n"
        "    for v in a:\n"
        "        pass\n"
        "    flag: bool = false\n"
        "    for f in flag:\n"
        "        pass\n";
    size_t n = 0; while (src[n]) n++;
    uint64_t non_iter = 0, non_bool = 0;
    loop_probe_export((uint8_t *)src, n, &non_iter, &non_bool);
    printf("%llu %llu\n", (unsigned long long)non_iter, (unsigned long long)non_bool);
    return 0;
}
EOF

"$ELISACORE_BIN" -emit header -o "$WORK/loop_smoke.h" "$FIX" >/dev/null
"$ELISACORE_BIN" -emit obj -permissive -O2 -o "$WORK/loop_smoke.o" "$FIX" >/dev/null

link_flags=(-O2 -I "$WORK" "$WORK/driver.c" "$WORK/loop_smoke.o" -o "$WORK/run")
[[ "$(uname -s)" == "Darwin" ]] && link_flags=(-Wl,-undefined,dynamic_lookup "${link_flags[@]}")
[[ "$(uname -s)" == "Linux" ]] && link_flags=(-no-pie "${link_flags[@]}")
clang "${link_flags[@]}"

read -r got_non_iter got_non_bool < <("$WORK/run")

# Expected: 4 NonIterableLoop + 2 NonBoolCondition (while)
if [[ "$got_non_iter" != "4" || "$got_non_bool" != "2" ]]; then
    echo "loop smoke FAILED: NonIterableLoop=$got_non_iter (want 4), NonBoolCondition=$got_non_bool (want 2)" >&2
    exit 1
fi

echo "loop smoke OK: NonIterableLoop=$got_non_iter NonBoolCondition=$got_non_bool" >&2
