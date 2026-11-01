#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule buffer views smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SUFFIX="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/buffer_views$SUFFIX" \
    "$ROOT/test/repro/pymodule_buffer_views.elisa" >/dev/null
grep -q "elisa_pymodule_borrow_buffer(arg0" < <(bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o /dev/stdout "$ROOT/test/repro/pymodule_buffer_views.elisa")

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
from array import array

import buffer_views as b

doubles = array("d", [0.5, 1.5, 2.0])
assert b.sum_f64(doubles) == 4.0
assert b.sum_f64([0.5, 1.5, 2.0]) == 4.0
assert b.sum_f64(memoryview(doubles)) == 4.0
assert b.sum_f64(array("d")) == 0.0
assert b.identity_f64(doubles) == [0.5, 1.5, 2.0]
# Other formats and strided memory are converted element by element, as before.
assert b.sum_f64(array("f", [0.5, 1.5])) == 2.0
assert b.sum_f64(array("i", [1, 2])) == 3.0
assert b.sum_f64(memoryview(doubles)[::2]) == 2.5
assert b.sum_f32(array("f", [0.25, 0.5])) == 0.75
assert b.sum_i32(array("i", [-3, 5, 7])) == 9
assert b.sum_u64(array("Q", [2**63, 1])) == 2**63 + 1
assert b.sum_u64_list([2**64 - 2, 1]) == 2**64 - 1
assert b.count_u8(b"abcd") == 4
assert b.count_u8(bytearray(b"ab")) == 2
assert b.count_u8(array("B", [1, 2, 3])) == 3

# A borrowed buffer is released after the call, and when a later argument fails.
doubles.append(3.0)
assert b.scaled_sum(doubles, b"xy") == 14.0
doubles.append(4.0)
try:
    b.scaled_sum(doubles, [1, 256])
except (TypeError, OverflowError):
    pass
else:
    raise AssertionError("out-of-range u8 accepted")
doubles.append(5.0)
try:
    b.sum_u64(array("q", [-1]))
except OverflowError:
    pass
else:
    raise AssertionError("signed buffer borrowed as unsigned")
PY

echo "pymodule buffer views smoke OK"
