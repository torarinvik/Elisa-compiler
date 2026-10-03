#!/usr/bin/env bash
# A parameter shadows a global const of the same name, and a `global mutable` is never a
# constant: neither may make a guarded call "provably" violate a precondition.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
check() {
  printf '%s' "$2" > "$WORK/p.elisa"
  out="$("$STAGE1" -emit obj -O0 -o "$WORK/p.o" "$WORK/p.elisa" 2>&1 || true)"
  if grep -q 'precondition of "scale" is violated' <<< "$out"; then got=yes; else got=no; fi
  [[ "$got" == "$1" ]] || { echo "precondition global shadow smoke FAIL: expected violation=$1 for:"; cat "$WORK/p.elisa"; exit 1; } >&2
}
body=$'def scale(distance: i64, edge: i64) -> i64:\n    requires edge >= 1\n    distance / edge\n\ndef use(edge: i64) -> i64:\n    return 0 if edge < 1\n    scale(4, edge)\n\ndef main() -> i32:\n    return 0 if use(2) == 2\n    return 1\n'
check no  $'global mutable edge: i64 = 0\n\n'"$body"
check no  $'const edge: i64 = 0\n\n'"$body"
check yes $'def scale(distance: i64, edge: i64) -> i64:\n    requires edge >= 1\n    distance / edge\n\ndef use() -> i64:\n    x: i64 = scale(4, 0)\n    return x\n\ndef main() -> i32:\n    return 0\n'
echo "precondition global shadow smoke OK" >&2
