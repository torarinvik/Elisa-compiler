#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule set error payload smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_error_payload_set.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/error_payload_set.json" "$SOURCE" >/dev/null
"$PYTHON_BIN" - "$WORK/error_payload_set.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail"]["payload"] == "set[i64]"
assert functions["fail_holder"]["payload"] == "Holder"
assert functions["fail_structured"]["payload"] == "struct"
assert functions["fail_structured"]["payload_variants"] == [{
    "name": "Bad",
    "fields": [
        {"name": "code", "type": "i64"},
        {"name": "values", "type": "set[i64]"},
        {"name": "labels", "type": "set[sview]"},
    ],
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/error_payload_set.pyi" "$SOURCE" >/dev/null
grep -Fq 'def fail(values: Iterable[int]) -> int: ...' "$WORK/error_payload_set.pyi"
grep -Fq 'def fail_structured(code: int, values: Iterable[int], labels: Iterable[str | bytes]) -> int: ...' "$WORK/error_payload_set.pyi"
grep -Fq 'def fail_holder(holder: Holder | HolderInput) -> int: ...' "$WORK/error_payload_set.pyi"
grep -Fq 'class SetPayloadError(ElisaError):' "$WORK/error_payload_set.pyi"
grep -Fq 'payload: set[int]' "$WORK/error_payload_set.pyi"
grep -Fq 'class StructuredSetPayloadError(ElisaError):' "$WORK/error_payload_set.pyi"
grep -Fq 'payload: StructuredSetPayloadErrorPayload' "$WORK/error_payload_set.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_set.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_set.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_set as module

values = {2, -1, 7}
try:
    module.fail(values)
except module.SetPayloadError as exc:
    assert exc.payload == values
    assert exc.function == "fail"
else:
    raise AssertionError("set error payload should raise SetPayloadError")

labels = {"α\x00β", "done"}
try:
    module.fail_structured(7, values, labels)
except module.StructuredSetPayloadError as exc:
    assert exc.payload == {
        "variant": "Bad",
        "code": 7,
        "values": values,
        "labels": labels,
    }
else:
    raise AssertionError("structured set error payload should raise StructuredSetPayloadError")

holder = {"values": values}
try:
    module.fail_holder(holder)
except module.HolderSetPayloadError as exc:
    assert exc.payload == holder
else:
    raise AssertionError("named-record set error payload should raise HolderSetPayloadError")

for bad in (3, {"not-an-int"}):
    try:
        module.fail(bad)
    except (TypeError, ValueError):
        pass
    except module.SetPayloadError:
        # A set is intentionally accepted from any iterable, so a coercible input can still
        # reach the Elisa function and raise its declared error.
        pass
    else:
        raise AssertionError((type(bad).__name__, bad))

print("pymodule set error payload smoke OK")
PY
