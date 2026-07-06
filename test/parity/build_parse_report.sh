#!/usr/bin/env bash
# Build the stage1 parse_report helper used by semantic smoke tests.
# Expects REPO_ROOT and ELISACORE_BIN to be set by the caller.

command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"

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
