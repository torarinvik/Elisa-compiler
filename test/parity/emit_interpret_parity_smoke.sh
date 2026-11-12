#!/usr/bin/env bash
# `-emit interpret` — run the program and report `main`'s RESULT.
#
# stage0 interprets the AST; stage1 compiles and runs, which is observably the same. The
# return value cannot travel out through the process exit status (0-255, and stage0 prints
# 100000 exactly), so stage1 renames the module's `main` and synthesizes an entry point that
# prints the result — Backend::wrap_main_for_interpret.
#
# Shape, measured against stage0: an i64 `main` prints `[ result   ] <value>`; a void `main`
# prints NOTHING; a unit with no `main` reports
# `error: interpreter does not know function "main"` and exits 1; the program's own console
# output comes FIRST.
#
# Known interpreter defects are labelled below, but remain parity failures until the
# Stage0 interpreter is fixed.
set -uo pipefail
shopt -s nullglob

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

# frame_filter_contracts (2026-09-16): stage0's interpreter answers 0 where BOTH compilers'
# native backends answer 42 (measured: stage0 -emit obj + link + run = 42, stage1 = 42).
# local_binding_qualifier left this list 2026-09-22: `writable_view: mutable i64& = &second;
# writable_view <- 9` WRITES THROUGH under rule R (the TYPE's `mutable` is the write capability),
# so the native backends now answer 9 like stage0's interpreter always did.
EXPECTED_DIVERGENT="generic_default_argument uintptr_corpus_probe frame_filter_contracts"

same=0
differ=0
skipped=0
known=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    s0="$(timeout 25 "$ELISACORE_BIN" -emit interpret "$src" </dev/null 2>&1)"; rc0=$?
    if [ "$rc0" -ne 0 ]; then
        if [ "$rc0" -gt 2 ]; then
            differ=$((differ + 1))
            echo "FAIL: $name — Stage0 interpreter exited $rc0: $s0"
        else
            skipped=$((skipped + 1))
            echo "UNCOMPARABLE: $name — Stage0 rejected input (exit $rc0): $s0"
        fi
        continue
    fi
    s1="$(timeout 120 bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit interpret -o /dev/null "$src" 2>&1)"; rc1=$?
    # A 124 is retried with a wider budget before it is believed (the corpus harness's
    # rule): on a host running the 800 s native smoke beside this one, a paging stall
    # fabricates a DIFF for a product that answers in a second when idle. A genuine
    # runaway expires both budgets and is still reported.
    if [ "$rc1" -eq 124 ]; then
        s1="$(timeout 300 bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit interpret -o /dev/null "$src" 2>&1)"; rc1=$?
    fi
    if [ "$s0" == "$s1" ] && [ "$rc0" == "$rc1" ]; then
        same=$((same + 1)); continue
    fi
    if [[ " $EXPECTED_DIVERGENT " == *" $name "* ]]; then
        known=$((known + 1))
        differ=$((differ + 1))
        echo "KNOWN (stage1 correct, stage0 interpreter wrong): $name — stage0=[$s0] stage1=[$s1]"
        continue
    fi
    differ=$((differ + 1))
    echo "DIFF: $name — stage0(exit $rc0)=[$s0] stage1(exit $rc1)=[$s1]"
done

echo "emit_interpret: $same identical, $differ divergent (including $known known Stage0 bugs), $skipped Stage0-rejected"
[ "$((same + differ))" -ne 0 ] || { echo "emit_interpret parity FAILED: no comparable fixtures"; exit 1; }
[ "$differ" -eq 0 ] || { echo "emit_interpret parity FAILED"; exit 1; }
echo "emit_interpret parity OK"
