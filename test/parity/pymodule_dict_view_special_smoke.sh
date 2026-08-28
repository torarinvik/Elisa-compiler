#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dict special views smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/dict_view_special.json" \
    "$ROOT/test/repro/pymodule_dict_view_special.elisa" >/dev/null
grep -Fq '"type": "dict[i64,view[sview]]"' "$WORK/dict_view_special.json"
grep -Fq '"type": "dict[i64,view[py::Object?]]"' "$WORK/dict_view_special.json"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dict_view_special.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_dict_view_special.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import dict_view_special

assert dict_view_special.roundtrip_sview({1: (item for item in ("α\x00β", "")), 2: ()}) == {
    1: ["α\x00β", ""], 2: []
}
assert dict_view_special.roundtrip_sview({1: (item for item in (b"\xce\xb1\x00\xce\xb2", b"")), 2: ()}) == {
    1: ["α\x00β", ""], 2: []
}
assert dict_view_special.roundtrip_cstr({"key": (item for item in ("a", ""))}) == {
    "key": ["a", ""]
}
assert dict_view_special.roundtrip_cstr({b"key": (item for item in (b"a", b""))}) == {
    "key": ["a", ""]
}
payload = {"kind": "object"}
objects = dict_view_special.roundtrip_objects({1: (item for item in (payload, None)), 2: ()})
assert objects[1][0] is payload and objects[1][1] is None and objects[2] == []
assert dict_view_special.roundtrip_optional({1: (item for item in (3, None, -4)), 2: ()}) == {
    1: [3, None, -4], 2: []
}
assert dict_view_special.roundtrip_optional_text({"key": (item for item in ("α\x00β", None, ""))}) == {
    "key": ["α\x00β", None, ""]
}
optional_payload = {"kind": "optional"}
optional_objects = dict_view_special.roundtrip_optional_objects({
    1: (item for item in (optional_payload, None)), 2: ()
})
assert optional_objects[1][0] is optional_payload and optional_objects[1][1] is None

for fn, value, expected in (
    (dict_view_special.roundtrip_sview, {1: [None]}, TypeError),
    (dict_view_special.roundtrip_cstr, {"key": ["bad\x00value"]}, ValueError),
    (dict_view_special.roundtrip_cstr, {"key": [None]}, TypeError),
    (dict_view_special.roundtrip_optional, {1: [2**63]}, OverflowError),
    (dict_view_special.roundtrip_optional, {1: ["bad"]}, TypeError),
    (dict_view_special.roundtrip_optional_text, {"key": [42]}, TypeError),
):
    try:
        fn(value)
    except expected:
        pass
    else:
        raise AssertionError("invalid special nested view value accepted")
try:
    dict_view_special.roundtrip_sview({1: [b"\xff"]})
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("invalid UTF-8 special view value accepted")
PY

echo "pymodule dict special views smoke OK"
