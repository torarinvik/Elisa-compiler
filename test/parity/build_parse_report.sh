#!/usr/bin/env bash
# Build the stage1 parse_report helper used by semantic smoke tests.
# Expects REPO_ROOT to be set by the caller. ELISA_STAGE1_BIN and ELISA_RUNTIME_OBJ may
# pin the local product and runtime; the caller's stage0 selector is intentionally ignored.

command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; return 2 2>/dev/null || exit 2; }

STAGE1_BIN="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$REPO_ROOT/build/runtime/elisacore_runtime.o}"
[[ -x "$STAGE1_BIN" ]] || {
  echo "error: missing stage1 product at $STAGE1_BIN (run scripts/elisac_stage1.sh --seed)" >&2
  return 2 2>/dev/null || exit 2
}
[[ -f "$RUNTIME_OBJ" ]] || {
  echo "error: missing stage1 runtime object at $RUNTIME_OBJ (run scripts/build_runtime_object.sh)" >&2
  return 2 2>/dev/null || exit 2
}

RPT="${ELISA_PARSE_REPORT:-$REPO_ROOT/build/parse_report}"
mkdir -p "$(dirname -- "$RPT")"

# FRESHNESS GUARD. This script is sourced by 67 gate checks and used to recompile
# parse_report.elisa unconditionally every time — identical bytes, once per check, and a
# race on the fixed output path that is what stopped the suite being parallelisable.
# Skip when the binary is newer than every input it is built from.
if [[ -x "$RPT" ]]; then
  _pr_stale=""
  for _pr_src in "$REPO_ROOT/test/breadth/parse_report.elisa" "$STAGE1_BIN" "$RUNTIME_OBJ" "$REPO_ROOT/scripts/elisac_stage1.sh"; do
    [[ -e "$_pr_src" && "$_pr_src" -nt "$RPT" ]] && _pr_stale=1
  done
  # The semantic layer it includes is the real input set; any .elisa under src/ counts.
  if [[ -z "$_pr_stale" ]] && [[ -n "$(find "$REPO_ROOT/src" -name '*.elisa' -newer "$RPT" -print -quit 2>/dev/null)" ]]; then
    _pr_stale=1
  fi
  [[ -z "$_pr_stale" ]] && return 0 2>/dev/null || true
fi

# ATOMIC PUBLISH. The guard above narrows the race but cannot close it: 74 gate checks
# source this script and run_all runs them in PARALLEL, so two can decide "stale" in the
# same instant. Writing straight to $RPT then let a third check exec a HALF-WRITTEN binary
# — observed once as a lone nullable_flow_smoke failure that passed on its own and did not
# recur. Build under per-process names and `mv` into place: rename is atomic within a
# filesystem, so a concurrent reader sees either the old binary or the new one, never a
# partial one.
_pr_tmp="$RPT.$$"
_pr_obj="$REPO_ROOT/build/parse_report.$$.o"
trap 'rm -f "$_pr_tmp" "$_pr_obj"' RETURN 2>/dev/null || true

# The reporter is deliberately a stage1-only product. Differential callers export their
# stage0 oracle as ELISACORE_BIN (and often ELISA_CORE); do not let those selector variables
# leak into the self-hosted compiler's environment, where they can change an otherwise local
# build or accidentally re-enter the seed path. The wrapper derives its own ROOT.
if ! env -u ELISACORE_BIN -u ELISA_CORE -u REPO_ROOT \
    ELISA_STAGE1_BIN="$STAGE1_BIN" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" \
    bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit obj -O2 -permissive \
      -o "$_pr_obj" "$REPO_ROOT/test/breadth/parse_report.elisa" \
      >/dev/null 2>"$REPO_ROOT/build/parse_report.$$.err"; then
  cat "$REPO_ROOT/build/parse_report.$$.err" >&2
  rm -f "$_pr_obj" "$REPO_ROOT/build/parse_report.$$.err"
  echo "error: failed to build stage1 parse_report.o" >&2
  exit 1
fi

_pr_link_flags=()
case "$(uname -s)" in
  Darwin) _pr_link_flags=(-Wl,-undefined,dynamic_lookup) ;;
  Linux)  _pr_link_flags=(-no-pie) ;;
esac
if ! clang -O2 "${_pr_link_flags[@]}" "$_pr_obj" "$RUNTIME_OBJ" -o "$_pr_tmp" 2>"$REPO_ROOT/build/parse_report.$$.link.err"; then
  cat "$REPO_ROOT/build/parse_report.$$.link.err" >&2
  rm -f "$_pr_obj" "$_pr_tmp" "$REPO_ROOT/build/parse_report.$$.link.err"
  echo "error: failed to link parse_report" >&2
  exit 1
fi

mv -f "$_pr_tmp" "$RPT"
rm -f "$_pr_obj" "$REPO_ROOT/build/parse_report.$$.err" "$REPO_ROOT/build/parse_report.$$.link.err"
