#!/usr/bin/env bash
# Build test/breadth/emit_native (the stage0-compiled LLVM-IR emitter twelve gate checks
# drive) ONCE, fresh and race-free. Sourced or executed; expects REPO_ROOT (or derives it).
#
# Phase T (2026-09-06): two checks rebuilt build/emit_native unconditionally and ten more
# rebuilt it when missing, all to the SAME path, and run_all runs them in parallel — on a
# 32-wide gate one check exec'd a half-linked binary ("Text file busy") and another found
# "no emit_native" while a sibling was mid-rebuild. Same freshness + atomic-publish shape as
# build_parse_report.sh: skip when newer than every input, build under a private name, mv.
REPO_ROOT="${REPO_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)}"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
ELISACORE_BIN="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
EMIT_NATIVE="${ELISA_EMIT_NATIVE:-$REPO_ROOT/build/emit_native}"
mkdir -p "$(dirname -- "$EMIT_NATIVE")"

_en_fresh=""
if [[ -x "$EMIT_NATIVE" ]]; then
  _en_fresh=1
  for _en_src in "$REPO_ROOT/test/breadth/emit_native.elisa" "$ELISACORE_BIN" "$REPO_ROOT/scripts/write_profiler_hook_fallbacks.sh"; do
    [[ -e "$_en_src" && "$_en_src" -nt "$EMIT_NATIVE" ]] && _en_fresh=""
  done
fi
if [[ -n "$_en_fresh" ]]; then
  return 0 2>/dev/null || exit 0
fi

_en_obj="$EMIT_NATIVE.$$.o"; _en_tmp="$EMIT_NATIVE.$$"; _en_log="$EMIT_NATIVE.$$.log"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$_en_obj" "$REPO_ROOT/test/breadth/emit_native.elisa" 2>"$_en_log"; then
  echo "build_emit_native: stage0 could not compile emit_native.elisa" >&2; sed -n '1,10p' "$_en_log" >&2
  rm -f "$_en_obj" "$_en_log"; return 1 2>/dev/null || exit 1
fi
_en_libdir="$("$LLVM_CONFIG" --libdir)"
# A stage0-compiled program references the std's profiler hooks; the seed and the runtime
# object link the weak fallbacks, and this link must too or it fails the day the std calls
# a hook nothing else defines -- which is exactly how it went red.
_en_hooks="$EMIT_NATIVE.$$.hooks.c"
bash "$REPO_ROOT/scripts/write_profiler_hook_fallbacks.sh" >"$_en_hooks"
if ! clang -o "$_en_tmp" "$_en_obj" "$_en_hooks" -L"$_en_libdir" -lLLVM -Wl,-rpath,"$_en_libdir" 2>"$_en_log"; then
  echo "build_emit_native: could not link emit_native" >&2; sed -n '1,10p' "$_en_log" >&2
  rm -f "$_en_obj" "$_en_tmp" "$_en_log" "$_en_hooks"; return 1 2>/dev/null || exit 1
fi
mv -f "$_en_tmp" "$EMIT_NATIVE"
rm -f "$_en_obj" "$_en_log" "$_en_hooks"
