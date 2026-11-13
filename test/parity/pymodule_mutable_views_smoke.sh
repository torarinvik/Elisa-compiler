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
    echo "pymodule mutable views smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/mutable_views.json" \
    "$ROOT/test/repro/pymodule_mutable_views.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/mutable_views.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    rows = {row["name"]: row for row in json.load(handle)["functions"]}
assert rows["scale"]["parameters"][0] == {"name": "values", "type": "view[f64]", "mutable": True}
assert "mutable" not in rows["scale"]["parameters"][1]
PY

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/text.json" \
    "$ROOT/test/repro/pymodule_mutable_view_text.elisa" 2>"$WORK/text.err"; then
    echo "mutable view of text accepted" >&2
    exit 1
fi
grep -q "mutable views only of fixed-width numbers" "$WORK/text.err"

SUFFIX="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/mutable_views$SUFFIX" \
    "$ROOT/test/repro/pymodule_mutable_views.elisa" >/dev/null
grep -q "def scale(values: _elisa_buffers.Buffer, factor: float) -> int" "$WORK/mutable_views.pyi"

cd "$WORK"
PYTHONPATH="$WORK" "$PYTHON_BIN" -P - <<'PY'
import array

import mutable_views

values = array.array("d", [1.0, 2.0, 3.0])
assert mutable_views.scale(values, 2.0) == 3
assert list(values) == [2.0, 4.0, 6.0]
counts = array.array("i", [1, 2])
assert mutable_views.bump(counts) == 2
assert list(counts) == [2, 3]
storage = bytearray(16)
assert mutable_views.scale(memoryview(storage).cast("d"), 2.0) == 2

# Copying an unaligned writable view would silently discard the caller's updates.
storage = bytearray(17)
unaligned = memoryview(storage)[1:].cast("d")
unaligned[:] = memoryview(array.array("d", [1.0, 2.0]))
before = bytes(storage)
try:
    mutable_views.scale(unaligned, 2.0)
except TypeError as error:
    assert "aligned" in str(error), error
    assert error.function == "scale" and error.parameter == "values"
else:
    raise AssertionError("unaligned writable view accepted")
assert bytes(storage) == before
unaligned.release()
storage.extend(b"x")

# A mutable view writes through, so every input it cannot write through is refused:
# sequences (a copy would drop the writes), read-only buffers, other element types.
for rejected in ([1.0, 2.0], (1.0,), b"\x00" * 8, memoryview(bytes(8)).cast("d"),
                 array.array("f", [1.0]), array.array("q", [1])):
    try:
        mutable_views.scale(rejected, 2.0)
    except TypeError as error:
        assert "writable" in str(error), error
    else:
        raise AssertionError(f"mutable view accepted {rejected!r}")
PY

echo "pymodule mutable views smoke OK"
