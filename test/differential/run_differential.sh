#!/usr/bin/env bash
# Differential testing: compile every case with BOTH compiler generations, run
# both binaries, and compare.
#
# The point is behavioural divergence, not compiler crashes. stage1 bugs found
# so far all compiled cleanly and then did the wrong thing at runtime -- a
# destructor that never ran, a text global that read as null -- so comparing
# exit status against stage0 is what makes them visible.
#
# Each case is a self-contained program whose `main` returns 0 on success and a
# distinct non-zero code per failed assertion, so a divergence points at which
# assertion moved.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../stage0/compiler/bin/elisac-local}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
RUNTIME="$ROOT/build/runtime/elisacore_runtime.o"
CASES="${1:-$ROOT/test/differential/cases}"

[[ -x "$STAGE0" ]] || { echo "no stage0 compiler at $STAGE0 (set ELISACORE_BIN)" >&2; exit 2; }
[[ -x "$ROOT/bin/elisac-stage1" ]] || { echo "no stage1 product; run scripts/elisac_stage1.sh --seed" >&2; exit 2; }
[[ -f "$RUNTIME" ]] || { echo "no runtime object at $RUNTIME" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-differential.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

pass=0
diverged=0
skipped=0
expected_divergences=0
unexpected_agreements=0

# A case named *.xfail.elisa documents a divergence that is already known and
# not yet fixed. It keeps the gap visible without turning the suite red, and it
# fails loudly the day the gap closes so the case gets promoted.
is_expected_divergence() {
  [[ "$1" == *.xfail ]]
}

report_divergence() {
  if is_expected_divergence "$1"; then
    echo "XFAIL $1: $2 (known)"
    expected_divergences=$((expected_divergences + 1))
  else
    echo "DIVERGE $1: $2"
    diverged=$((diverged + 1))
  fi
}

for source in "$CASES"/*.elisa; do
  name="$(basename "$source" .elisa)"

  # A case stage0 itself rejects is not a stage1 finding; skip rather than
  # reporting a divergence against a baseline that never worked.
  if ! "$STAGE0" -emit obj -O0 -o "$WORK/$name.s0.o" "$source" >"$WORK/$name.s0.log" 2>&1; then
    echo "SKIP $name (stage0 rejected it)"
    skipped=$((skipped + 1))
    continue
  fi
  if ! bash "$STAGE1" -O0 -o "$WORK/$name.s1.o" "$source" >"$WORK/$name.s1.log" 2>&1; then
    report_divergence "$name" "stage0 compiled it, stage1 did not"
    continue
  fi

  # stage0 bundles the runtime into its object; stage1 links against the
  # separately built runtime object.
  # stage0 usually bundles what it needs; a case that pulls in std collections
  # still wants the runtime object, so fall back to linking it in.
  clang -Wl,-dead_strip -o "$WORK/$name.s0" "$WORK/$name.s0.o" >>"$WORK/$name.s0.log" 2>&1 ||
    clang -Wl,-dead_strip -o "$WORK/$name.s0" "$WORK/$name.s0.o" "$RUNTIME" >>"$WORK/$name.s0.log" 2>&1
  clang -Wl,-dead_strip -o "$WORK/$name.s1" "$WORK/$name.s1.o" "$RUNTIME" >>"$WORK/$name.s1.log" 2>&1
  if [[ ! -x "$WORK/$name.s0" || ! -x "$WORK/$name.s1" ]]; then
    echo "SKIP $name (link failed on one side)"
    skipped=$((skipped + 1))
    continue
  fi

  "$WORK/$name.s0" >"$WORK/$name.s0.out" 2>&1
  status0=$?
  "$WORK/$name.s1" >"$WORK/$name.s1.out" 2>&1
  status1=$?

  if [[ "$status0" -ne "$status1" ]]; then
    report_divergence "$name" "stage0 exit=$status0, stage1 exit=$status1"
    continue
  fi
  if ! diff -q "$WORK/$name.s0.out" "$WORK/$name.s1.out" >/dev/null; then
    report_divergence "$name" "same exit status, different output"
    continue
  fi
  if [[ "$status0" -ne 0 ]]; then
    echo "SKIP $name (both generations agree on failure exit=$status0)"
    skipped=$((skipped + 1))
    continue
  fi
  if is_expected_divergence "$name"; then
    echo "UNEXPECTED-PASS $name: agrees now; drop the .xfail suffix"
    unexpected_agreements=$((unexpected_agreements + 1))
    continue
  fi
  pass=$((pass + 1))
done

echo "differential: $pass agreed, $diverged diverged, $expected_divergences xfail, $skipped skipped, $unexpected_agreements unexpected-pass"
[[ "$diverged" -eq 0 && "$unexpected_agreements" -eq 0 ]]
