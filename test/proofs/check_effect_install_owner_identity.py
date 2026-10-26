"""Check exact install ownership through parser, cloning, and semantic capture checks."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src/parser/parser_core.elisa"
CORE_INIT = ROOT / "src/parser/parser_core_member_tables.elisa"
SPECIALIZATION = ROOT / "src/parser/parser_effect_specialization.elisa"
DEFERRED = ROOT / "src/parser/parser_effect_deferred.elisa"
PARSER_BLOCK = ROOT / "src/parser/parser_stmt_control_blocks_prefixed.elisa"
PARSER_CLAUSE = ROOT / "src/parser/parser_stmt_control_blocks.elisa"
PARSER_REWRITE = ROOT / "src/parser/parser_effect_handler_rewrite.elisa"
PARSER_DEFERRED = ROOT / "src/parser/parser_effect_deferred.elisa"
PARSER_SPECIALIZATION = ROOT / "src/parser/parser_effect_specialization.elisa"
SEMANTIC = ROOT / "src/semantic/check_abstract_effects.elisa"
SEMANTIC_HANDLERS = ROOT / "src/semantic/check_effect_handlers.elisa"
SEMANTIC_SIGNATURES = ROOT / "src/semantic/check_effect_signatures.elisa"
SEMANTIC_DECLARATIONS = ROOT / "src/semantic/check_effect_declarations.elisa"
FIXTURE = ROOT / "test/fixtures/effects/nested_install_same_line_identity.elisa"
NEGATIVE = ROOT / "test/fixtures/effects/nested_install_same_line_capture_count.neg.elisa"
SAME_NAME_FIXTURE = ROOT / "test/fixtures/effects/install_same_name_handler_identity.elisa"
OUTSIDE_MODULE_NEGATIVE = ROOT / "test/fixtures/effects/install_handler_outside_module.neg.elisa"
CROSS_MODULE_HELPER_FIXTURE = ROOT / "test/fixtures/effects/module_local_handler_helper_cross_module.elisa"
SMOKE = ROOT / "test/parity/effect_handler_stage1_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing effect-install helper {name}")
    return match.group(0)


core = CORE.read_text()
core_init = CORE_INIT.read_text()
specialization = SPECIALIZATION.read_text()
deferred = DEFERRED.read_text()
parser_block = PARSER_BLOCK.read_text()
parser_clause = PARSER_CLAUSE.read_text()
parser_rewrite = PARSER_REWRITE.read_text()
parser_deferred = PARSER_DEFERRED.read_text()
parser_specialization = PARSER_SPECIALIZATION.read_text()
semantic = SEMANTIC.read_text()
semantic_handlers = SEMANTIC_HANDLERS.read_text()
semantic_signatures = SEMANTIC_SIGNATURES.read_text()
semantic_declarations = SEMANTIC_DECLARATIONS.read_text()
fixture = FIXTURE.read_text()
negative = NEGATIVE.read_text()
same_name_fixture = SAME_NAME_FIXTURE.read_text()
outside_module_negative = OUTSIDE_MODULE_NEGATIVE.read_text()
cross_module_helper_fixture = CROSS_MODULE_HELPER_FIXTURE.read_text()
smoke = SMOKE.read_text()

for fragment in (
    "effect_install_offsets: mutable darray[u32]",
    "effect_install_parents: mutable darray[u32]",
    "effect_install_capture_ids: mutable darray[u32]",
    "effect_clone_install_ids: mutable darray[u32]",
):
    if fragment not in core:
        raise SystemExit(f"Parser must store exact install identity metadata: {fragment}")
for fragment in (
    "effect_install_offsets: []",
    "effect_install_parents: []",
    "effect_install_capture_ids: []",
    "effect_clone_install_ids: []",
):
    if fragment not in core_init:
        raise SystemExit(f"Parser must initialize install identity metadata: {fragment}")

row = function_source(specialization, "effect_install_row_at")
if "effect_install_lines[index] == line" not in row or \
        "effect_install_offsets[index] == offset" not in row:
    raise SystemExit("parser install annotation lookup must join the exact (line, offset) pair")
parent = function_source(specialization, "effect_install_parent")
if "(install_id - 1).usize()" not in parent or "effect_install_parents[index]" not in parent:
    raise SystemExit("parent chains must use unique one-based install IDs")
captures = function_source(specialization, "effect_install_captures_at")
if "effect_install_capture_ids[index] == install_id" not in captures:
    raise SystemExit("capture expressions must stay scoped to one install ID")
for caller in (specialization, deferred):
    if "effect_install_parent(current)" not in caller:
        raise SystemExit("all install-chain walks must follow the ID-indexed parent relation")
if "effect_clone_install_ids[clone_index] != parser.effect_active_install" not in specialization or \
        "parser.effect_clone_install_ids <- parser.effect_clone_install_ids.push(parser.effect_active_install)" not in specialization:
    raise SystemExit("clone selection and registration must retain the install identity")

if "installed_install_id <- (parser.effect_install_lines.count + 1.usize()).u32()" not in parser_block or \
        "effect_install_offsets <- parser.effect_install_offsets.push(first_token.start)" not in parser_block or \
        "effect_install_parents <- parser.effect_install_parents.push(saved_effect_install)" not in parser_block or \
        "effect_active_install <- installed_install_id" not in parser_block or \
        "parser.effect_active_install <- saved_effect_install" not in parser_block:
    raise SystemExit("parser block entry/restore must maintain a unique, nested install identity")
if "consume_can_handler_clause(clause, installed_effect, installed_handler, installed_arguments, first_token.start)" not in parser_block:
    raise SystemExit("the install annotation producer must receive the exact block token offset")
for marker in (
    'owner: "__effect_install"',
    'owner: "__effect_install_effect"',
    'owner: "__effect_install_identity_mismatch"',
    'owner: "__effect_install_capture_count"',
):
    clause_row = parser_clause[parser_clause.find(marker):]
    if not clause_row or "offset: install_offset" not in clause_row[:350]:
        raise SystemExit(f"semantic install marker must retain its block offset: {marker}")
if 'owner: "__effect_install_capture", name: capture_name, line: line, offset: first_token.start' not in parser_block:
    raise SystemExit("capture annotations must carry the exact install block position")
if 'owner: "__effect_install_capture_count", name: installed_handler_value, line: effect_start_token.line, offset: install_offset, identity_id: arguments.count.u32()' not in parser_clause:
    raise SystemExit("capture count rows must keep location and payload in separate fields")

install_position = function_source(semantic, "ae_install_position_index_at")
if "index.lines[low] == line" not in install_position or \
        "index.offsets[low] == offset" not in install_position or \
        "index.lines[row] == line and index.offsets[row] == offset" not in install_position:
    raise SystemExit("semantic install metadata must join exact block coordinates")
install_index = function_source(semantic, "ae_effect_install_position_index")
if 'annotation.owner == "__effect_install_effect"' not in install_index or \
        'annotation.owner == "__effect_install_capture_count"' not in install_index or \
        'annotation.owner == "__effect_install_identity_mismatch"' not in install_index or \
        "ae_install_position_index_at(index, annotation.line, annotation.offset)" not in install_index or \
        "index.capture_counts[install_row.usize()] <- annotation.identity_id" not in install_index:
    raise SystemExit("effect, capture, and mismatch rows must be prejoined by exact install coordinates")
handler_index = function_source(semantic, "ae_handler_semantic_index")
if "annotation.identity_id" not in handler_index or \
        "target_effect_ids[handler_row]" not in handler_index or \
        "realization_heads" not in handler_index or \
        "realization_next" not in handler_index:
    raise SystemExit("handler target and realization metadata must be indexed by exact handler identity")
collector = function_source(semantic, "ae_collect_install_statements")
if "statement_pos.line, statement_pos.offset" not in collector or \
        "ae_install_position_index_at(installs" not in collector or \
        "ae_handler_realization_head(handlers, handler_identity_id)" not in collector:
    raise SystemExit("install collection must use exact block coordinates and indexed handler rows")

signature = function_source(semantic_signatures, "ae_handler_operation_signature")
if signature.count("annotation.identity_id == handler_identity_id") < 2 or \
        "handler_identity_id == 0" not in signature:
    raise SystemExit("handler operation/signature ordinal pairing must stay inside one exact handler identity")
duplicate = function_source(semantic_declarations, "ae_duplicate_handler_operation_declared")
if "handler_identity_id == 0" not in duplicate or \
        "annotation.identity_id == handler_identity_id" not in duplicate:
    raise SystemExit("duplicate-operation checks must not combine same-named module handlers")

parser_defaults = function_source(parser_clause, "materialize_handler_capture_defaults")
parser_install = function_source(parser_clause, "consume_can_handler_clause")
parser_operation_lookup = function_source(parser_rewrite, "handler_declares_operation")
parser_identity_lookup = function_source(parser_rewrite, "handler_rewrite_identity")
parser_operation_callee = function_source(parser_rewrite, "handler_operation_callee")
parser_operations = function_source(parser_rewrite, "handler_declares_operation_identity")
parser_known = function_source(parser_rewrite, "handler_is_known")
clone_capture = function_source(parser_specialization, "effect_clone_capture_abi")
clone_register = function_source(parser_specialization, "effect_register_clones")
install_specializer = function_source(parser_specialization, "effect_specialize_install_statements")
deferred = function_source(parser_deferred, "defer_generic_effect_call")
for helper in (parser_defaults, parser_install, parser_operations, parser_known, clone_capture, clone_register, deferred):
    if "handler_identity_id == 0" not in helper and \
            "installed_handler_identity_id == 0" not in helper and \
            "current_handler_identity_id != 0" not in helper and \
            "parser.effect_install_handler_identity_at(install_id) == 0" not in helper:
        raise SystemExit("parser handler consumers must explicitly fail closed on identity 0")
if "parser.handler_capture_identity_ids[owner_index] == handler_identity_id" not in parser_defaults or \
        "handler_annotation.identity_id == installed_handler_identity_id" not in parser_install or \
        "parser.handler_rewrite_identity(handler_name)" not in parser_operation_lookup or \
        "parser.handler_identity_for_name(handler_name, parser.handler_rewrite_owner())" not in parser_identity_lookup or \
        "parser.effect_install_handler_identity_at(parser.effect_active_install)" not in parser_identity_lookup or \
        "active_handler == handler_name" not in parser_identity_lookup or \
        "handler_identity_id <- active_handler_identity_id" not in parser_identity_lookup or \
        "parser.handler_rewrite_identity(handler)" not in parser_operation_callee or \
        "parser.handler_operation_name_for_identity(handler, operation, handler_identity_id)" not in parser_operation_callee or \
        "parser.handler_identity_is_module_local(handler_identity_id)" not in parser_operation_callee or \
        "parser.handler_identity_owner(handler_identity_id)" not in parser_operation_callee or \
        "parser.effect_active_install <- install_id" not in install_specializer or \
        "parser.rewrite_handler_statements(inner_body, effect_ref, handler_name, actual_captures)" not in install_specializer or \
        parser_operations.count("annotation.identity_id == handler_identity_id") < 2 or \
        "annotation.identity_id == handler_identity_id" not in parser_known or \
        "parser.handler_capture_identity_ids[owner_index] != handler_identity_id" not in clone_capture or \
        "parser.effect_install_handler_identity_at(install_id) == 0" not in clone_register or \
        "parser.handler_capture_identity_ids[capture_index] == current_handler_identity_id" not in deferred:
    raise SystemExit("parser capture, operation, clone, and authority joins must use the exact handler identity")

if fixture.count("#line 0 nested-install-owner.elisa") != 3 or not all(
    fragment in fixture
    for fragment in (
        "handler LeftHandler(value: i64) for LeftValue:",
        "handler RightHandler(value: i64) for RightValue:",
        "can LeftValue with LeftHandler(10):",
        "can RightValue with RightHandler(32):",
        "return effectful_sum()",
        "return LeftValue.read() + RightValue.read()",
    )
):
    raise SystemExit("nested line-zero fixture must exercise both install owners and their captures")
if negative.count("#line 0 nested-install-capture-count.elisa") != 3 or not all(
    fragment in negative
    for fragment in (
        "can Tick with Add(1):",
        "can Tick with Add:",
        "Tick.ping()",
    )
):
    raise SystemExit("negative fixture must give same-line nested installs distinct capture counts")
if same_name_fixture.count("handler H(") != 2 or not all(
    fragment in same_name_fixture
    for fragment in (
        "handler H(value: i64) for LeftTick:",
        "handler H() for RightTick:",
        "can LeftTick with H(10):",
        "can RightTick with H:",
        "return A::run() + B::run()",
    )
):
    raise SystemExit("same-name module fixture must exercise distinct target and capture metadata")
if "module B:" not in outside_module_negative or \
        "handler H() for Tick:" not in outside_module_negative or \
        "can Tick with H:" not in outside_module_negative:
    raise SystemExit("bare install outside the only handler module must exercise unresolved identity")
if "handler H(value: i64) for Tick:" not in cross_module_helper_fixture or \
        "can Tick with H(42):" not in cross_module_helper_fixture or \
        "return Util::emit_tick()" not in cross_module_helper_fixture or \
        "module Util:" not in cross_module_helper_fixture or \
        "def emit_tick() -> i64 can[A::Tick]:" not in cross_module_helper_fixture or \
        "return A::Tick.ping()" not in cross_module_helper_fixture:
    raise SystemExit("cross-module helper fixture must lower through its installing module's exact handler")
if "check_effect_install_owner_identity.py" not in smoke or \
        'run_positive "nested_install_same_line_identity.elisa"' not in smoke or \
        'run_positive "install_same_name_handler_identity.elisa"' not in smoke or \
        'run_positive "module_local_handler_helper_cross_module.elisa"' not in smoke or \
        'run_native_result "nested_install_same_line_identity.elisa" 42' not in smoke or \
        'run_native_result "install_same_name_handler_identity.elisa" 42' not in smoke or \
        'run_native_result "module_local_handler_helper_cross_module.elisa" 42' not in smoke or \
        'run_zero_overhead_ir "nested_install_same_line_identity.elisa"' not in smoke or \
        'run_zero_overhead_ir "install_same_name_handler_identity.elisa"' not in smoke or \
        'run_zero_overhead_ir "module_local_handler_helper_cross_module.elisa"' not in smoke or \
        'run_negative "install_handler_outside_module.neg.elisa" \'undefined identifier "H"\'' not in smoke or \
        'run_negative "nested_install_same_line_capture_count.neg.elisa" \'effect handler "Add" requires 1 capture argument(s), got 0\'' not in smoke:
    raise SystemExit("effect smoke must compile, execute, inspect, and reject the same-line regressions")

print("effect install owner identity source proof OK")
