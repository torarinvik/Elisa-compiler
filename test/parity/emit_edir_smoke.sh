#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/fixtures/edir/arithmetic.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$BIN" ]] || { echo "emit_edir_smoke FAIL: missing stage1 product $BIN" >&2; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "emit_edir_smoke FAIL: missing runtime object $RUNTIME" >&2; exit 1; }
unset ELISACORE_BIN || true
export ELISA_STAGE1_BIN="$BIN" ELISA_RUNTIME_OBJ="$RUNTIME"

emit_edir() {
  local source_root="$1" output_path="$2" source_path="$3"
  ELISA_EDIR_SOURCE_ROOT="$source_root" bash "$WRAPPER" -emit edir -o "$output_path" "$source_path"
}

artifact="$WORK/arithmetic.edir"
emit_edir "$ROOT" "$artifact" "$FIXTURE"

python3 - "$artifact" "$FIXTURE" <<'PY'
from pathlib import Path
import struct
import sys

artifact_path, source_path = map(Path, sys.argv[1:])
data = artifact_path.read_bytes()
source = source_path.read_bytes()
EDIR_HEADER_PREFIX_BYTES = 29
EDIR_SOURCE_FILE_FIXED_BYTES = 36
source_path_length = struct.unpack_from("<I", data, EDIR_HEADER_PREFIX_BYTES + 32)[0]
EDIR_HEADER_BYTES = EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES + source_path_length
EDIR_INSTRUCTION_BYTES = 62
EDIR_FUNCTION_COUNT_BYTES = 4
EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES = 72
EDIR_MAIN_NAME_BYTES = 4
EDIR_MAIN_FUNCTION_TABLE_BYTES = EDIR_FUNCTION_COUNT_BYTES + EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES + EDIR_MAIN_NAME_BYTES
EDIR_OPCODE_CONSTANT = 1
EDIR_OPCODE_ADD = 2
EDIR_OPCODE_RETURN = 19
assert len(data) == EDIR_HEADER_BYTES + 3 * EDIR_INSTRUCTION_BYTES + EDIR_MAIN_FUNCTION_TABLE_BYTES, f"unexpected artifact size: {len(data)}"
schema, version, instruction_count, local_count = struct.unpack_from("<IIQQ", data)
has_return = data[24]
assert (schema, version, instruction_count, local_count, has_return) == (3, 1, 3, 0, 1)
source_file_count = struct.unpack_from("<I", data, 25)[0]
file_id, logical_path_id, content_digest, line_count, path_length = struct.unpack_from("<QQQQI", data, EDIR_HEADER_PREFIX_BYTES)
logical_path = data[EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES : EDIR_HEADER_BYTES]
assert source_file_count == 1 and file_id == 1
assert logical_path.decode("utf-8") == "test/fixtures/edir/arithmetic.elisa"
assert path_length == len(logical_path)
assert line_count == source.count(b"\n") + 1
FNV_OFFSET_BASIS = 14695981039346656037
FNV_PRIME = 1099511628211
def fnv1a(domain, value):
    result = FNV_OFFSET_BASIS
    for byte in domain + value:
        result = ((result ^ byte) * FNV_PRIME) & ((1 << 64) - 1)
    return result or 1
assert logical_path_id == fnv1a(b"EDIR logical path:", logical_path)
assert content_digest == fnv1a(b"EDIR source content:", source)

def decode_instruction(index):
    offset = EDIR_HEADER_BYTES + index * EDIR_INSTRUCTION_BYTES
    opcode, operand_a, operand_b, file_id, start, end, line, column, end_line, end_column, discriminator = struct.unpack_from(
        "<HqqQQQIIIII", data, offset
    )
    return (opcode, operand_a, operand_b, file_id, start, end, line, column, end_line, end_column, discriminator)

def source_span(line_number, start_text, end_text=None):
    lines = source.splitlines(keepends=True)
    line_prefix = sum(len(part) for part in lines[: line_number - 1])
    line = lines[line_number - 1].decode("ascii")
    start_column = line.index(start_text) + 1
    end_column = start_column + len(end_text if end_text is not None else start_text)
    start = line_prefix + start_column - 1
    end = line_prefix + end_column - 1
    return (1, start, end, line_number, start_column, line_number, end_column, 0)

constant = decode_instruction(0)
addition = decode_instruction(1)
returned = decode_instruction(2)
assert constant[:3] == (EDIR_OPCODE_CONSTANT, 40, 0)
assert constant[3:] == source_span(2, "40")
assert addition[:3] == (EDIR_OPCODE_ADD, 2, 0)
assert addition[3:] == source_span(2, "40", "40 + 2")
assert returned[:3] == (EDIR_OPCODE_RETURN, 0, 0)
assert returned[3:] == source_span(2, "return", "return 40 + 2")
PY

literal_source="$WORK/literal.elisa"
literal_artifact="$WORK/literal.edir"
cat >"$literal_source" <<'EOF'
def main() -> i64:
    return 42
EOF
emit_edir "$WORK" "$literal_artifact" "$literal_source"
python3 - "$literal_artifact" <<'PY'
from pathlib import Path
import struct
import sys

data = Path(sys.argv[1]).read_bytes()
EDIR_HEADER_PREFIX_BYTES = 29
EDIR_SOURCE_FILE_FIXED_BYTES = 36
source_path_length = struct.unpack_from("<I", data, EDIR_HEADER_PREFIX_BYTES + 32)[0]
EDIR_HEADER_BYTES = EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES + source_path_length
EDIR_INSTRUCTION_BYTES = 62
EDIR_FUNCTION_COUNT_BYTES = 4
EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES = 72
EDIR_MAIN_NAME_BYTES = 4
EDIR_MAIN_FUNCTION_TABLE_BYTES = EDIR_FUNCTION_COUNT_BYTES + EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES + EDIR_MAIN_NAME_BYTES
assert len(data) == EDIR_HEADER_BYTES + 2 * EDIR_INSTRUCTION_BYTES + EDIR_MAIN_FUNCTION_TABLE_BYTES
assert struct.unpack_from("<Hqq", data, EDIR_HEADER_BYTES) == (1, 42, 0)
assert struct.unpack_from("<Hqq", data, EDIR_HEADER_BYTES + EDIR_INSTRUCTION_BYTES) == (19, 0, 0)
PY

no_newline_source="$WORK/café:case.elisa"
no_newline_artifact="$WORK/no-newline.edir"
printf 'def main() -> i64:\n    return 7' >"$no_newline_source"
emit_edir "$WORK" "$no_newline_artifact" "$no_newline_source"
python3 - "$no_newline_artifact" "$no_newline_source" <<'PY'
from pathlib import Path
import struct
import sys

artifact_path, source_path = map(Path, sys.argv[1:])
data = artifact_path.read_bytes()
source = source_path.read_bytes()
EDIR_HEADER_PREFIX_BYTES = 29
EDIR_SOURCE_FILE_FIXED_BYTES = 36
path_length = struct.unpack_from("<I", data, EDIR_HEADER_PREFIX_BYTES + 32)[0]
EDIR_HEADER_BYTES = EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES + path_length
file_id, logical_path_id, content_digest, line_count, _ = struct.unpack_from("<QQQQI", data, EDIR_HEADER_PREFIX_BYTES)
logical_path = data[EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES : EDIR_HEADER_BYTES]
FNV_OFFSET_BASIS = 14695981039346656037
FNV_PRIME = 1099511628211
def fnv1a(domain, value):
    result = FNV_OFFSET_BASIS
    for byte in domain + value:
        result = ((result ^ byte) * FNV_PRIME) & ((1 << 64) - 1)
    return result or 1
assert struct.unpack_from("<IIQQBI", data) == (3, 1, 2, 0, 1, 1)
assert file_id == 1 and logical_path.decode("utf-8") == "café:case.elisa"
assert logical_path_id == fnv1a(b"EDIR logical path:", logical_path)
assert content_digest == fnv1a(b"EDIR source content:", source)
assert line_count == 2 and b"\n" not in source[-1:]
assert len(data) == EDIR_HEADER_BYTES + 2 * EDIR_INSTRUCTION_BYTES + EDIR_MAIN_FUNCTION_TABLE_BYTES
PY

local_source="$WORK/local.elisa"
local_artifact="$WORK/local.edir"
cat >"$local_source" <<'EOF'
def main() -> i64:
    answer: i64 = 40
    return answer + 2
EOF
emit_edir "$WORK" "$local_artifact" "$local_source"
python3 - "$local_artifact" "$local_source" <<'PY'
from pathlib import Path
import struct
import sys

artifact_path, source_path = map(Path, sys.argv[1:])
data = artifact_path.read_bytes()
source = source_path.read_bytes()
EDIR_HEADER_PREFIX_BYTES = 29
EDIR_SOURCE_FILE_FIXED_BYTES = 36
source_path_length = struct.unpack_from("<I", data, EDIR_HEADER_PREFIX_BYTES + 32)[0]
EDIR_HEADER_BYTES = EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES + source_path_length
EDIR_INSTRUCTION_BYTES = 62
EDIR_FUNCTION_COUNT_BYTES = 4
EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES = 72
EDIR_MAIN_NAME_BYTES = 4
EDIR_MAIN_FUNCTION_TABLE_BYTES = EDIR_FUNCTION_COUNT_BYTES + EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES + EDIR_MAIN_NAME_BYTES
assert len(data) == EDIR_HEADER_BYTES + 5 * EDIR_INSTRUCTION_BYTES + EDIR_MAIN_FUNCTION_TABLE_BYTES
schema, version, instruction_count, local_count = struct.unpack_from("<IIQQ", data)
assert (schema, version, instruction_count, local_count, data[24]) == (3, 1, 5, 1, 1)

def decode_instruction(index):
    offset = EDIR_HEADER_BYTES + index * EDIR_INSTRUCTION_BYTES
    return struct.unpack_from("<HqqQQQIIIII", data, offset)

def source_span(line_number, start_text, end_text=None):
    lines = source.splitlines(keepends=True)
    line_prefix = sum(len(part) for part in lines[: line_number - 1])
    line = lines[line_number - 1].decode("ascii")
    start_column = line.index(start_text) + 1
    end_column = start_column + len(end_text if end_text is not None else start_text)
    start = line_prefix + start_column - 1
    end = line_prefix + end_column - 1
    return (1, start, end, line_number, start_column, line_number, end_column, 0)

constant, stored, loaded, addition, returned = [decode_instruction(index) for index in range(5)]
assert constant[:3] == (1, 40, 0)
assert constant[3:] == source_span(2, "40")
assert stored[:3] == (5, 0, 0)
assert stored[3:] == source_span(2, "answer", "answer: i64 = 40")
assert loaded[:3] == (4, 0, 0)
assert loaded[3:] == source_span(3, "answer")
assert addition[:3] == (2, 2, 0)
assert addition[3:] == source_span(3, "answer", "answer + 2")
assert returned[:3] == (19, 0, 0)
assert returned[3:] == source_span(3, "return", "return answer + 2")
PY

local_return_source="$WORK/local-return.elisa"
local_return_artifact="$WORK/local-return.edir"
cat >"$local_return_source" <<'EOF'
def main() -> i64:
    answer: i64 = 42
    return answer
EOF
emit_edir "$WORK" "$local_return_artifact" "$local_return_source"
python3 - "$local_return_artifact" <<'PY'
from pathlib import Path
import struct
import sys

data = Path(sys.argv[1]).read_bytes()
EDIR_HEADER_PREFIX_BYTES = 29
EDIR_SOURCE_FILE_FIXED_BYTES = 36
source_path_length = struct.unpack_from("<I", data, EDIR_HEADER_PREFIX_BYTES + 32)[0]
EDIR_HEADER_BYTES = EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES + source_path_length
EDIR_INSTRUCTION_BYTES = 62
EDIR_FUNCTION_COUNT_BYTES = 4
EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES = 72
EDIR_MAIN_NAME_BYTES = 4
EDIR_MAIN_FUNCTION_TABLE_BYTES = EDIR_FUNCTION_COUNT_BYTES + EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES + EDIR_MAIN_NAME_BYTES
assert len(data) == EDIR_HEADER_BYTES + 4 * EDIR_INSTRUCTION_BYTES + EDIR_MAIN_FUNCTION_TABLE_BYTES
assert struct.unpack_from("<IIQQB", data) == (3, 1, 4, 1, 1)
assert [struct.unpack_from("<Hqq", data, EDIR_HEADER_BYTES + index * EDIR_INSTRUCTION_BYTES) for index in range(4)] == [
    (1, 42, 0), (5, 0, 0), (4, 0, 0), (19, 0, 0)
]
PY

# A statically bounded counted loop exercises compiler-emitted compare, branch,
# backward jump, local updates, and source statement grouping.
counted_loop_source="$ROOT/test/fixtures/edir/counted_loop.elisa"
counted_loop_artifact="$WORK/counted-loop.edir"
emit_edir "$ROOT" "$counted_loop_artifact" "$counted_loop_source"
python3 - "$counted_loop_artifact" "$counted_loop_source" <<'PY'
from pathlib import Path
import struct
import sys

artifact_path, source_path = map(Path, sys.argv[1:])
data = artifact_path.read_bytes()
source = source_path.read_bytes()
EDIR_HEADER_PREFIX_BYTES = 29
EDIR_SOURCE_FILE_FIXED_BYTES = 36
EDIR_INSTRUCTION_BYTES = 62
EDIR_FUNCTION_COUNT_BYTES = 4
EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES = 72
EDIR_MAIN_NAME_BYTES = 4
EDIR_MAIN_FUNCTION_TABLE_BYTES = EDIR_FUNCTION_COUNT_BYTES + EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES + EDIR_MAIN_NAME_BYTES
EXPECTED_INSTRUCTION_COUNT = 16
EXPECTED_LOCAL_COUNT = 2
EXPECTED_LOOP_LIMIT = 5
EXPECTED_LOOP_START = 4
EXPECTED_LOOP_EXIT = 14
CONDITION_LOAD_INSTRUCTION_INDEX = 4
TOTAL_UPDATE_LOAD_INSTRUCTION_INDEX = 7
COUNTER_UPDATE_LOAD_INSTRUCTION_INDEX = 10
LOOP_BACK_EDGE_INSTRUCTION_INDEX = 13
COUNTED_LOOP_HEADER_TEXT = b"while counter < 5:"
COMPARISON_OPERATOR_TEXT = b"<"
COMPARISON_OPERATOR_LENGTH = len(COMPARISON_OPERATOR_TEXT)
source_path_length = struct.unpack_from("<I", data, EDIR_HEADER_PREFIX_BYTES + 32)[0]
EDIR_HEADER_BYTES = EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES + source_path_length
assert len(data) == EDIR_HEADER_BYTES + EXPECTED_INSTRUCTION_COUNT * EDIR_INSTRUCTION_BYTES + EDIR_MAIN_FUNCTION_TABLE_BYTES
assert struct.unpack_from("<IIQQB", data) == (3, 1, EXPECTED_INSTRUCTION_COUNT, EXPECTED_LOCAL_COUNT, 1)

def instruction(index):
    return struct.unpack_from("<HqqQQQIIIII", data, EDIR_HEADER_BYTES + index * EDIR_INSTRUCTION_BYTES)

def source_span_for_range(start, end):
    prefix = source[:start].decode("ascii")
    through = source[:end].decode("ascii")
    start_line = prefix.count("\n") + 1
    end_line = through.count("\n") + 1
    start_column = len(prefix.rsplit("\n", 1)[-1]) + 1
    end_column = len(through.rsplit("\n", 1)[-1]) + 1
    return (1, start, end, start_line, start_column, end_line, end_column, 0)

def source_span(start_text, end_text):
    start = source.index(start_text.encode("ascii"))
    end = source.index(end_text.encode("ascii"), start) + len(end_text.encode("ascii"))
    return source_span_for_range(start, end)

instructions = [instruction(index) for index in range(EXPECTED_INSTRUCTION_COUNT)]
assert [item[:3] for item in instructions] == [
    (1, 0, 0), (5, 0, 0), (1, 0, 0), (5, 1, 0),
    (4, 0, 0), (15, EXPECTED_LOOP_LIMIT, 0), (17, EXPECTED_LOOP_EXIT, 0),
    (4, 1, 0), (2, 2, 0), (5, 1, 0),
    (4, 0, 0), (2, 1, 0), (5, 0, 0), (16, EXPECTED_LOOP_START, 0),
    (4, 1, 0), (19, 0, 0),
]
assert instructions[0][3:] == source_span("counter: mutable i64 = 0", "counter: mutable i64 = 0")
assert instructions[1][3:] == instructions[0][3:]
assert instructions[2][3:] == source_span("total: mutable i64 = 0", "total: mutable i64 = 0")
assert instructions[3][3:] == instructions[2][3:]
loop_header_start = source.index(COUNTED_LOOP_HEADER_TEXT)
condition_operator_start = source.index(COMPARISON_OPERATOR_TEXT, loop_header_start)
condition_span = source_span_for_range(condition_operator_start, condition_operator_start + COMPARISON_OPERATOR_LENGTH)
assert all(instructions[index][3:] == condition_span for index in range(CONDITION_LOAD_INSTRUCTION_INDEX, CONDITION_LOAD_INSTRUCTION_INDEX + 3))
total_update_span = source_span("total <- total + 2", "total <- total + 2")
assert all(instructions[index][3:] == total_update_span for index in range(TOTAL_UPDATE_LOAD_INSTRUCTION_INDEX, TOTAL_UPDATE_LOAD_INSTRUCTION_INDEX + 3))
counter_update_span = source_span("counter <- counter + 1", "counter <- counter + 1")
assert all(instructions[index][3:] == counter_update_span for index in range(COUNTER_UPDATE_LOAD_INSTRUCTION_INDEX, COUNTER_UPDATE_LOAD_INSTRUCTION_INDEX + 3))
assert instructions[LOOP_BACK_EDGE_INSTRUCTION_INDEX][3:] == condition_span
assert len({condition_span, total_update_span, counter_update_span}) == 3
return_span = source_span("return total", "return total")
assert instructions[14][3:] == return_span and instructions[15][3:] == return_span
PY

counted_loop_object="$WORK/counted-loop-native.o"
counted_loop_program="$WORK/counted-loop-native"
bash "$WRAPPER" -o "$counted_loop_object" "$counted_loop_source"
clang -Wl,-dead_strip -o "$counted_loop_program" "$counted_loop_object" "$RUNTIME"
set +e
"$counted_loop_program"
counted_loop_native_status=$?
set -e
COUNTED_LOOP_EXPECTED_EXIT=10
[[ "$counted_loop_native_status" -eq "$COUNTED_LOOP_EXPECTED_EXIT" ]] || {
  echo "emit_edir_smoke FAIL: counted-loop native exit $counted_loop_native_status, want $COUNTED_LOOP_EXPECTED_EXIT" >&2
  exit 1
}

unsupported_loop_source="$WORK/unsupported-loop.elisa"
unsupported_loop_artifact="$WORK/unsupported-loop.edir"
printf 'stale artifact\n' >"$unsupported_loop_artifact"
cat >"$unsupported_loop_source" <<'EOF'
def main() -> i64:
    counter: mutable i64 = 0
    total: mutable i64 = 0
    while counter < 5:
        total <- total + 2
        counter <- counter + 2
    return total
EOF
if emit_edir "$WORK" "$unsupported_loop_artifact" "$unsupported_loop_source" >"$WORK/unsupported-loop.stdout" 2>"$WORK/unsupported-loop.stderr"; then
  echo "emit_edir_smoke FAIL: unsupported counted-loop update was accepted" >&2
  exit 1
fi
[[ ! -s "$unsupported_loop_artifact" ]] || {
  echo "emit_edir_smoke FAIL: unsupported counted loop left a stale/non-empty artifact" >&2
  exit 1
}
grep -q 'counted-loop body must use' "$WORK/unsupported-loop.stderr"

# The same source still follows the native backend path and exits with the value
# represented by the EDIR arithmetic slice.
native_object="$WORK/native.o"
native_program="$WORK/native-program"
bash "$WRAPPER" -o "$native_object" "$FIXTURE"
clang -Wl,-dead_strip -o "$native_program" "$native_object" "$RUNTIME"
set +e
"$native_program"
native_status=$?
set -e
[[ "$native_status" -eq 42 ]] || {
  echo "emit_edir_smoke FAIL: native exit $native_status, want 42" >&2
  exit 1
}

# The typed-local EDIR sequence loads the initialized value before arithmetic;
# compile and run the same source natively to check the emitted value path agrees.
local_object="$WORK/local-native.o"
local_program="$WORK/local-native"
bash "$WRAPPER" -o "$local_object" "$local_source"
clang -Wl,-dead_strip -o "$local_program" "$local_object" "$RUNTIME"
set +e
"$local_program"
local_native_status=$?
set -e
[[ "$local_native_status" -eq 42 ]] || {
  echo "emit_edir_smoke FAIL: typed-local native exit $local_native_status, want 42" >&2
  exit 1
}

# The same literal-literal accumulator pattern maps every supported arithmetic
# operator to the debugger's stable EDIR opcode and agrees with native execution.
check_arithmetic_case() {
  local operator="$1" left="$2" right="$3" opcode="$4" expected="$5"
  local case_source="$WORK/operator-${opcode}.elisa"
  local case_artifact="$WORK/operator-${opcode}.edir"
  local case_object="$WORK/operator-${opcode}.o"
  local case_program="$WORK/operator-${opcode}"
  cat >"$case_source" <<EOF
def main() -> i64:
    return $left $operator $right
EOF
  emit_edir "$WORK" "$case_artifact" "$case_source"
  python3 - "$case_artifact" "$operator" "$left" "$right" "$opcode" <<'PY'
from pathlib import Path
import struct
import sys

artifact_path = Path(sys.argv[1])
operator, left, right, expected_opcode = sys.argv[2], *map(int, sys.argv[3:])
data = artifact_path.read_bytes()
EDIR_HEADER_PREFIX_BYTES = 29
EDIR_SOURCE_FILE_FIXED_BYTES = 36
source_path_length = struct.unpack_from("<I", data, EDIR_HEADER_PREFIX_BYTES + 32)[0]
EDIR_HEADER_BYTES = EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES + source_path_length
EDIR_INSTRUCTION_BYTES = 62
EDIR_FUNCTION_COUNT_BYTES = 4
EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES = 72
EDIR_MAIN_NAME_BYTES = 4
EDIR_MAIN_FUNCTION_TABLE_BYTES = EDIR_FUNCTION_COUNT_BYTES + EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES + EDIR_MAIN_NAME_BYTES
assert len(data) == EDIR_HEADER_BYTES + 3 * EDIR_INSTRUCTION_BYTES + EDIR_MAIN_FUNCTION_TABLE_BYTES
instructions = [
    struct.unpack_from("<HqqQQQIIIII", data, EDIR_HEADER_BYTES + index * EDIR_INSTRUCTION_BYTES)
    for index in range(3)
]
assert instructions[0][0:3] == (1, left, 0)
assert instructions[1][0:3] == (expected_opcode, right, 0)
assert instructions[2][0:3] == (19, 0, 0)
assert all(instruction[3] == 1 and instruction[5] > instruction[4] for instruction in instructions)
PY
  bash "$WRAPPER" -o "$case_object" "$case_source"
  clang -Wl,-dead_strip -o "$case_program" "$case_object" "$RUNTIME"
  set +e
  "$case_program"
  local actual=$?
  set -e
  [[ "$actual" -eq "$expected" ]] || {
    echo "emit_edir_smoke FAIL: native $left $operator $right exited $actual, want $expected" >&2
    exit 1
  }
}

check_arithmetic_case - 42 40 3 2
check_arithmetic_case '*' 6 7 11 42
check_arithmetic_case / 84 2 12 42

# Schema 3 supplies explicit function ranges and direct call targets. This
# compiler-owned fixture exercises a regular helper call and bounded tail recursion.
functions_source="$ROOT/test/fixtures/edir/function_calls.elisa"
functions_artifact="$WORK/function-calls.edir"
emit_edir "$ROOT" "$functions_artifact" "$functions_source"
python3 - "$functions_artifact" "$functions_source" <<'PY'
from pathlib import Path
import struct
import sys

artifact_path, source_path = map(Path, sys.argv[1:])
data = artifact_path.read_bytes()
source = source_path.read_bytes()
EDIR_HEADER_PREFIX_BYTES = 29
EDIR_SOURCE_FILE_FIXED_BYTES = 36
EDIR_INSTRUCTION_BYTES = 62
EDIR_FUNCTION_COUNT_BYTES = 4
EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES = 72
EDIR_MAX_CALL_DEPTH = 16
EDIR_OPCODE_CALL = 18
EDIR_SCHEMA_VERSION = 3
source_path_length = struct.unpack_from("<I", data, EDIR_HEADER_PREFIX_BYTES + 32)[0]
header_bytes = EDIR_HEADER_PREFIX_BYTES + EDIR_SOURCE_FILE_FIXED_BYTES + source_path_length
schema, version, instruction_count, local_count, has_return = struct.unpack_from("<IIQQB", data)
assert (schema, version, local_count, has_return) == (EDIR_SCHEMA_VERSION, 1, 1, 1)
assert source.count(b"\n") + 1 == 11
function_table_offset = header_bytes + instruction_count * EDIR_INSTRUCTION_BYTES
function_count, = struct.unpack_from("<I", data, function_table_offset)
assert function_count == 3
descriptor_offset = function_table_offset + EDIR_FUNCTION_COUNT_BYTES
functions = []
final_return_by_name = {
    b"main": b"return add_ten(descend(7))",
    b"descend": b"return descend(depth - 1)",
    b"add_ten": b"return value + 10",
}
for _ in range(function_count):
    descriptor = struct.unpack_from("<QQQQQQIIIIII", data, descriptor_offset)
    function_id, entry, end, file_id, start, finish, start_line, start_column, end_line, end_column, discriminator, name_length = descriptor
    name_start = descriptor_offset + EDIR_FUNCTION_DESCRIPTOR_FIXED_BYTES
    name = data[name_start : name_start + name_length]
    assert function_id != 0 and file_id == 1 and start < finish
    assert 1 <= start_line <= end_line <= 11 and start_column > 0 and end_column > 0
    declaration_start = source.index(b"def " + name + b"(")
    return_start = source.index(final_return_by_name[name], declaration_start)
    line_end = source.find(b"\n", return_start)
    expected_finish = line_end if line_end >= 0 else len(source)
    expected_start_line = source[:declaration_start].count(b"\n") + 1
    expected_start_line_start = source.rfind(b"\n", 0, declaration_start) + 1
    expected_start_column = declaration_start - expected_start_line_start + 1
    expected_end_line = source[:expected_finish].count(b"\n") + 1
    expected_end_line_start = source.rfind(b"\n", 0, expected_finish) + 1
    expected_end_column = expected_finish - expected_end_line_start + 1
    assert (start, finish, start_line, start_column, end_line, end_column, discriminator) == (
        declaration_start,
        expected_finish,
        expected_start_line,
        expected_start_column,
        expected_end_line,
        expected_end_column,
        0,
    )
    functions.append((name, entry, end, function_id, start, finish))
    descriptor_offset = name_start + name_length
assert [function[0] for function in functions] == [b"main", b"descend", b"add_ten"]
assert functions[0][1] == 0
assert all(function[1] < function[2] for function in functions)
assert all(functions[index][2] == functions[index + 1][1] for index in range(len(functions) - 1))
assert descriptor_offset == len(data)
entries = {function[1] for function in functions}
calls = []
for instruction_index in range(instruction_count):
    instruction_offset = header_bytes + instruction_index * EDIR_INSTRUCTION_BYTES
    opcode, operand_a, operand_b, file_id, start, finish, *_ = struct.unpack_from("<HqqQQQIIIII", data, instruction_offset)
    if opcode == EDIR_OPCODE_CALL:
        assert operand_a >= 0 and operand_a in entries and operand_b == EDIR_MAX_CALL_DEPTH
        assert file_id == 1 and start < finish
        calls.append(operand_a)
assert calls == [functions[1][1], functions[2][1], functions[1][1]]
PY

# A fresh destination remains empty when an AST outside the exact supported
# shape is rejected; the emitter must not publish a partial image.
unsupported_source="$WORK/unsupported.elisa"
unsupported_artifact="$WORK/unsupported.edir"
printf 'stale artifact\n' >"$unsupported_artifact"
cat >"$unsupported_source" <<'EOF'
def main() -> i64:
    return 40 + 2 * 3
EOF
if emit_edir "$WORK" "$unsupported_artifact" "$unsupported_source" >"$WORK/unsupported.stdout" 2>"$WORK/unsupported.stderr"; then
  echo "emit_edir_smoke FAIL: unsupported expression was accepted" >&2
  exit 1
fi
[[ ! -s "$unsupported_artifact" ]] || {
  echo "emit_edir_smoke FAIL: unsupported source left a stale/non-empty artifact" >&2
  exit 1
}
grep -q 'both operands of return arithmetic must be integer literals' "$WORK/unsupported.stderr"

unsupported_local_source="$WORK/unsupported-local.elisa"
unsupported_local_artifact="$WORK/unsupported-local.edir"
cat >"$unsupported_local_source" <<'EOF'
def main() -> i64:
    answer: i64 = 40
    return 2 + answer
EOF
if emit_edir "$WORK" "$unsupported_local_artifact" "$unsupported_local_source" >"$WORK/unsupported-local.stdout" 2>"$WORK/unsupported-local.stderr"; then
  echo "emit_edir_smoke FAIL: local in the unsupported right operand was accepted" >&2
  exit 1
fi
[[ ! -s "$unsupported_local_artifact" ]] || {
  echo "emit_edir_smoke FAIL: unsupported local use left a stale/non-empty artifact" >&2
  exit 1
}
grep -q 'left operand of return arithmetic must be the initialized local' "$WORK/unsupported-local.stderr"

zero_source="$WORK/divide-by-zero.elisa"
zero_artifact="$WORK/divide-by-zero.edir"
cat >"$zero_source" <<'EOF'
def main() -> i64:
    return 1 / 0
EOF
if emit_edir "$WORK" "$zero_artifact" "$zero_source" >"$WORK/divide-by-zero.stdout" 2>"$WORK/divide-by-zero.stderr"; then
  echo "emit_edir_smoke FAIL: division by zero was accepted" >&2
  exit 1
fi
[[ ! -s "$zero_artifact" ]] || {
  echo "emit_edir_smoke FAIL: division by zero left an artifact" >&2
  exit 1
}
grep -q 'may overflow or divide by zero' "$WORK/divide-by-zero.stderr"

overflow_source="$WORK/overflow.elisa"
overflow_artifact="$WORK/overflow.edir"
cat >"$overflow_source" <<'EOF'
def main() -> i64:
    return 9223372036854775807 + 1
EOF
if emit_edir "$WORK" "$overflow_artifact" "$overflow_source" >"$WORK/overflow.stdout" 2>"$WORK/overflow.stderr"; then
  echo "emit_edir_smoke FAIL: overflowing addition was accepted" >&2
  exit 1
fi
[[ ! -s "$overflow_artifact" ]] || {
  echo "emit_edir_smoke FAIL: overflowing addition left an artifact" >&2
  exit 1
}
grep -q 'may overflow or divide by zero' "$WORK/overflow.stderr"

# Includes alter the flat-to-original byte mapping. The M0 writer must refuse
# even when the included file contributes no declarations.
include_source="$WORK/include.elisa"
include_helper="$WORK/helper.elisa"
include_artifact="$WORK/include.edir"
cat >"$include_source" <<'EOF'
include "helper.elisa"
def main() -> i64:
    return 42
EOF
cat >"$include_helper" <<'EOF'
# no declarations
EOF
if emit_edir "$WORK" "$include_artifact" "$include_source" >"$WORK/include.stdout" 2>"$WORK/include.stderr"; then
  echo "emit_edir_smoke FAIL: include-expanded source was accepted" >&2
  exit 1
fi
[[ ! -s "$include_artifact" ]] || {
  echo "emit_edir_smoke FAIL: included source left a non-empty artifact" >&2
  exit 1
}
grep -q 'include-expanded source mapping is not supported yet' "$WORK/include.stderr"

# The EDIR CLI requires an explicit destination instead of silently using the
# ordinary object-file default.
if bash "$WRAPPER" -emit edir "$FIXTURE" >"$WORK/no-output.stdout" 2>"$WORK/no-output.stderr"; then
  echo "emit_edir_smoke FAIL: -emit edir accepted a missing -o" >&2
  exit 1
fi
grep -q 'requires an explicit -o output path' "$WORK/no-output.stderr"

# An unwritable target must fail without redirecting binary bytes to stdout.
if emit_edir "$ROOT" "$WORK" "$FIXTURE" >"$WORK/write-failure.stdout" 2>"$WORK/write-failure.stderr"; then
  echo "emit_edir_smoke FAIL: directory output path was accepted" >&2
  exit 1
fi
[[ ! -s "$WORK/write-failure.stdout" ]] || {
  echo "emit_edir_smoke FAIL: failed binary output leaked to stdout" >&2
  exit 1
}
grep -q 'could not open or truncate the requested -o path' "$WORK/write-failure.stderr"

echo "emit_edir_smoke OK: literal/local/arithmetic/counted-loop EDIR, spans, native results, and fail-closed cases"
