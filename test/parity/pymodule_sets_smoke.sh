#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule sets smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/sets.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_sets.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import sets

assert sets.__all__[:9] == [
    "count_i64", "count_text", "count_u8", "count_bool",
    "roundtrip_i64", "roundtrip_i8", "roundtrip_text", "roundtrip_u8", "empty_i64",
]
assert sets.count_i64({}) == 0
assert sets.count_i64({1, -2, 3}) == 3
assert sets.count_i64(frozenset({1, 2})) == 2
assert sets.count_i64(value for value in (1, 2, 3)) == 3
assert sets.count_text({"α", "", "β"}) == 3
assert sets.count_text({b"\xce\xb1", b"", b"\xce\xb2"}) == 3
assert sets.count_u8({0, 255}) == 2
assert sets.count_bool({True, False}) == 2
assert sets.roundtrip_i64({1, -2, 3}) == {1, -2, 3}
assert sets.roundtrip_i8({-128, 127}) == {-128, 127}
assert sets.roundtrip_text({"α", ""}) == {"α", ""}
assert sets.roundtrip_u8({0, 255}) == {0, 255}
assert sets.empty_i64() == set()

for fn, value in ((sets.count_i64, {"bad"}), (sets.count_text, {1, 2}), (sets.count_u8, {256}), (sets.count_u8, {-1}), (sets.roundtrip_i8, {128}), (sets.roundtrip_text, {"bad\x00"})):
    try:
        fn(value)
    except (TypeError, OverflowError, ValueError):
        pass
    else:
        raise AssertionError(f"invalid Python set boundary accepted by {fn.__name__}")

try:
    sets.count_u8({256})
except OverflowError as exc:
    assert "at path [256]:" in str(exc)
    assert exc.function == "count_u8"
    assert exc.parameter == "values"
    assert exc.path == "[256]"
else:
    raise AssertionError("set element error did not include its value path")

try:
    sets.count_i64({"bad"})
except TypeError as exc:
    assert "at path ['bad']:" in str(exc)
    assert exc.function == "count_i64"
    assert exc.parameter == "values"
    assert exc.path == "['bad']"
else:
    raise AssertionError("set element type error did not include its value path")

try:
    sets.count_text({b"\xff"})
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("invalid UTF-8 set text accepted")
PY

echo "pymodule sets smoke OK"
