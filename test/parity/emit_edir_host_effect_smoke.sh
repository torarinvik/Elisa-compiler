#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/fixtures/edir/host_clock.elisa"
CONSOLE_FIXTURE="$ROOT/test/fixtures/edir/host_console_output.elisa"
CONSOLE_INPUT_FIXTURE="$ROOT/test/fixtures/edir/host_console_input.elisa"
VIRTUAL_FILE_FIXTURE="$ROOT/test/fixtures/edir/host_virtual_file_read.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$BIN" ]] || { echo "emit_edir_host_effect_smoke FAIL: missing stage1 product $BIN" >&2; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "emit_edir_host_effect_smoke FAIL: missing runtime object $RUNTIME" >&2; exit 1; }
unset ELISACORE_BIN || true
export ELISA_STAGE1_BIN="$BIN" ELISA_RUNTIME_OBJ="$RUNTIME"

for optimization in 0 2; do
  artifact="$WORK/host-clock-O$optimization.edir"
  ELISA_EDIR_SOURCE_ROOT="$ROOT" ELISA_ALLOW_STALE_STAGE1=0 bash "$WRAPPER" -emit edir "-O$optimization" -o "$artifact" "$FIXTURE"
  python3 - "$artifact" "$FIXTURE" <<'PY'
from pathlib import Path
import struct
import sys

SCHEMA = 4
PROGRAM_VERSION = 5
INSTRUCTION_COUNT = 4
FUNCTION_COUNT = 2
LOCAL_COUNT = 1
HAS_RETURN = 1
SOURCE_FILE_COUNT = 1
OPCODE_CLOCK_NOW = 20
OPCODE_RANDOM_U64 = 21
OPCODE_RETURN = 19
NO_OPERAND = 0
PROGRAM_HEADER_BYTES = 29
SOURCE_FILE_FIXED_BYTES = 36
SOURCE_FILE_PATH_LENGTH_OFFSET = 32
INSTRUCTION_BYTES = 62
INSTRUCTION_SOURCE_OFFSET = 18
HAS_RETURN_OFFSET = 24

artifact_path, source_path = map(Path, sys.argv[1:])
data = artifact_path.read_bytes()
source = source_path.read_bytes()
source_path_length = struct.unpack_from("<I", data, PROGRAM_HEADER_BYTES + SOURCE_FILE_PATH_LENGTH_OFFSET)[0]
header_bytes = PROGRAM_HEADER_BYTES + SOURCE_FILE_FIXED_BYTES + source_path_length
schema, program_version, instruction_count, local_count = struct.unpack_from("<IIQQ", data)
assert (schema, program_version, instruction_count, local_count, data[HAS_RETURN_OFFSET]) == (SCHEMA, PROGRAM_VERSION, INSTRUCTION_COUNT, LOCAL_COUNT, HAS_RETURN)
assert struct.unpack_from("<I", data, PROGRAM_HEADER_BYTES)[0] == SOURCE_FILE_COUNT
clock = struct.unpack_from("<Hqq", data, header_bytes)
clock_returned = struct.unpack_from("<Hqq", data, header_bytes + INSTRUCTION_BYTES)
random = struct.unpack_from("<Hqq", data, header_bytes + INSTRUCTION_BYTES * 2)
random_returned = struct.unpack_from("<Hqq", data, header_bytes + INSTRUCTION_BYTES * 3)
assert clock == (OPCODE_CLOCK_NOW, NO_OPERAND, NO_OPERAND), clock
assert clock_returned == (OPCODE_RETURN, NO_OPERAND, NO_OPERAND), clock_returned
assert random == (OPCODE_RANDOM_U64, NO_OPERAND, NO_OPERAND), random
assert random_returned == (OPCODE_RETURN, NO_OPERAND, NO_OPERAND), random_returned
effect_source = struct.unpack_from("<QQQIIIII", data, header_bytes + INSTRUCTION_SOURCE_OFFSET)
start_byte, end_byte = effect_source[1], effect_source[2]
assert source[start_byte:end_byte].decode() == "DebuggerHostEffects::clock_now"
random_source = struct.unpack_from("<QQQIIIII", data, header_bytes + INSTRUCTION_BYTES * 2 + INSTRUCTION_SOURCE_OFFSET)
random_start_byte, random_end_byte = random_source[1], random_source[2]
assert source[random_start_byte:random_end_byte].decode() == "DebuggerHostEffects::random_u64"
function_count_offset = header_bytes + instruction_count * INSTRUCTION_BYTES
assert struct.unpack_from("<I", data, function_count_offset)[0] == FUNCTION_COUNT
PY
done

for optimization in 0 2; do
  artifact="$WORK/host-console-output-O$optimization.edir"
  ELISA_EDIR_SOURCE_ROOT="$ROOT" ELISA_ALLOW_STALE_STAGE1=0 bash "$WRAPPER" -emit edir "-O$optimization" -o "$artifact" "$CONSOLE_FIXTURE"
  python3 - "$artifact" "$CONSOLE_FIXTURE" <<'PY'
from pathlib import Path
import struct
import sys

SCHEMA = 4
PROGRAM_VERSION = 5
INSTRUCTION_COUNT = 2
FUNCTION_COUNT = 1
LOCAL_COUNT = 0
HAS_RETURN = 1
SOURCE_FILE_COUNT = 1
OPCODE_CONSOLE_WRITE_BYTE = 22
OPCODE_RETURN = 19
OUTPUT_BYTE = 67
NO_OPERAND = 0
PROGRAM_HEADER_BYTES = 29
SOURCE_FILE_FIXED_BYTES = 36
SOURCE_FILE_PATH_LENGTH_OFFSET = 32
INSTRUCTION_BYTES = 62
INSTRUCTION_SOURCE_OFFSET = 18
HAS_RETURN_OFFSET = 24

artifact_path, source_path = map(Path, sys.argv[1:])
data = artifact_path.read_bytes()
source = source_path.read_bytes()
source_path_length = struct.unpack_from("<I", data, PROGRAM_HEADER_BYTES + SOURCE_FILE_PATH_LENGTH_OFFSET)[0]
header_bytes = PROGRAM_HEADER_BYTES + SOURCE_FILE_FIXED_BYTES + source_path_length
schema, program_version, instruction_count, local_count = struct.unpack_from("<IIQQ", data)
assert (schema, program_version, instruction_count, local_count, data[HAS_RETURN_OFFSET]) == (SCHEMA, PROGRAM_VERSION, INSTRUCTION_COUNT, LOCAL_COUNT, HAS_RETURN)
assert struct.unpack_from("<I", data, PROGRAM_HEADER_BYTES)[0] == SOURCE_FILE_COUNT
output = struct.unpack_from("<Hqq", data, header_bytes)
returned = struct.unpack_from("<Hqq", data, header_bytes + INSTRUCTION_BYTES)
assert output == (OPCODE_CONSOLE_WRITE_BYTE, OUTPUT_BYTE, NO_OPERAND), output
assert returned == (OPCODE_RETURN, NO_OPERAND, NO_OPERAND), returned
output_source = struct.unpack_from("<QQQIIIII", data, header_bytes + INSTRUCTION_SOURCE_OFFSET)
start_byte, end_byte = output_source[1], output_source[2]
assert source[start_byte:end_byte].decode() == "DebuggerHostEffects::console_write_byte"
function_count_offset = header_bytes + instruction_count * INSTRUCTION_BYTES
assert struct.unpack_from("<I", data, function_count_offset)[0] == FUNCTION_COUNT
PY
done

for optimization in 0 2; do
  artifact="$WORK/host-console-input-O$optimization.edir"
  ELISA_EDIR_SOURCE_ROOT="$ROOT" ELISA_ALLOW_STALE_STAGE1=0 bash "$WRAPPER" -emit edir "-O$optimization" -o "$artifact" "$CONSOLE_INPUT_FIXTURE"
  python3 - "$artifact" "$CONSOLE_INPUT_FIXTURE" <<'PY'
from pathlib import Path
import struct
import sys

SCHEMA = 4
PROGRAM_VERSION = 5
INSTRUCTION_COUNT = 2
FUNCTION_COUNT = 1
LOCAL_COUNT = 0
HAS_RETURN = 1
SOURCE_FILE_COUNT = 1
OPCODE_CONSOLE_READ_BYTE = 23
OPCODE_RETURN = 19
NO_OPERAND = 0
PROGRAM_HEADER_BYTES = 29
SOURCE_FILE_FIXED_BYTES = 36
SOURCE_FILE_PATH_LENGTH_OFFSET = 32
INSTRUCTION_BYTES = 62
INSTRUCTION_SOURCE_OFFSET = 18
HAS_RETURN_OFFSET = 24

artifact_path, source_path = map(Path, sys.argv[1:])
data = artifact_path.read_bytes()
source = source_path.read_bytes()
source_path_length = struct.unpack_from("<I", data, PROGRAM_HEADER_BYTES + SOURCE_FILE_PATH_LENGTH_OFFSET)[0]
header_bytes = PROGRAM_HEADER_BYTES + SOURCE_FILE_FIXED_BYTES + source_path_length
schema, program_version, instruction_count, local_count = struct.unpack_from("<IIQQ", data)
assert (schema, program_version, instruction_count, local_count, data[HAS_RETURN_OFFSET]) == (SCHEMA, PROGRAM_VERSION, INSTRUCTION_COUNT, LOCAL_COUNT, HAS_RETURN)
assert struct.unpack_from("<I", data, PROGRAM_HEADER_BYTES)[0] == SOURCE_FILE_COUNT
read = struct.unpack_from("<Hqq", data, header_bytes)
returned = struct.unpack_from("<Hqq", data, header_bytes + INSTRUCTION_BYTES)
assert read == (OPCODE_CONSOLE_READ_BYTE, NO_OPERAND, NO_OPERAND), read
assert returned == (OPCODE_RETURN, NO_OPERAND, NO_OPERAND), returned
read_source = struct.unpack_from("<QQQIIIII", data, header_bytes + INSTRUCTION_SOURCE_OFFSET)
start_byte, end_byte = read_source[1], read_source[2]
assert source[start_byte:end_byte].decode() == "DebuggerHostEffects::console_read_byte"
function_count_offset = header_bytes + instruction_count * INSTRUCTION_BYTES
assert struct.unpack_from("<I", data, function_count_offset)[0] == FUNCTION_COUNT
PY
done

for optimization in 0 2; do
  artifact="$WORK/host-virtual-file-read-O$optimization.edir"
  ELISA_EDIR_SOURCE_ROOT="$ROOT" ELISA_ALLOW_STALE_STAGE1=0 bash "$WRAPPER" -emit edir "-O$optimization" -o "$artifact" "$VIRTUAL_FILE_FIXTURE"
  python3 - "$artifact" "$VIRTUAL_FILE_FIXTURE" <<'PY'
from pathlib import Path
import struct
import sys

SCHEMA = 4
PROGRAM_VERSION = 5
INSTRUCTION_COUNT = 2
FUNCTION_COUNT = 1
LOCAL_COUNT = 0
HAS_RETURN = 1
SOURCE_FILE_COUNT = 1
OPCODE_VIRTUAL_FILE_READ_BYTE = 24
OPCODE_RETURN = 19
RESOURCE_HANDLE = 7
NO_OPERAND = 0
PROGRAM_HEADER_BYTES = 29
SOURCE_FILE_FIXED_BYTES = 36
SOURCE_FILE_PATH_LENGTH_OFFSET = 32
INSTRUCTION_BYTES = 62
INSTRUCTION_SOURCE_OFFSET = 18
HAS_RETURN_OFFSET = 24

artifact_path, source_path = map(Path, sys.argv[1:])
data = artifact_path.read_bytes()
source = source_path.read_bytes()
source_path_length = struct.unpack_from("<I", data, PROGRAM_HEADER_BYTES + SOURCE_FILE_PATH_LENGTH_OFFSET)[0]
header_bytes = PROGRAM_HEADER_BYTES + SOURCE_FILE_FIXED_BYTES + source_path_length
schema, program_version, instruction_count, local_count = struct.unpack_from("<IIQQ", data)
assert (schema, program_version, instruction_count, local_count, data[HAS_RETURN_OFFSET]) == (SCHEMA, PROGRAM_VERSION, INSTRUCTION_COUNT, LOCAL_COUNT, HAS_RETURN)
assert struct.unpack_from("<I", data, PROGRAM_HEADER_BYTES)[0] == SOURCE_FILE_COUNT
read = struct.unpack_from("<Hqq", data, header_bytes)
returned = struct.unpack_from("<Hqq", data, header_bytes + INSTRUCTION_BYTES)
assert read == (OPCODE_VIRTUAL_FILE_READ_BYTE, RESOURCE_HANDLE, NO_OPERAND), read
assert returned == (OPCODE_RETURN, NO_OPERAND, NO_OPERAND), returned
read_source = struct.unpack_from("<QQQIIIII", data, header_bytes + INSTRUCTION_SOURCE_OFFSET)
start_byte, end_byte = read_source[1], read_source[2]
assert source[start_byte:end_byte].decode() == "DebuggerHostEffects::virtual_file_read_byte"
function_count_offset = header_bytes + instruction_count * INSTRUCTION_BYTES
assert struct.unpack_from("<I", data, function_count_offset)[0] == FUNCTION_COUNT
PY
done

echo "emit_edir_host_effect_smoke OK: namespaced clock/random/console/virtual-file calls lower at O0 and O2 with source identity"
