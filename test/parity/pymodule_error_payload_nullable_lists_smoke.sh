#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
SOURCE="$ROOT/test/repro/pymodule_error_payload_nullable_lists.elisa"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nullable-list error payload smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
"$PYTHON_BIN" - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
rows = {row["name"]: row for row in manifest["functions"]}
assert rows["fail_scalar"]["payload"] == "darray[i64?]"
assert rows["fail_text"]["payload"] == "darray[sview?]"
assert rows["fail_object"]["payload"] == "darray[py::Object?]"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/error_payload_nullable_lists.pyi" "$SOURCE" >/dev/null
grep -Fq 'class OptionalScalarListPayloadError(ElisaError):' "$WORK/error_payload_nullable_lists.pyi"
grep -Fq 'payload: list[int | None]' "$WORK/error_payload_nullable_lists.pyi"
grep -Fq 'payload: list[str | None]' "$WORK/error_payload_nullable_lists.pyi"
grep -Fq 'payload: list[Any | None]' "$WORK/error_payload_nullable_lists.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_nullable_lists.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_nullable_lists.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_nullable_lists as module

try:
    module.fail_scalar([1, None, -2])
except module.OptionalScalarListPayloadError as exc:
    assert exc.payload == [1, None, -2]
else:
    raise AssertionError("nullable scalar list payload should raise")

try:
    module.fail_text(["a", None, b"\xce\xb2"])
except module.OptionalTextListPayloadError as exc:
    assert exc.payload == ["a", None, "β"]
else:
    raise AssertionError("nullable text list payload should raise")

marker = {"kept": True}
try:
    module.fail_object([marker, None])
except module.OptionalObjectListPayloadError as exc:
    assert exc.payload[0] is marker
    assert exc.payload[1] is None
else:
    raise AssertionError("nullable object list payload should raise")

print("pymodule nullable-list error payload smoke OK")
PY
