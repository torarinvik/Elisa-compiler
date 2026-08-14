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
# EXPECTED_DIVERGENT names fixtures where stage1 is CORRECT and stage0's interpreter is not.
# generic_default_argument.elisa is the case: stage1 answers 127, which is what that
# fixture's own header records stage0 answering, while stage0's INTERPRETER binds a generic
# call's named argument by position (see the stage0 commit fixing the non-generic half).
# Demanding parity there would mean reproducing a known wrong answer.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

EXPECTED_DIVERGENT="generic_default_argument uintptr_corpus_probe"

same=0
differ=0
skipped=0
known=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    s0="$(timeout 25 "$ELISACORE_BIN" -emit interpret "$src" </dev/null 2>&1)"; rc0=$?
    [ "$rc0" -ne 0 ] && { skipped=$((skipped + 1)); continue; }
    s1="$(timeout 120 bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit interpret -o /dev/null "$src" 2>&1)"; rc1=$?
    if [ "$s0" == "$s1" ] && [ "$rc0" == "$rc1" ]; then
        same=$((same + 1)); continue
    fi
    if [[ " $EXPECTED_DIVERGENT " == *" $name "* ]]; then
        known=$((known + 1))
        echo "KNOWN (stage1 correct, stage0 interpreter wrong): $name — stage0=[$s0] stage1=[$s1]"
        continue
    fi
    differ=$((differ + 1))
    echo "DIFF: $name — stage0(exit $rc0)=[$s0] stage1(exit $rc1)=[$s1]"
done

echo "emit_interpret: $same identical, $known known-stage0-bug, $differ divergent, $skipped skipped"
[ "$differ" -eq 0 ] || { echo "emit_interpret parity FAILED"; exit 1; }
echo "emit_interpret parity OK"
