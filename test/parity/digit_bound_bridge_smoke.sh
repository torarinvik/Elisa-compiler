#!/usr/bin/env bash
# Compare every signed 8-bit input across divisors and keep a real overflow check.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
LLVM_CONFIG="${LLVM_CONFIG:-llvm-config}"
CXX="${CXX:-clang++}"
CC="${CC:-clang}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-digit-bound.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
bash "$ROOT/scripts/build_stage1_llvm_bridge.sh" "$WORK/bridge.o"
read -r -a CXXFLAGS <<<"$("$LLVM_CONFIG" --cxxflags)"
read -r -a LDFLAGS <<<"$("$LLVM_CONFIG" --ldflags --system-libs --libs core irreader analysis passes | tr '\n' ' ')"
"$CXX" -O2 "${CXXFLAGS[@]}" "$ROOT/test/parity/digit_bound_bridge_driver.cpp" "$WORK/bridge.o" "${LDFLAGS[@]}" -o "$WORK/transform"
"$WORK/transform" "$ROOT/test/parity/fixtures/digit_bound_exhaustive.ll" "$WORK/transformed.ll"
"$CC" -O0 "$ROOT/test/parity/fixtures/digit_bound_exhaustive.c" "$ROOT/test/parity/fixtures/digit_bound_exhaustive.ll" -o "$WORK/before"
"$CC" -O0 "$ROOT/test/parity/fixtures/digit_bound_exhaustive.c" "$WORK/transformed.ll" -o "$WORK/after"
"$WORK/before" > "$WORK/before.txt"
"$WORK/after" > "$WORK/after.txt"
cmp "$WORK/before.txt" "$WORK/after.txt"
python3 - "$WORK/after.txt" <<'PY'
from pathlib import Path
import sys
values = Path(sys.argv[1]).read_text().split()
assert len(values) == 4865 and values[-1] == '-999'
PY
if [[ "$("$LLVM_CONFIG" --version)" == 23.* ]]; then
  count="$(grep -c 'call { i8, i1 } @llvm.sadd.with.overflow' "$WORK/transformed.ll")"
  [[ "$count" == 4 ]] || { echo "expected four retained overflow checks, got $count" >&2; exit 1; }
fi
echo 'bounded division sum bridge: PASS'
