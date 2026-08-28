#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dict views smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/dict_views.json" \
    "$ROOT/test/repro/pymodule_dict_views.elisa" >/dev/null
grep -Fq '"type": "dict[i64,view[i64]]"' "$WORK/dict_views.json"
grep -Fq '"type": "dict[sview,view[u8]]"' "$WORK/dict_views.json"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dict_views.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_dict_views.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import dict_views

assert dict_views.roundtrip({1: [2, 3], 4: []}) == {1: [2, 3], 4: []}
assert dict_views.roundtrip({1: (item for item in (7, 8))}) == {1: [7, 8]}
assert dict_views.roundtrip_bytes({"raw": b"\x00ab", "empty": b""}) == {
    "raw": b"\x00ab", "empty": b""
}
assert dict_views.roundtrip_bytes({"array": bytearray(b"abc"), "view": memoryview(b"xyz")}) == {
    "array": b"abc", "view": b"xyz"
}

for fn, value in (
    (dict_views.roundtrip, {1: [2**63]}),
    (dict_views.roundtrip, {1: ["bad"]}),
    (dict_views.roundtrip_bytes, {"bad": [256]}),
):
    try:
        fn(value)
    except (TypeError, OverflowError, ValueError):
        pass
    else:
        raise AssertionError("invalid nested view dictionary value accepted")
PY

echo "pymodule dict views smoke OK"
