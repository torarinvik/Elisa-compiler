from pathlib import Path
import os
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
EDIR_SCHEMA_VERSION = int(os.environ["EDIR_SCHEMA_VERSION"])
EDIR_PROGRAM_VERSION = int(os.environ["EDIR_PROGRAM_VERSION"])
assert len(data) == EDIR_HEADER_BYTES + 3 * EDIR_INSTRUCTION_BYTES + EDIR_MAIN_FUNCTION_TABLE_BYTES, f"unexpected artifact size: {len(data)}"
schema, version, instruction_count, local_count = struct.unpack_from("<IIQQ", data)
has_return = data[24]
assert (schema, version, instruction_count, local_count, has_return) == (EDIR_SCHEMA_VERSION, EDIR_PROGRAM_VERSION, 3, 0, 1)
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
