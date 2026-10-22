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
    echo "pymodule defaults smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/defaults.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_defaults.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import sys
import defaults

assert defaults.scaled(2) == 11
assert defaults.scaled(2, 4) == 13
assert defaults.scaled(2, 4, 6) == 14
assert defaults.scaled(base=2, offset=7) == 13
assert defaults.enabled() is False
assert defaults.enabled(True) is True
assert defaults.ratio(8) == 4.0
assert defaults.count_from() == 0
assert defaults.count_from(9) == 9
pointer_unsigned_max = 2 * sys.maxsize + 1
assert defaults.count_from(pointer_unsigned_max) == pointer_unsigned_max
for bad in (-1, pointer_unsigned_max + 1):
    try:
        defaults.count_from(bad)
    except OverflowError:
        pass
    else:
        raise AssertionError(("count_from accepted an out-of-range usize", bad))
assert defaults.char_code() == 65
assert defaults.char_code(66) == 66
assert defaults.cstr_default() == "hello"
assert defaults.cstr_default("world") == "world"
assert defaults.sview_default() == "α"
assert defaults.sview_default("β") == "β"
assert defaults.escaped_default() == "line\nnext"
assert defaults.empty_list() == 0
assert defaults.empty_list([1, 2]) == 2
assert defaults.empty_bytes() == 0
assert defaults.empty_bytes(b"abc") == 3
assert defaults.empty_dict() == 0
assert defaults.empty_dict({1: 2}) == 1
assert defaults.empty_set() == 0
assert defaults.empty_set({1, 2}) == 2
assert defaults.empty_view() == 0
assert defaults.empty_view([1, 2]) == 2
assert defaults.empty_mix() == 0
assert defaults.empty_mix([1], {2: 3}, {4, 5}) == 4
assert str(inspect.signature(defaults.scaled)) == "(base, factor=3, offset=5)"
assert str(inspect.signature(defaults.enabled)) == "(flag=False)"
assert str(inspect.signature(defaults.ratio)) == "(value, scale=0.5)"
assert str(inspect.signature(defaults.count_from)) == "(start=0)"
assert str(inspect.signature(defaults.char_code)) == "(value=65)"
assert str(inspect.signature(defaults.cstr_default)) == "(value='hello')"
assert str(inspect.signature(defaults.sview_default)) == "(value='α')"
assert str(inspect.signature(defaults.escaped_default)) == "(value='line\\nnext')"
assert str(inspect.signature(defaults.empty_list)) == "(values=[])"
assert str(inspect.signature(defaults.empty_bytes)) == "(values=b'')"
assert str(inspect.signature(defaults.empty_dict)) == "(values={})"
assert str(inspect.signature(defaults.empty_set)) == "(values={})"
assert str(inspect.signature(defaults.empty_view)) == "(values=[])"
assert str(inspect.signature(defaults.empty_mix)) == "(values=[], mapping={}, unique={})"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/defaults_unsupported.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_defaults_unsupported.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import defaults_unsupported

assert defaults_unsupported.bad() == 1
assert defaults_unsupported.mapping() == 1
assert defaults_unsupported.unique() == 2
assert defaults_unsupported.bytes_default() == 3
assert defaults_unsupported.nested() == 2
assert defaults_unsupported.viewed() == 2
assert str(inspect.signature(defaults_unsupported.bad)) == "(values=[1])"
assert str(inspect.signature(defaults_unsupported.mapping)) == "(values={1: 2})"
assert str(inspect.signature(defaults_unsupported.unique)) == "(values={1, 2})"
assert str(inspect.signature(defaults_unsupported.bytes_default)) == "(values=b'\\x01\\x02\\xff')"
assert str(inspect.signature(defaults_unsupported.nested)) == "(values=[[1, 2], [3]])"
assert str(inspect.signature(defaults_unsupported.viewed)) == "(values=[1, 2])"

assert defaults_unsupported.bad([4, 5]) == 2
assert defaults_unsupported.mapping({7: 8, 9: 10}) == 2
assert defaults_unsupported.unique({11}) == 1
assert defaults_unsupported.bytes_default(b"xy") == 2
assert defaults_unsupported.nested([[12]]) == 1
assert defaults_unsupported.viewed([13]) == 1
PY

grep -Fq 'def bad(values: Sequence[int] = [1]) -> int: ...' "$WORK/defaults_unsupported.pyi"
grep -Fq 'def mapping(values: Mapping[int, int] = {1: 2}) -> int: ...' "$WORK/defaults_unsupported.pyi"
grep -Fq 'def unique(values: Iterable[int] = {1, 2}) -> int: ...' "$WORK/defaults_unsupported.pyi"
grep -Fq 'def bytes_default(values: bytes | bytearray | memoryview = b"\x01\x02\xff") -> int: ...' "$WORK/defaults_unsupported.pyi"
grep -Fq 'def nested(values: Sequence[Sequence[int]] = [[1, 2], [3]]) -> int: ...' "$WORK/defaults_unsupported.pyi"
grep -Fq 'def viewed(values: Sequence[int] = [1, 2]) -> int: ...' "$WORK/defaults_unsupported.pyi"

for invalid_default in negative_unsigned negative_usize negative_uintptr out_of_range bad_escape; do
    if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
        -o "$WORK/$invalid_default.json" \
        "$ROOT/test/repro/pymodule_defaults_${invalid_default}.elisa" \
        >"$WORK/${invalid_default}_manifest.log" 2>&1; then
        echo "$invalid_default default should be rejected by pymodule" >&2
        exit 1
    fi
    grep -Fq "only literal scalar/text or recursively literal container defaults" "$WORK/${invalid_default}_manifest.log"
done

if "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.maxsize <= 2147483647 else 1)'; then
    for invalid_default in usize_32bit_out_of_range isize_32bit_out_of_range; do
        if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
            -o "$WORK/$invalid_default.json" \
            "$ROOT/test/repro/pymodule_defaults_${invalid_default}.elisa" \
            >"$WORK/${invalid_default}_manifest.log" 2>&1; then
            echo "$invalid_default default should be rejected on 32-bit targets" >&2
            exit 1
        fi
        grep -Fq "only literal scalar/text or recursively literal container defaults" "$WORK/${invalid_default}_manifest.log"
    done
fi

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/negative_unsigned.c" \
    "$ROOT/test/repro/pymodule_defaults_negative_unsigned.elisa" >"$WORK/negative_unsigned.log" 2>&1; then
    echo "negative unsigned default should be rejected by pymodule-c" >&2
    exit 1
fi
grep -Fq "only literal scalar/text or recursively literal container defaults" "$WORK/negative_unsigned.log"

for invalid_default in negative_usize negative_uintptr; do
    if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
        -o "$WORK/$invalid_default.c" \
        "$ROOT/test/repro/pymodule_defaults_${invalid_default}.elisa" >"$WORK/$invalid_default.log" 2>&1; then
        echo "$invalid_default default should be rejected by pymodule-c" >&2
        exit 1
    fi
    grep -Fq "only literal scalar/text or recursively literal container defaults" "$WORK/$invalid_default.log"
done

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/out_of_range.c" \
    "$ROOT/test/repro/pymodule_defaults_out_of_range.elisa" >"$WORK/out_of_range.log" 2>&1; then
    echo "out-of-range integer default should be rejected by pymodule-c" >&2
    exit 1
fi
grep -Fq "only literal scalar/text or recursively literal container defaults" "$WORK/out_of_range.log"

# `usize` and `isize` defaults are bounded by the target pointer width. On a
# 32-bit host these values must be refused; on a 64-bit host both are valid.
if "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.maxsize < 2**32 else 1)'; then
    for invalid_default in usize_32bit_out_of_range isize_32bit_out_of_range; do
        if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
            -o "$WORK/$invalid_default.c" \
            "$ROOT/test/repro/pymodule_defaults_${invalid_default}.elisa" >"$WORK/$invalid_default.log" 2>&1; then
            echo "$invalid_default default should be rejected on 32-bit targets" >&2
            exit 1
        fi
        grep -Fq "only literal scalar/text or recursively literal container defaults" "$WORK/$invalid_default.log"
    done
else
    for valid_default in usize_32bit_out_of_range isize_32bit_out_of_range; do
        bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
            -o "$WORK/$valid_default.c" \
            "$ROOT/test/repro/pymodule_defaults_${valid_default}.elisa" >/dev/null
    done
fi

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/bad_escape.c" \
    "$ROOT/test/repro/pymodule_defaults_bad_escape.elisa" >"$WORK/bad_escape.log" 2>&1; then
    echo "unknown string escape should be rejected by pymodule-c" >&2
    exit 1
fi
grep -Fq "only literal scalar/text or recursively literal container defaults" "$WORK/bad_escape.log"

echo "pymodule defaults smoke OK"
