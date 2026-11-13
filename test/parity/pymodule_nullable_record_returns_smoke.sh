#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nullable record returns smoke SKIP (Python/clang/runtime unavailable)"
    exit 0
fi
SUFFIX="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so -o "$WORK/nullable_records$SUFFIX" \
    "$ROOT/test/repro/pymodule_nullable_record_returns.elisa" >/dev/null
cd "$WORK"
PYTHONPATH="$WORK" "$PYTHON_BIN" -P - "$WORK/nullable_records.pyi" <<'PY'
import gc
from pathlib import Path
import sys
import nullable_records as m

assert m.scalar(False) is None
assert m.scalar(True) == {"value": 7}
obj = object()
count = sys.getrefcount(obj)
for _ in range(200):
    value = m.sample(found=True, label="α\0🙂", payload=obj)
    assert value == {"score": 1.25, "ids": [2, 0, 0], "rows": [[.1, .2, .7], []],
                     "label": "α\0🙂", "payload": obj}
    other = m.sample(True, b"bytes", obj)
    other["ids"][0] = 99
    other["rows"][0][0] = 99
    assert value["ids"][0] == 2 and value["rows"][0][0] == .1
    assert other["label"] == "bytes"
    del value, other
    assert m.sample(False, "unused", obj) is None
    assert sys.getrefcount(obj) == count
assert m.fallible(0, obj) is None
assert m.fallible(1, obj)["payload"] is obj
assert m.scalar_fallible(0) is None
assert m.scalar_fallible(1) == {"value": 7}
for _ in range(200):
    try:
        m.fallible(-9, obj)
    except m.ElisaError as exc:
        assert exc.payload == -9 and exc.function == "fallible"
    else:
        raise AssertionError("fallible record failed to raise")
    assert sys.getrefcount(obj) == count
try:
    m.scalar_fallible(-1)
except m.ElisaError as exc:
    assert exc.function == "scalar_fallible"
else:
    raise AssertionError("scalar record failed to raise")
# A conversion error after native array allocation must release partial outputs and owners.
for _ in range(200):
    try:
        m.sample(True, b"\xff", obj)
    except UnicodeDecodeError:
        pass
    else:
        raise AssertionError("invalid UTF-8 returned as text")
    assert sys.getrefcount(obj) == count
value = m.sample(True, "kept", obj)
gc.collect()
assert value["payload"] is obj and value["rows"][0] == [.1, .2, .7]
del value
assert sys.getrefcount(obj) == count
stub = Path(sys.argv[1]).read_text()
assert "-> Sample | None" in stub and "-> Scalar | None" in stub
assert "rows: list[list[float]]" in stub
assert "ids: list[int]" in stub
compile(stub, sys.argv[1], "exec")
PY
# Unsupported payload shapes must fail before a C prototype can guess their ABI.
cat > "$WORK/unsupported.elisa" <<'ELISA'
struct Item:
    rows: view[view[i64]]
def value() -> Item?:
    return null
export pymodule unsupported:
    fn value
ELISA
for mode in pymodule pymodule-c; do
    if bash "$ROOT/scripts/elisac_stage1.sh" -emit "$mode" -o "$WORK/rejected" "$WORK/unsupported.elisa" >"$WORK/reject.log" 2>&1; then
        echo "unsupported nullable record unexpectedly accepted" >&2
        exit 1
    fi
    grep -q 'representable nullable record return' "$WORK/reject.log"
done
echo "pymodule nullable record returns smoke OK"
