#!/usr/bin/env bash
# Verify the backend's Darwin/POSIX compatibility predicates in emitted code.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OBJDUMP="${LLVM_OBJDUMP:-/opt/homebrew/opt/llvm/bin/llvm-objdump}"
[[ -x "$OBJDUMP" ]] || { echo "set LLVM_OBJDUMP to LLVM's object disassembler" >&2; exit 2; }
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-apple-predicates.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
for triple in arm64-apple-ios17.0 arm64-apple-ios17.0-simulator arm64-apple-tvos17.0 arm64-apple-watchos10.0 arm64-apple-xros1.0 arm64-apple-macos14.0 aarch64-unknown-linux-gnu; do
  bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -target-triple "$triple" \
    -o "$WORK/probe.o" "$ROOT/test/apple_mobile_target_predicate.elisa" > "$WORK/compile.log" 2>&1 || {
      cat "$WORK/compile.log" >&2; exit 1;
    }
  "$OBJDUMP" -d "$WORK/probe.o" > "$WORK/disassembly.txt"
  if ! grep -Eq 'mov[[:space:]]+w0, #0x1([[:space:]]|$)' "$WORK/disassembly.txt"; then
    echo "target predicate is not POSIX: $triple" >&2
    cat "$WORK/disassembly.txt" >&2
    exit 1
  fi
  echo "PASS POSIX target $triple"
done
