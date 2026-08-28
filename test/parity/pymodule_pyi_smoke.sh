#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
PYTHON312_BIN="${PYTHON312_BIN:-/opt/homebrew/bin/python3.12}"
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    echo "pymodule pyi smoke SKIP (python3 unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/optional_structs.pyi" \
    "$ROOT/test/repro/pymodule_optional_structs.elisa" >/dev/null

"$PYTHON_BIN" - "$WORK/optional_structs.pyi" <<'PY'
import sys

stub = open(sys.argv[1], encoding="utf-8").read()
assert "class Options(TypedDict):" in stub
assert "class OptionsInput(Protocol):" in stub
assert "# optional attribute 'signed': int | None" in stub
assert "# optional attribute 'text': str | bytes | None" in stub
assert "def roundtrip(options: Options | OptionsInput) -> Options: ..." in stub
assert '__all__: list[str] = ["roundtrip", "ElisaError", "Options"]' in stub
PY

NESTED_STUB="$WORK/nested/stubs/fastmath.pyi"
PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$NESTED_STUB" \
    "$ROOT/test/repro/pymodule_export.elisa" >/dev/null
test -f "$NESTED_STUB"
grep -Fq 'def add(a: int, b: int) -> int: ...' "$NESTED_STUB"

DERIVED_WORK="$WORK/derived"
mkdir -p "$DERIVED_WORK"
(
    cd "$DERIVED_WORK"
    PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
        "$ROOT/test/repro/pymodule_export.elisa" >/dev/null
)
test -f "$DERIVED_WORK/fastmath.pyi"
grep -Fq 'def add(a: int, b: int) -> int: ...' "$DERIVED_WORK/fastmath.pyi"

if command -v pyright >/dev/null 2>&1; then
    cat > "$WORK/star_import_client.py" <<'PY'
from optional_structs import *

value: Options = {}
roundtrip(value)
ElisaError
PY
    # This fixture intentionally has only a .pyi (no native .so/.py source), so Pyright's
    # reportMissingModuleSource warning is expected. Fail on actual type errors instead.
    (cd "$WORK" && pyright --pythonversion 3.11 --level error star_import_client.py)
    pyright --pythonversion 3.10 --level error "$WORK/optional_structs.pyi"
fi

# Python 3.12 installations may not ship typing_extensions even though they provide
# stdlib NotRequired. Execute the stub to ensure the generated import fallback does not
# make that optional package a runtime dependency.
if [[ -x "$PYTHON312_BIN" ]]; then
    "$PYTHON312_BIN" - "$WORK/optional_structs.pyi" <<'PY'
import runpy
import sys

runpy.run_path(sys.argv[1])
PY
fi

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/errors.pyi" \
    "$ROOT/test/repro/pymodule_errors.elisa" >/dev/null
grep -Fq '# raises DivideError' "$WORK/errors.pyi"
grep -Fq 'class DivideError(ElisaError):' "$WORK/errors.pyi"
grep -Fq '    parameter: str | None' "$WORK/errors.pyi"
grep -Fq '    expected: str | None' "$WORK/errors.pyi"
grep -Fq '    path: str | None' "$WORK/errors.pyi"
grep -Fq 'payload: None' "$WORK/errors.pyi"
grep -Fq 'def float(value: _elisa_builtins.float) -> _elisa_builtins.float: ...' "$WORK/errors.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_reserved_name.pyi" \
    "$ROOT/test/repro/pymodule_struct_reserved_name.elisa" >/dev/null
grep -Fq 'class _ElisaStruct_0(TypedDict):' "$WORK/struct_reserved_name.pyi"
grep -Fq 'class _ElisaStruct_0Input(Protocol):' "$WORK/struct_reserved_name.pyi"
grep -Fq 'def roundtrip(value: _ElisaStruct_0 | _ElisaStruct_0Input) -> _ElisaStruct_0: ...' "$WORK/struct_reserved_name.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_reserved_name.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/text_constants.pyi" \
    "$ROOT/test/repro/pymodule_text_constants.elisa" >/dev/null
grep -Fq 'bytes: Final[_elisa_builtins.bytes]' "$WORK/text_constants.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/text_constants.pyi"

PYTHONPATH="$ROOT/scripts" "$PYTHON_BIN" - "$WORK/final_collision.pyi" <<'PY'
import sys
from pathlib import Path

from pymodule_pyi import render

manifest = {
    "constants": [
        {"name": "Final", "type": "i64"},
        {"name": "limit", "type": "i64"},
    ],
}
Path(sys.argv[1]).write_text(render(manifest), encoding="utf-8")
PY
grep -Fq 'Final: _elisa_typing.Final[int]' "$WORK/final_collision.pyi"
grep -Fq 'limit: _elisa_typing.Final[int]' "$WORK/final_collision.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/final_collision.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/payload_multi.pyi" \
    "$ROOT/test/repro/pymodule_error_payload_multi.elisa" >/dev/null
grep -Fq 'class MultiPayloadErrorBadPayload(TypedDict):' "$WORK/payload_multi.pyi"
grep -Fq 'MultiPayloadErrorPayload = MultiPayloadErrorBadPayload | MultiPayloadErrorOtherPayload' "$WORK/payload_multi.pyi"
grep -Fq '# error payload: MultiPayloadErrorPayload' "$WORK/payload_multi.pyi"
grep -Fq 'class MultiPayloadError(ElisaError):' "$WORK/payload_multi.pyi"
grep -Fq 'payload: MultiPayloadErrorPayload' "$WORK/payload_multi.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/payload_multi.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/payload_collision.pyi" \
    "$ROOT/test/repro/pymodule_pyi_payload_collision.elisa" >/dev/null
grep -Fq 'class CollisionBadPayload(TypedDict):' "$WORK/payload_collision.pyi"
grep -Fq 'class CollisionPayload(TypedDict):' "$WORK/payload_collision.pyi"
grep -Fq 'CollisionPayload_1 = CollisionBadPayload_1' "$WORK/payload_collision.pyi"
grep -Fq 'class CollisionBadPayload_1(TypedDict):' "$WORK/payload_collision.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/payload_collision.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/defaults.pyi" \
    "$ROOT/test/repro/pymodule_defaults.elisa" >/dev/null
grep -Fq 'def scaled(base: int, factor: int = 3, offset: int = 5) -> int: ...' "$WORK/defaults.pyi"
grep -Fq 'def enabled(flag: bool = False) -> bool: ...' "$WORK/defaults.pyi"
grep -Fq 'def cstr_default(value: str | bytes = "hello") -> str: ...' "$WORK/defaults.pyi"
grep -Fq 'def sview_default(value: str | bytes = "α") -> str: ...' "$WORK/defaults.pyi"
grep -Fq 'def empty_bytes(values: bytes | bytearray | memoryview = b"") -> int: ...' "$WORK/defaults.pyi"
grep -Fq 'def empty_set(values: Iterable[int] = set()) -> int: ...' "$WORK/defaults.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/defaults.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/optional_sview.pyi" \
    "$ROOT/test/repro/pymodule_optional_sview_probe.elisa" >/dev/null
grep -Fq 'def maybe_text(value: str | bytes | None = None) -> str | None: ...' "$WORK/optional_sview.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/optional_sview.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/optional_cstr.pyi" \
    "$ROOT/test/repro/pymodule_optional_cstr.elisa" >/dev/null
grep -Fq 'def maybe(value: str | bytes | None = None) -> str | None: ...' "$WORK/optional_cstr.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/optional_cstr.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/strings.pyi" \
    "$ROOT/test/repro/pymodule_strings.elisa" >/dev/null
grep -Fq 'def cstr(value: str | bytes) -> str: ...' "$WORK/strings.pyi"
grep -Fq 'def sview(value: str | bytes) -> str: ...' "$WORK/strings.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/strings.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_defaults.pyi" \
    "$ROOT/test/repro/pymodule_struct_defaults.elisa" >/dev/null
grep -Fq 'retries: NotRequired[int]' "$WORK/struct_defaults.pyi"
grep -Fq 'enabled: NotRequired[bool]' "$WORK/struct_defaults.pyi"
! grep -Fq 'retries: NotRequired[int | None]' "$WORK/struct_defaults.pyi"
grep -Fq "# optional attribute 'retries': int" "$WORK/struct_defaults.pyi"
grep -Fq 'class ConfigInput(Protocol):' "$WORK/struct_defaults.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_defaults.pyi"
if command -v pyright >/dev/null 2>&1; then
    cat > "$WORK/struct_defaults_client.py" <<'PY'
from types import SimpleNamespace

import struct_defaults

struct_defaults.roundtrip(SimpleNamespace(retries=9))
struct_defaults.roundtrip({"retries": 9})
PY
    (cd "$WORK" && pyright --pythonversion 3.11 --level error struct_defaults_client.py)
fi

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/optional_nontrailing.pyi" \
    "$ROOT/test/repro/pymodule_optional_nontrailing.elisa" >"$WORK/optional_nontrailing.log" 2>&1; then
    echo "pymodule-pyi should reject non-trailing optional parameters" >&2
    exit 1
fi
grep -Fq 'error: -emit pymodule requires default/nullable parameters to be trailing (target `bad`)' "$WORK/optional_nontrailing.log"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_lists.pyi" \
    "$ROOT/test/repro/pymodule_struct_lists.elisa" >/dev/null
grep -Fq 'values: Sequence[int]' "$WORK/struct_lists.pyi"
grep -Fq 'weights: Sequence[float]' "$WORK/struct_lists.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_lists.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_list_returns.pyi" \
    "$ROOT/test/repro/pymodule_struct_list_returns.elisa" >/dev/null
grep -Fq 'raw: bytes' "$WORK/struct_list_returns.pyi"
grep -Fq 'def make' "$WORK/struct_list_returns.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_list_returns.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_text_lists.pyi" \
    "$ROOT/test/repro/pymodule_struct_text_lists.elisa" >/dev/null
grep -Fq 'names: Sequence[str | bytes]' "$WORK/struct_text_lists.pyi"
grep -Fq 'labels: Sequence[str | bytes]' "$WORK/struct_text_lists.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_text_lists.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_object_lists.pyi" \
    "$ROOT/test/repro/pymodule_struct_object_lists.elisa" >/dev/null
grep -Fq 'values: list[Any]' "$WORK/struct_object_lists.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_object_lists.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_object_input.pyi" \
    "$ROOT/test/repro/pymodule_struct_object_input.elisa" >/dev/null
grep -Fq 'values: Sequence[Any]' "$WORK/struct_object_input.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_object_input.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_optional_lists.pyi" \
    "$ROOT/test/repro/pymodule_struct_optional_lists.elisa" >/dev/null
grep -Fq 'signed: Sequence[int | None]' "$WORK/struct_optional_lists.pyi"
grep -Fq 'narrow: Sequence[int | None]' "$WORK/struct_optional_lists.pyi"
grep -Fq 'labels: Sequence[str | bytes | None]' "$WORK/struct_optional_lists.pyi"
grep -Fq 'text: Sequence[str | bytes | None]' "$WORK/struct_optional_lists.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_optional_lists.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/struct_optional_lists.json" \
    "$ROOT/test/repro/pymodule_struct_optional_lists.elisa" >/dev/null
grep -Fq '"type": "darray[i64?]"' "$WORK/struct_optional_lists.json"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_dicts.pyi" \
    "$ROOT/test/repro/pymodule_struct_dicts.elisa" >/dev/null
grep -Fq 'numbers: dict[int, int]' "$WORK/struct_dicts.pyi"
grep -Fq 'nested: dict[str, list[int]]' "$WORK/struct_dicts.pyi"
grep -Fq 'objects: dict[str, Any | None]' "$WORK/struct_dicts.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_dicts.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/dicts.pyi" \
    "$ROOT/test/repro/pymodule_dicts.elisa" >/dev/null
grep -Fq 'def roundtrip_nested_bytes(values: Mapping[str | bytes, bytes | bytearray | memoryview]) -> dict[str, bytes]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_objects(values: Mapping[int, Sequence[Any]]) -> dict[int, list[Any]]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_optional_scalars(values: Mapping[int, Sequence[int | None]]) -> dict[int, list[int | None]]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_optional_float(values: Mapping[str | bytes, Sequence[float | None]]) -> dict[str, list[float | None]]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_optional_objects(values: Mapping[int, Sequence[Any | None]]) -> dict[int, list[Any | None]]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_cstr_values(values: Mapping[str | bytes, str | bytes]) -> dict[str, str]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_sview_values(values: Mapping[int, str | bytes]) -> dict[int, str]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_optional_cstr(values: Mapping[str | bytes, Sequence[str | bytes | None]]) -> dict[str, list[str | None]]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_optional_sview(values: Mapping[int, Sequence[str | bytes | None]]) -> dict[int, list[str | None]]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_cstr(values: Mapping[str | bytes, Sequence[str | bytes]]) -> dict[str, list[str]]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_sview(values: Mapping[int, Sequence[str | bytes]]) -> dict[int, list[str]]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_i8(values: Mapping[int, Sequence[int]]) -> dict[int, list[int]]: ...' "$WORK/dicts.pyi"
grep -Fq 'def roundtrip_nested_bool(values: Mapping[int, Sequence[bool]]) -> dict[int, list[bool]]: ...' "$WORK/dicts.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/dicts.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/nullable_dicts.pyi" \
    "$ROOT/test/repro/pymodule_nullable_dicts.elisa" >/dev/null
grep -Fq 'def optional_view(values: Mapping[str | bytes, str | bytes | None]) -> dict[str, str | None]: ...' "$WORK/nullable_dicts.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/nullable_dicts.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_sets.pyi" \
    "$ROOT/test/repro/pymodule_struct_sets.elisa" >/dev/null
grep -Fq 'numbers: set[int]' "$WORK/struct_sets.pyi"
grep -Fq 'labels: set[str]' "$WORK/struct_sets.pyi"
grep -Fq 'class SetBundleInput(Protocol):' "$WORK/struct_sets.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_sets.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_views.pyi" \
    "$ROOT/test/repro/pymodule_struct_views.elisa" >/dev/null
grep -Fq 'values: Sequence[int]' "$WORK/struct_views.pyi"
grep -Fq 'text: Sequence[str | bytes]' "$WORK/struct_views.pyi"
grep -Fq 'objects: Sequence[Any]' "$WORK/struct_views.pyi"
grep -Fq 'bytes: Sequence[int]' "$WORK/struct_views.pyi"
grep -Fq 'def roundtrip(batch: ViewBatch | ViewBatchInput) -> ViewBatch: ...' "$WORK/struct_views.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_views.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/error_payload_darray.pyi" \
    "$ROOT/test/repro/pymodule_error_payload_darray.elisa" >/dev/null
grep -Fq '# error payload: list[int]' "$WORK/error_payload_darray.pyi"
grep -Fq 'items: list[int]' "$WORK/error_payload_darray.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_darray.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/error_payload_view.pyi" \
    "$ROOT/test/repro/pymodule_error_payload_view.elisa" >/dev/null
grep -Fq '# error payload: list[int]' "$WORK/error_payload_view.pyi"
grep -Fq 'items: list[int]' "$WORK/error_payload_view.pyi"
grep -Fq '# error payload: bytes' "$WORK/error_payload_view.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_view.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/error_payload_dict.pyi" \
    "$ROOT/test/repro/pymodule_error_payload_dict.elisa" >/dev/null
grep -Fq 'def fail_dict(values: Mapping[int, int]) -> int: ...' "$WORK/error_payload_dict.pyi"
grep -Fq '# error payload: dict[int, int]' "$WORK/error_payload_dict.pyi"
grep -Fq 'def fail_text(values: Mapping[str | bytes, str | bytes]) -> int: ...' "$WORK/error_payload_dict.pyi"
grep -Fq '# error payload: dict[str, str]' "$WORK/error_payload_dict.pyi"
grep -Fq 'def fail_objects(values: Mapping[int, Any]) -> int: ...' "$WORK/error_payload_dict.pyi"
grep -Fq '# error payload: dict[int, Any]' "$WORK/error_payload_dict.pyi"
grep -Fq 'class DictPayloadError(ElisaError):' "$WORK/error_payload_dict.pyi"
grep -Fq 'payload: dict[int, int]' "$WORK/error_payload_dict.pyi"
grep -Fq 'class ObjectDictPayloadError(ElisaError):' "$WORK/error_payload_dict.pyi"
grep -Fq 'payload: dict[int, Any]' "$WORK/error_payload_dict.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_dict.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/error_payload_struct_dict.pyi" \
    "$ROOT/test/repro/pymodule_error_payload_struct_dict.elisa" >/dev/null
grep -Fq 'values: dict[int, int]' "$WORK/error_payload_struct_dict.pyi"
grep -Fq 'values: dict[str, str]' "$WORK/error_payload_struct_dict.pyi"
grep -Fq '# error payload: StructDictPayloadErrorPayload' "$WORK/error_payload_struct_dict.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_struct_dict.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/optional_payload_errors.pyi" \
    "$ROOT/test/repro/pymodule_optional_payload_errors.elisa" >/dev/null
grep -Fq 'def fail_int(value: int | None = None) -> int: ...' "$WORK/optional_payload_errors.pyi"
grep -Fq 'def fail_text(value: str | bytes | None = None) -> int: ...' "$WORK/optional_payload_errors.pyi"
grep -Fq 'def fail_cstr(value: str | bytes | None = None) -> int: ...' "$WORK/optional_payload_errors.pyi"
grep -Fq 'def fail_object(value: Any | None = None) -> int: ...' "$WORK/optional_payload_errors.pyi"
grep -Fq 'value: int | None' "$WORK/optional_payload_errors.pyi"
grep -Fq '# error payload: int | None' "$WORK/optional_payload_errors.pyi"
grep -Fq '# error payload: StructuredOptionalPayloadErrorPayload' "$WORK/optional_payload_errors.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/optional_payload_errors.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/dict_views.pyi" \
    "$ROOT/test/repro/pymodule_dict_views.elisa" >/dev/null
grep -Fq 'def roundtrip(values: Mapping[int, Sequence[int]]) -> dict[int, list[int]]: ...' "$WORK/dict_views.pyi"
grep -Fq 'def roundtrip_bytes(values: Mapping[str | bytes, Sequence[int]]) -> dict[str, bytes]: ...' "$WORK/dict_views.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/dict_views.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/views.pyi" \
    "$ROOT/test/repro/pymodule_views.elisa" >/dev/null
grep -Fq 'def identity_i64(values: Sequence[int]) -> list[int]: ...' "$WORK/views.pyi"
grep -Fq 'def identity_u8(values: Sequence[int]) -> bytes: ...' "$WORK/views.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/views.pyi"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/dict_view_special.pyi" \
    "$ROOT/test/repro/pymodule_dict_view_special.elisa" >/dev/null
grep -Fq 'def roundtrip_sview(values: Mapping[int, Sequence[str | bytes]]) -> dict[int, list[str]]: ...' "$WORK/dict_view_special.pyi"
grep -Fq 'def roundtrip_cstr(values: Mapping[str | bytes, Sequence[str | bytes]]) -> dict[str, list[str]]: ...' "$WORK/dict_view_special.pyi"
grep -Fq 'def roundtrip_objects(values: Mapping[int, Sequence[Any]]) -> dict[int, list[Any]]: ...' "$WORK/dict_view_special.pyi"
grep -Fq 'def roundtrip_optional(values: Mapping[int, Sequence[int | None]]) -> dict[int, list[int | None]]: ...' "$WORK/dict_view_special.pyi"
grep -Fq 'def roundtrip_optional_objects(values: Mapping[int, Sequence[Any | None]]) -> dict[int, list[Any | None]]: ...' "$WORK/dict_view_special.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/dict_view_special.pyi"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/enums.pyi" \
    "$ROOT/test/repro/pymodule_enums.elisa" >/dev/null
grep -Fq 'def mode_roundtrip(mode: int) -> int' "$WORK/enums.pyi"
grep -Fq 'def plain_roundtrip(value: int) -> int' "$WORK/enums.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/enums.pyi"

PYTHONPATH="$ROOT/scripts" "$PYTHON_BIN" - "$WORK/keyword_fields.pyi" <<'PY'
import sys
from pathlib import Path

from pymodule_pyi import render

manifest = {
    "structs": [{
        "name": "Options",
        "fields": [
            {"name": "class", "type": "i64", "optional": True},
            {"name": "normal", "type": "sview"},
        ],
    }],
    "functions": [{
        "name": "roundtrip",
        "parameters": [{"name": "options", "type": "Options"}],
        "return": "Options",
    }],
}
Path(sys.argv[1]).write_text(render(manifest), encoding="utf-8")
PY
"$PYTHON_BIN" -m py_compile "$WORK/keyword_fields.pyi"
grep -Fq "Options = TypedDict('Options', {'class': NotRequired[int], 'normal': str})" "$WORK/keyword_fields.pyi"

PYTHONPATH="$ROOT/scripts" "$PYTHON_BIN" - "$WORK/keyword_params.pyi" <<'PY'
import sys
from pathlib import Path

from pymodule_pyi import render

manifest = {
    "functions": [{
        "name": "call",
        "parameters": [{"name": "class", "type": "i64"}, {"name": "value", "type": "bool"}],
        "return": "i64",
    }],
}
Path(sys.argv[1]).write_text(render(manifest), encoding="utf-8")
PY
grep -Fq 'def call(_arg0: int, value: bool) -> int: ...' "$WORK/keyword_params.pyi"
grep -Fq "_arg0 represents Elisa parameter 'class'" "$WORK/keyword_params.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/keyword_params.pyi"

echo "pymodule pyi smoke OK"
