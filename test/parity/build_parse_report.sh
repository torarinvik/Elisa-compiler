#!/usr/bin/env bash
# Build the stage1 parse_report helper used by semantic smoke tests.
# Expects REPO_ROOT and ELISACORE_BIN to be set by the caller.

command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"

# FRESHNESS GUARD. This script is sourced by 67 gate checks and used to recompile
# parse_report.elisa unconditionally every time — identical bytes, once per check, and a
# race on the fixed output path that is what stopped the suite being parallelisable.
# Skip when the binary is newer than every input it is built from.
if [[ -x "$RPT" ]]; then
  _pr_stale=""
  for _pr_src in "$REPO_ROOT/test/breadth/parse_report.elisa" "$ELISACORE_BIN"; do
    [[ -e "$_pr_src" && "$_pr_src" -nt "$RPT" ]] && _pr_stale=1
  done
  # The semantic layer it includes is the real input set; any .elisa under src/ counts.
  if [[ -z "$_pr_stale" ]] && [[ -n "$(find "$REPO_ROOT/src" -name '*.elisa' -newer "$RPT" -print -quit 2>/dev/null)" ]]; then
    _pr_stale=1
  fi
  [[ -z "$_pr_stale" ]] && return 0 2>/dev/null || true
fi

if ! "$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>"$REPO_ROOT/build/parse_report.err"; then
  cat "$REPO_ROOT/build/parse_report.err" >&2
  echo "error: failed to build parse_report.o" >&2
  exit 1
fi

if ! clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>"$REPO_ROOT/build/parse_report.link.err"; then
  cat "$REPO_ROOT/build/parse_report.link.err" >&2
  echo "error: failed to link parse_report" >&2
  exit 1
fi
