"""Bind thread-shareability generic classification to exact declaration offsets."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
THREAD = ROOT / "src/semantic/check_thread_shareability.elisa"
REFERENCE_TYPES = ROOT / "src/semantic/check_thread_shareability/reference_types.elisa"
WALK = ROOT / "src/semantic/check_thread_shareability/walk.elisa"
SMOKE = ROOT / "test/parity/diagnostics_smoke.sh"
POS = ROOT / "test/fixtures/diagnostics/thread_shareability_generic_owner_line_zero.pos.elisa"
NEG = ROOT / "test/fixtures/diagnostics/thread_shareability_generic_owner_line_zero.neg.elisa"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


thread = THREAD.read_text()
reference_types = REFERENCE_TYPES.read_text()
walk = WALK.read_text()
smoke = SMOKE.read_text()
positive = POS.read_text()
negative = NEG.read_text()

owner_lookup = function_source(thread, "thread_generic_name_at_owner")
type_walk = function_source(thread, "thread_type_contains_nonstatic_reference")
type_row = function_source(thread, "thread_index_type_row")
new_index = function_source(thread, "new_thread_callback_index")
named_type = function_source(reference_types, "thread_named_type_contains_nonstatic_reference")
callback_row = function_source(reference_types, "thread_callback_row_may_reference")
declaration_walk = function_source(walk, "check_thread_shareability_declarations")
callback_collect = function_source(walk, "collect_thread_callbacks")
if not all(fragment in owner_lookup for fragment in (
    "table.generic_param_lines.count != table.generic_param_names.count",
    "table.generic_param_lines.count != table.generic_param_owner_offsets.count",
    "owner_offset: u32",
    "encoded_bound_line: u32 = line + 2147483648",
    "table.generic_param_names[generic_index] == name",
    "table.generic_param_owner_offsets[generic_index] == owner_offset",
    "line >= 2147483648",
)) or "line == 0" in owner_lookup:
    raise SystemExit("thread generic lookup must match exact offsets and admit logical line zero")
if "generic_scope_offset: u32" not in type_walk or \
        "generic_scope_line, generic_scope_offset, module_scope" not in type_walk:
    raise SystemExit("recursive thread type traversal must preserve its generic owner's offset")
if "thread_generic_name_at_owner(table, generic_scope_line, generic_scope_offset, name)" not in named_type or \
        "thread_generic_name_at_owner(table, callbacks.function_line, callbacks.function_offset, name)" not in named_type:
    raise SystemExit("thread type classification must use exact struct/alias and active-function owners")
if not all(fragment in named_type for fragment in (
    "table.generic_param_lines.count != table.generic_param_names.count",
    "table.generic_param_lines.count != table.generic_param_owner_offsets.count",
)):
    raise SystemExit("thread type classification must reject malformed generic metadata before lookup")
if "callbacks.type_owner_offsets <- callbacks.type_owner_offsets.push(owner_offset)" not in type_row or \
        "type_owner_offsets: []" not in new_index or \
        "function_offset: THREAD_GENERIC_OWNER_OFFSET_NONE" not in new_index or \
        "callbacks.function_offset <- line.offset" not in declaration_walk or \
        "callbacks.offsets.push(line.offset)" not in callback_collect:
    raise SystemExit("thread type and callback indexes must retain declaration offsets")
if "outer_offset: u32 = callbacks.function_offset" not in callback_row or \
        "callbacks.function_offset <- callbacks.offsets[row]" not in callback_row or \
        "callbacks.function_offset <- outer_offset" not in callback_row:
    raise SystemExit("callback result classification must save, set, and restore the owner offset")

if "#line 0 generic_sibling.elisa" not in positive or \
        "#line 0 concrete_owner.elisa" not in positive or \
        "pointer: i64&" not in positive or \
        "def phantom[T]()" not in positive or "def send(value: T)" not in positive:
    raise SystemExit("positive fixture must keep a concrete T nonshareable beside a same-line generic owner")
if "#line 0 generic_owner.elisa" not in negative or \
        "pointer: i64&" not in negative or \
        "def safe_send[T](value: T)" not in negative or \
        "safe_send[i64](42)" not in negative:
    raise SystemExit("negative fixture must exercise a line-zero generic T with a safe concrete call")
if "check_thread_generic_owner_identity.py" not in smoke or \
        "thread_shareability_generic_owner_line_zero" not in smoke or \
        "is not structurally shareable across threads" not in smoke:
    raise SystemExit("diagnostics smoke must run the source proof and both line-zero fixtures")
