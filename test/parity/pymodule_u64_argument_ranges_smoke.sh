#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

SOURCE="$ROOT/test/repro/pymodule_u64_argument_ranges.elisa"
GENERATED_C="$WORK/u64_argument_ranges.c"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$GENERATED_C" "$SOURCE" >/dev/null

python3 - "$GENERATED_C" <<'PY'
import re
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()

def wrapper(name):
    marker = f"static PyObject *elisa_py_{name}("
    start = source.index(marker)
    next_wrapper = source.find("static PyObject *elisa_py_", start + len(marker))
    return source[start:next_wrapper if next_wrapper >= 0 else len(source)]

def failure_branch(function_source, marker):
    start = function_source.index(marker)
    open_brace = function_source.index("{", start)
    depth = 0
    for index in range(open_brace, len(function_source)):
        if function_source[index] == "{":
            depth += 1
        elif function_source[index] == "}":
            depth -= 1
            if depth == 0:
                return function_source[start:index]
    raise AssertionError(f"unterminated generated failure branch: {marker}")

assert "return value <= UINT64_MAX;" in source, (
    "generated C is missing the portable wider-ULL u64 bound helper"
)

for name, pattern in (
    ("required_u64", r"!elisa_pymodule_ull_fits_u64\s*\(\s*arg0\s*\)"),
    ("optional_u64", r"!elisa_pymodule_ull_fits_u64\s*\(\s*arg0_number\s*\)"),
    ("roundtrip_u64_list", r"!elisa_pymodule_ull_fits_u64\s*\(\s*arg0_number\s*\)"),
    ("roundtrip_u64_set", r"!elisa_pymodule_ull_fits_u64\s*\(\s*arg0_key_number\s*\)"),
    ("roundtrip_u64_dict", r"!elisa_pymodule_ull_fits_u64\s*\(\s*arg0_key_number\s*\)"),
    ("roundtrip_u64_dict", r"!elisa_pymodule_ull_fits_u64\s*\(\s*arg0_value_scalar\s*\)"),
    ("roundtrip_optional_u64_dict", r"!elisa_pymodule_ull_fits_u64\s*\(\s*arg0_value_number\s*\)"),
    ("roundtrip_u64_nested_dict", r"!elisa_pymodule_ull_fits_u64\s*\(\s*arg0_nested_number\s*\)"),
    ("first_u64_fixed", r"!elisa_pymodule_ull_fits_u64\s*\(\s*arg0_number\s*\)"),
):
    assert re.search(pattern, wrapper(name)), (
        f"{name} generated input conversion does not use the u64 bound helper"
    )

optional_dict = wrapper("roundtrip_optional_u64_dict")
optional_dict_failure = failure_branch(
    optional_dict,
    "if (!elisa_pymodule_ull_fits_u64(arg0_value_number)) {",
)
assert 'PyErr_SetString(PyExc_OverflowError, "u64 dictionary value out of range");' in optional_dict_failure
assert "if (arg0_materialized)" in optional_dict_failure, (
    "optional u64 dictionary overflow path skips owned-input cleanup"
)
assert "return NULL;" in optional_dict_failure, (
    "optional u64 dictionary overflow branch is not closed"
)

record_marker = "static int elisa_pymodule_struct_U64Record_from_py("
record_start = source.index(record_marker)
record_end = source.find("\nstatic ", record_start + len(record_marker))
record_helper = source[record_start:record_end if record_end >= 0 else len(source)]
assert len(re.findall(r"!elisa_pymodule_ull_fits_u64\s*\(\s*field_number\s*\)", record_helper)) >= 4, (
    "U64Record required/optional scalar and list fields are missing u64 guards"
)

def record_field_block(field_name):
    marker = f'elisa_pymodule_get_field(object, "{field_name}")'
    field_at = record_helper.index(marker)
    block_start = record_helper.rfind("{ Py_ssize_t field_path_mark", 0, field_at)
    assert block_start >= 0, f"missing generated field block for {field_name}"
    block_end = record_helper.find(
        "elisa_pymodule_current_path_restore(field_path_mark); }", field_at
    )
    assert block_end >= 0, f"unterminated generated field block for {field_name}"
    return record_helper[block_start:block_end]

for field_name in ("view_values", "optional_view_values"):
    field_source = record_field_block(field_name)
    assert re.search(
        r"!elisa_pymodule_ull_fits_u64\s*\(\s*field_number\s*\)",
        field_source,
    ), f"U64Record {field_name} conversion is missing its u64 guard"

for local_name, minimum_count in (("nested_number", 2), ("item_number", 2)):
    guard_count = len(re.findall(
        rf"!elisa_pymodule_ull_fits_u64\s*\(\s*{local_name}\s*\)", source
    ))
    assert guard_count >= minimum_count, (
        f"generated nested/view conversions have only {guard_count} {local_name} u64 guards"
    )

assert re.search(
    r"if\s*\(!elisa_pymodule_ull_fits_u64\(nested_number\)\)\s*\{\s*"
    r"Py_DECREF\(nested_seq\);\s*Py_DECREF\(field_seq\);\s*Py_DECREF\(field_obj\);",
    source,
), "u64 nested struct overflow path does not release its field object"
PY

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule u64 argument range smoke generated-C checks OK (runtime build unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/u64_argument_ranges.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import u64_argument_ranges as module

maximum = (1 << 64) - 1
assert module.required_u64(maximum) == maximum
assert module.optional_u64(maximum) == maximum
assert module.optional_u64() is None
assert module.roundtrip_u64_list([maximum]) == [maximum]
assert module.roundtrip_u64_set({maximum}) == {maximum}
assert module.roundtrip_u64_dict({maximum: maximum}) == {maximum: maximum}
assert module.roundtrip_u64_nested_dict({maximum: [maximum]}) == {maximum: [maximum]}
assert module.roundtrip_optional_u64_dict({maximum: maximum}) == {maximum: maximum}
assert module.roundtrip_optional_u64_dict({maximum: None}) == {maximum: None}
assert module.roundtrip_u64_view([maximum]) == [maximum]
assert module.roundtrip_u64_view_list([[maximum]]) == [[maximum]]
assert module.roundtrip_u64_optional_view_list([[maximum]]) == [[maximum]]
assert module.first_u64_fixed([maximum, 0]) == maximum
assert module.roundtrip_u64_record({
    "value": maximum,
    "optional": maximum,
    "values": [maximum],
    "optional_values": [maximum, None],
    "nested_values": [[maximum]],
    "optional_nested_values": [[maximum, None]],
    "view_values": [maximum],
    "optional_view_values": [maximum, None],
})["value"] == maximum

import gc
import tracemalloc

gc.collect()
tracemalloc.start()
before, _ = tracemalloc.get_traced_memory()
for _ in range(3000):
    try:
        module.roundtrip_u64_record({
            "value": 0,
            "optional": None,
            "values": [],
            "optional_values": [],
            "nested_values": [[maximum + 1]],
            "optional_nested_values": [],
            "view_values": [],
            "optional_view_values": [],
        })
    except OverflowError:
        pass
    else:
        raise AssertionError("nested struct field accepted a value above u64.max")
gc.collect()
after, _ = tracemalloc.get_traced_memory()
tracemalloc.stop()
assert after - before < 65536, (
    f"nested struct field failures leaked Python references: {after - before} bytes"
)

for function, value in (
    (module.required_u64, maximum + 1),
    (module.optional_u64, maximum + 1),
    (module.roundtrip_u64_list, [maximum + 1]),
    (module.roundtrip_u64_set, {maximum + 1}),
    (module.roundtrip_u64_dict, {maximum + 1: maximum}),
    (module.roundtrip_u64_dict, {maximum: maximum + 1}),
    (module.roundtrip_optional_u64_dict, {maximum: maximum + 1}),
    (module.roundtrip_u64_nested_dict, {maximum: [maximum + 1]}),
    (module.roundtrip_u64_view, [maximum + 1]),
    (module.roundtrip_u64_view_list, [[maximum + 1]]),
    (module.roundtrip_u64_optional_view_list, [[maximum + 1]]),
    (module.first_u64_fixed, [maximum + 1, 0]),
    (module.roundtrip_u64_record, {
        "value": maximum + 1,
        "optional": None,
        "values": [],
        "optional_values": [],
        "nested_values": [],
        "optional_nested_values": [],
        "view_values": [],
        "optional_view_values": [],
    }),
    (module.roundtrip_u64_record, {
        "value": 0,
        "optional": None,
        "values": [],
        "optional_values": [],
        "nested_values": [],
        "optional_nested_values": [[maximum + 1]],
        "view_values": [],
        "optional_view_values": [],
    }),
    (module.roundtrip_u64_record, {
        "value": 0,
        "optional": None,
        "values": [],
        "optional_values": [],
        "nested_values": [],
        "optional_nested_values": [],
        "view_values": [maximum + 1],
        "optional_view_values": [],
    }),
    (module.roundtrip_u64_record, {
        "value": 0,
        "optional": None,
        "values": [],
        "optional_values": [],
        "nested_values": [],
        "optional_nested_values": [],
        "view_values": [],
        "optional_view_values": [maximum + 1],
    }),
):
    try:
        function(value)
    except OverflowError:
        pass
    else:
        raise AssertionError(f"{function.__name__} accepted a value above u64.max")
PY

echo "pymodule u64 argument range smoke OK"
