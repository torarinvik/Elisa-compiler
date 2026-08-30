#!/usr/bin/env bash
# The adversarial differential oracle, as a GATE check.
#
# It generates small programs in shapes the compiler's own source never uses, builds each with
# BOTH compilers, links, runs, and compares exit codes. That last property is why it belongs in
# the gate rather than in a drawer: a byte-identical gen3 fixpoint proves stage1 reproduces the
# COMPILER, and every generation skips a construct the compiler never writes, identically. Five
# real defects have been found this way that a green gate could not see — two of them silent
# wrong answers (a `when` default row that shadowed later rows; `defer` dropped when a `-> void`
# function fell off the end).
#
# MISMATCH / DECLINE / PERMISSIVE are all ratcheted at zero by the tester itself, and so are
# O2_MISMATCH / O2_DECLINE: every program that agrees at -O0 is compiled again through the real
# `default<O2>` pipeline and re-run, because optimisation must never change an answer and a
# miscompile that only appears optimised is invisible to every other check here (the missing
# module datalayout was exactly that shape). ~2m40s.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ] || { echo "adversarial_differential SKIP: no stage1 binary"; exit 0; }
[ -x "${ELISACORE_BIN:-$REPO_ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}" ] || { echo "adversarial_differential SKIP: no stage0"; exit 0; }
[ -f "$ROOT/build/runtime/elisacore_runtime.o" ] || { echo "adversarial_differential SKIP: no runtime object"; exit 0; }

out="$(REPO_ROOT="$ROOT" python3 "$ROOT/test/breadth/adversarial_differential.py" 2>&1)"
status=$?
if [ "$status" -ne 0 ]; then
    echo "$out" >&2
    echo "adversarial_differential FAILED: see MISMATCH / DECLINE / PERMISSIVE rows above" >&2
    exit 1
fi
echo "adversarial_differential OK: $(echo "$out" | grep '^adversarial:' | sed 's/^adversarial: //')"
