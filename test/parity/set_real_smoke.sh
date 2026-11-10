#!/usr/bin/env bash
# Compile and execute each real stdlib case through both compiler drivers.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/real_std_runtime_cases.sh"
cat > "$WORK/ctx_streq.c" <<'C'
#include <string.h>
_Bool ctx_streq(const char *left, const char *right) {
    return strcmp(left, right) == 0;
}
C
clang -c "$WORK/ctx_streq.c" -o "$WORK/ctx_streq.o"
link_inputs=("$WORK/profile_hooks.o" "$WORK/ctx_streq.o")

set_case() {
    real_std_runtime_case "collections.elisa" "$@" "${link_inputs[@]}"
}

# Literal build + membership hit: {1,2,3}, probe for 2 -> present.
set_case member_hit 'def main() -> i64:
    s: mutable set[i64] = {1, 2, 3}
    return 42 if 2 in s else 7' 42
# Membership miss: 9 not inserted.
set_case member_miss 'def main() -> i64:
    s: mutable set[i64] = {1, 2, 3}
    return 42 if 9 in s else 7' 7
# Empty set: nothing is a member.
set_case empty_miss 'def main() -> i64:
    s: mutable set[i64] = {}
    return 42 if 9 in s else 7' 7
# All three literal elements are individually present (distinct hash probes).
set_case all_present 'def main() -> i64:
    s: mutable set[i64] = {10, 20, 30}
    hit: mutable i64 = 0
    if 10 in s:
        hit <- hit + 1
    if 20 in s:
        hit <- hit + 1
    if 30 in s:
        hit <- hit + 1
    return hit' 3
# Set COMPREHENSION `{x for x in LOW..<HIGH}`: a zeroed DynSet + one
# arena_set_add_or_panic per iteration. Members {1,2,3,4}: 2 and 4 present, 9 absent.
set_case comprehension 'def main() -> i64:
    s: mutable set[i64] = {x for x in 1..<5}
    hit: mutable i64 = 0
    if 2 in s:
        hit <- hit + 1
    if 4 in s:
        hit <- hit + 1
    if 9 in s:
        hit <- hit + 1
    return 42 if hit == 2 else 7' 42
# Filtered comprehension `{x for x in … if COND}`: only x in {7,8,9} added.
set_case comprehension_filter 'def main() -> i64:
    s: mutable set[i64] = {x for x in 0..<10 if x > 6}
    return 42 if (7 in s) and not (3 in s) else 7' 42
# Comprehension over an existing DARRAY source (not a range).
set_case comprehension_over_darray 'def main() -> i64:
    xs: darray[i64] = [3, 5, 7]
    s: mutable set[i64] = {x * 2 for x in xs}
    return 42 if (10 in s) and not (3 in s) else 7' 42

real_std_runtime_summary "set_real_smoke"
