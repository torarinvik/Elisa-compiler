#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nullable aggregate defaults smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_nullable_aggregate_defaults.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/nullable_aggregate_defaults.json" "$SOURCE" >/dev/null
python3 - "$WORK/nullable_aggregate_defaults.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["list_default"]["parameters"][0]["default"] == "[1, None, -2]"
assert functions["dict_default"]["parameters"][0]["default"] == '{"a": 1, "b": None}'
assert functions["text_default"]["parameters"][0]["default"] == '["hello", None, "a\\0b"]'
assert functions["object_default"]["parameters"][0]["default"] == "[None]"
assert functions["optional_scalar_default"]["parameters"][0]["default"] == "7"
assert functions["optional_text_default"]["parameters"][0]["default"] == '"hello"'
assert functions["optional_cstr_default"]["parameters"][0]["default"] == '"world"'
assert functions["optional_object_default"]["parameters"][0]["default"] == "None"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/nullable_aggregate_defaults.pyi" "$SOURCE" >/dev/null
grep -Fq 'def list_default(values: Sequence[int | None] = [1, None, -2]) -> list[int | None]: ...' "$WORK/nullable_aggregate_defaults.pyi"
grep -Fq 'def dict_default(values: Mapping[str | bytes, int | None] = {"a": 1, "b": None}) -> dict[str, int | None]: ...' "$WORK/nullable_aggregate_defaults.pyi"
grep -Fq 'def text_default(values: Sequence[str | bytes | None] = ["hello", None, "a\0b"]) -> list[str | None]: ...' "$WORK/nullable_aggregate_defaults.pyi"
grep -Fq 'def object_default(values: Sequence[Any | None] = [None]) -> list[Any | None]: ...' "$WORK/nullable_aggregate_defaults.pyi"
grep -Fq 'def optional_scalar_default(value: int | None = 7) -> int | None: ...' "$WORK/nullable_aggregate_defaults.pyi"
grep -Fq 'def optional_text_default(value: str | bytes | None = "hello") -> str | None: ...' "$WORK/nullable_aggregate_defaults.pyi"
grep -Fq 'def optional_cstr_default(value: str | bytes | None = "world") -> str | None: ...' "$WORK/nullable_aggregate_defaults.pyi"
grep -Fq 'def optional_object_default(value: Any | None = None) -> Any | None: ...' "$WORK/nullable_aggregate_defaults.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/nullable_aggregate_defaults.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/nullable_aggregate_defaults.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nullable_aggregate_defaults as module

assert module.list_default() == [1, None, -2]
assert module.dict_default() == {"a": 1, "b": None}
assert module.text_default() == ["hello", None, "a\x00b"]
assert module.object_default() == [None]
assert module.optional_scalar_default() == 7
assert module.optional_scalar_default(None) is None
assert module.optional_scalar_default(9) == 9
assert module.optional_text_default() == "hello"
assert module.optional_text_default(None) is None
assert module.optional_text_default("β") == "β"
assert module.optional_cstr_default() == "world"
assert module.optional_cstr_default(None) is None
assert module.optional_cstr_default("γ") == "γ"
assert module.optional_object_default() is None
assert module.optional_object_default(None) is None

# Literal defaults are rebuilt on every omitted call, including nullable leaves.
values = module.list_default()
values[0] = 999
assert module.list_default() == [1, None, -2]
mapping = module.dict_default()
mapping["a"] = 999
assert module.dict_default() == {"a": 1, "b": None}

marker = {"kept": True}
assert module.object_default([marker, None])[0] is marker
assert module.text_default(["override", None]) == ["override", None]
print("pymodule nullable aggregate defaults smoke OK")
PY
