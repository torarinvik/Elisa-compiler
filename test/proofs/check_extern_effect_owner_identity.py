"""Extern capability rows must retain both declaration and module identity."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text()


def function_text(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        text,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


parser = source("src/parser/parser_export_surface.elisa")
parser_probes = source("src/parser/parser_extern_header_probes.elisa")
parser_modules = source("src/parser/parser_decl_module.elisa")
checker = source("src/semantic/check_ungranted_panic.elisa")
symbols = source("src/semantic/symbols.elisa")
abstract_effects = source("src/semantic/check_abstract_effects.elisa")
effect_refs = source("src/semantic/resolve_types_effect_refs.elisa")
resolve_types = source("src/semantic/resolve_types.elisa")
grant_checker = source("src/semantic/check_ungranted_panic_grants.elisa")
coverage_checker = source("src/semantic/check_ungranted_panic_coverage.elisa")
types = source("src/semantic/semantic_types_symbol_table.elisa")
global_effect_sources = source("src/semantic/check_global_permissions/axis_projection.elisa")
fixture = source("test/repro/extern_cross_module_effect_leaf_collision.elisa")

nested_name = function_text(parser_modules, "qualify_nested_module_name")
if not all(fragment in nested_name for fragment in (
    "parser.current_module == \"\"",
    "module_name_is_qualified(name)",
    "append_machine_name_text(name_bytes, parser.current_module)",
    "append_machine_name_text(name_bytes, name)",
)):
    raise SystemExit("nested module declarations must store their full canonical path before semantic collection")
symbol_modules = function_text(symbols, "collect_range_with_variadics")
if not all(fragment in symbol_modules for fragment in (
    "outer_module: sview = table.current_module",
    "table.current_module <- name",
    "table.current_module <- outer_module",
)):
    raise SystemExit("signature effect module tags must follow the parser's already-qualified module name")
source_module_walk = function_text(checker, "collect_effect_sources")
if "extern_join_module_scope(current_module, name, table)" not in source_module_walk:
    raise SystemExit("effect source traversal must preserve the canonical nested module path")

for row in (
    'owner: name, name: "__extern_decl", module: parser.current_module, line: token.line, offset: token.start',
    'owner: name, name: "__extern_effect", module: parser.current_module, line: token.line, offset: token.start',
    'owner: "__extern_effect_ref", name: extern_effect_ref, module: parser.current_module, line: token.line, offset: token.start',
    'owner: name, name: "__extern_effect_blocking", module: parser.current_module, line: token.line, offset: token.start',
):
    if row not in parser:
        raise SystemExit(f"extern effect metadata must carry module and declaration position: {row}")
if "parser.record_extern_effect_row(name, token.line, token.start)" not in parser or \
        'owner: owner, name: "__extern_effect_row_complete", module: parser.current_module, line: line, offset: owner_offset' not in parser_probes or \
        'owner: "__extern_effect_row_text", name: row, module: parser.current_module, line: line, offset: owner_offset' not in parser_probes:
    raise SystemExit("complete extern row text and marker must carry the same module and owner position")

effect_ref = function_text(checker, "extern_effect_ref_at")
if not all(fragment in effect_ref for fragment in (
    'annotations[probe].owner == "__extern_effect_ref"',
    "annotations[probe].module == module",
    "annotations[probe].line == line and annotations[probe].offset == offset",
)):
    raise SystemExit("fallback extern refs must join by module and exact declaration position")
effect_row = function_text(checker, "extern_effect_row_at")
if not all(fragment in effect_row for fragment in (
    'annotation.name == "__extern_effect_row_complete"',
    'annotation.owner == "__extern_effect_row_text"',
    "annotation.module != module or annotation.line != line or annotation.offset != offset",
    "complete_count == 1 and text_count == 1",
)):
    raise SystemExit("complete extern rows must pair by exact module and declaration position")

row_splitter = function_text(checker, "collect_extern_effect_row")
if not all(fragment in row_splitter for fragment in (
    "byte == 44",
    "depth == 0",
    "effect_ref_trim_layout(row[start:index])",
    "effect_ref_trim_layout(row[start:row.len])",
    "table <- extern_effect_add_declared_ref(module, owner, effect_ref, table)",
)):
    raise SystemExit("extern effect rows must split every top-level ref and preserve module identity")
declared_row_add = function_text(checker, "extern_effect_add_declared_ref")
if "effect_ref_via(effect_ref)" not in declared_row_add or \
        "extern_effect_index_add_ref(module, owner, via_ref, table)" not in declared_row_add:
    raise SystemExit("extern via rows must retain both abstract and concrete requirements in the module index")

index_fields = (
    "extern_effect_modules:",
    "extern_effect_owners:",
    "extern_effect_row_modules:",
    "extern_effect_row_owners:",
    "extern_effect_row_names:",
    "extern_declaration_modules:",
    "extern_declaration_owners:",
    "extern_declaration_counts:",
    "function_effect_source_module:",
)
if not all(field in types for field in index_fields):
    raise SystemExit("symbol table must keep declaration presence and refs in a module-scoped extern index")
index_add = function_text(checker, "extern_effect_index_add_ref")
if not all(fragment in index_add for fragment in (
    "extern_effect_index_declare(module, owner, table)",
    "extern_effect_row_modules[row] == module",
    "extern_effect_row_owners[row] == owner",
    "extern_effect_row_names[row] == effect_ref",
)):
    raise SystemExit("module-scoped extern refs must be deduplicated by (module, leaf, ref)")
extern_only = function_text(checker, "extern_module_owner_is_extern_only")
if not all(fragment in extern_only for fragment in (
    "symbol.module_owner == module",
    "table.extern_declaration_modules[row] == module",
    "function_count == 1.usize() and declaration_count == 1.usize()",
)):
    raise SystemExit("extern effect rows must fail closed for same-module overloads and regular-function collisions")

collector = function_text(checker, "collect_extern_effects")
complete_branch = collector.find("if complete_row.complete:")
fallback_branch = collector.find("else:", complete_branch)
if complete_branch < 0 or fallback_branch < 0 or not (
    complete_branch < collector.find("collect_extern_effect_row(annotation.module, annotation.owner, complete_row.text, table)", complete_branch)
    < fallback_branch
    < collector.find('extern_effect_ref_at(annotations, annotation.module, annotation.line, annotation.offset)', fallback_branch)
    < collector.find('"Permission"', fallback_branch)
):
    raise SystemExit("complete rows, including can[], must stay on the full-row path and never fall through to Permission")
if "extern_effect_index_declare(annotation.module, annotation.owner, table)" not in collector:
    raise SystemExit("an explicit empty can[] row must still register its exact module/owner declaration")
if 'annotation.name == "__extern_decl"' not in collector or \
        "extern_declaration_index_add(annotation.module, annotation.owner, table)" not in collector:
    raise SystemExit("extern-only overload classification must count every callable extern declaration by module")

qualified_module = function_text(checker, "extern_qualified_module")
if not all(fragment in qualified_module for fragment in (
    "binding_module_alias_row_before(alias_head, requester, table)",
    "BINDING_MODULE_ALIAS_ROW_AMBIGUOUS",
    "binding_resolve_module_alias_target(qualifier, requester, table)",
    "extern_module_path_exists(qualifier, table)",
)):
    raise SystemExit("qualified extern lookup must honor exact-position alias resolution before root fallback")
bare_module = function_text(checker, "extern_bare_module_for_call")
if not all(fragment in bare_module for fragment in (
    "errorset_import_scope(table.definite_import_annotations",
    "requester.line, requester.offset, call_offset_present",
    "candidate_module != selected",
    "selected_direct: mutable bool = false",
    "rank == best_rank and direct and not selected_direct",
    "direct == selected_direct and selected != candidate_module",
    "errorset_import_scope(table.possible_import_annotations, candidate_module, name, caller_module, requester.line, requester.offset, call_offset_present)",
    "possible_rank > best_rank",
)):
    raise SystemExit("bare extern calls must honor direct-over-import ties and only reject source-visible possible imports that can win")

outside_checker = function_text(grant_checker, "check_ungranted_call_expression")
if not all(fragment in outside_checker for fragment in (
    "extern_call_target(expression, table)",
    "extern_qualified_module(target.qualifier, caller_module, requester, table)",
    "extern_bare_module_for_call(callee_name, caller_module, requester, table)",
    "extern_module_owner_is_extern_only",
    "extern_effect_index_refs",
    "return extern_effect_index_refs(resolved.module, target.name, table)",
    "return extern_effect_index_refs(selected.module, target.name, table)",
    "function_effect_refs(table, callee_name, resolved.module, true)",
    "function_effect_refs(table, callee_name, selected_module.module, true)",
    "function_has_effect(table, callee_name, selected_function_module, true)",
    'target.qualifier == "" and names_contains(bound_names, callee_name)',
)):
    raise SystemExit("outside-grant call checks must use exact extern rows and shadow only bare callees")
postfix_checker = function_text(grant_checker, "check_ungranted_panic_statements")
if not all(fragment in postfix_checker for fragment in (
    "extern_call_target(expression, table)",
    "first_uncovered_extern_ref",
    "extern_module_owner_is_extern_only",
    "selected_regular_module <- resolved.module",
    "selected_regular_module <- selected_module.module",
    "first_uncovered_declared_ref(table, grant_callee, selected_regular_module, true",
    "function_first_declared_effect_ref(table, grant_callee, selected_regular_module, true)",
    'grant_target.qualifier == "" and names_contains(bound_names, grant_callee)',
)):
    raise SystemExit("postfix-grant checks must use exact selected-module declared rows and fail closed on unresolved names")
block_checker = function_text(coverage_checker, "cov_check_call")
if not all(fragment in block_checker for fragment in (
    "extern_qualified_module(target.qualifier, caller_module, requester, table)",
    "extern_bare_module_for_call(callee, caller_module, requester, table)",
    "cov_extern_call_uncovered_ref",
    "extern_module_owner_is_extern_only",
    "extern_regular_function_owner_is_unique(resolved.module, callee, table)",
    "cov_call_uncovered_ref(table, coverage_annotations, resolved.module, callee, granted)",
    'target.qualifier == "" and names_contains(bound_names, callee)',
    "return if extern_effect_index_has_declaration(resolved.module, callee, table)",
)):
    raise SystemExit("block-grant checks must use selected module rows and preserve bare-name fail-closed behavior")
if "function_effect_refs(table, callee, module, true)" not in function_text(coverage_checker, "cov_call_uncovered_ref"):
    raise SystemExit("direct block coverage must filter declared and inferred regular-function rows by resolved module")

block_gap = function_text(checker, "register_block_grant_gaps")
if not all(fragment in block_gap for fragment in (
    "register_block_grant_expression_gaps(owner, expression",
    "visible_names: mutable darray[sview]",
    "visible_names.push(name)",
    "pattern_bound_names(arm.pattern, arm_names)",
    "combined_clause: mutable darray[sview] = [grant for grant in enclosing_clause]",
    "combined_clause.extend(clause)",
    "body, combined_clause, true, caller_module",
)):
    raise SystemExit("transitive block-gap walk must preserve visible binders and cumulative nested grants")
gap_call = function_text(checker, "register_block_grant_call_gap")
if not all(fragment in gap_call for fragment in (
    "extern_qualified_module(target.qualifier, caller_module, requester, table)",
    "extern_bare_module_for_call(gap_callee, caller_module, requester, table)",
    "extern_module_owner_is_extern_only",
    "extern_effect_index_refs",
    "function_effect_refs(table, gap_callee, resolved.module, true)",
    "function_effect_refs(table, gap_callee, selected_module.module, true)",
    "extern_regular_function_owner_is_unique",
    'target.qualifier == "" and names_contains(visible_names, gap_callee)',
)):
    raise SystemExit("transitive block-gap calls must use scoped extern identities and call-site-visible binders")
gap_ref = function_text(checker, "register_block_gap_ref")
if not all(fragment in gap_ref for fragment in (
    "owner_module: sview",
    "extern_regular_function_owner_is_unique(owner_module, owner, table)",
    "table.function_effect_module[known_index] == owner_module",
    "table.function_effect_module <- table.function_effect_module.push(owner_module)",
)):
    raise SystemExit("block-gap rows must retain exact caller module identity and fail closed for same-module overloads")
gap_dedupe = function_text(checker, "register_block_grant_gaps")
if not all(fragment in gap_dedupe for fragment in (
    "table.function_effect_module[row_index] == caller_module",
    "table.function_effect_module <- table.function_effect_module.push(caller_module)",
)):
    raise SystemExit("Unsafe.Alias gap rows must dedupe within the selected module only")
for statement_shape in (
    "Stmt.VarDecl(name, type_expression, value, line)",
    "Stmt.Assign(target, operator, value, line)",
    "Stmt.Return(value, line)",
    "Stmt.If(condition, then_body, else_body, line)",
    "Stmt.While(condition, body, line)",
    "Stmt.For(bind, variables, iterable, body, line)",
    "Stmt.Match(scrutinee, arms, line)",
    "if operator == TokenKind.Assign:",
):
    if statement_shape not in block_gap:
        raise SystemExit(f"block-gap source walk must inspect calls in {statement_shape}")
gap_expression = function_text(checker, "register_block_grant_expression_gaps")
if not all(fragment in gap_expression for fragment in (
    "Expr.Call(callee, arguments, argument_names, call_pos)",
    "Expr.Index(object, index, index_pos)",
    "Expr.Binary(left, operator, right, binary_pos)",
    "Expr.Match(scrutinee, arms, match_pos)",
    "Expr.Block(block_statements, value, captures, block_pos)",
    "body_block_tail_visible_names(block_statements, visible_names)",
    "Lambda expressions are deferred bodies",
)):
    raise SystemExit("block-gap expression traversal must find nested calls and leave deferred lambdas to fn-value analysis")
if "collect_bound_names(body, bound_names)" in function_text(checker, "collect_effect_sources"):
    raise SystemExit("block-gap extern lookup must not use function-wide binder overcollection")

source_call = function_text(checker, "body_effect_refs_for_call")
if not all(fragment in source_call for fragment in (
    "extern_qualified_module(target.qualifier, caller_module, requester, table)",
    "extern_bare_module_for_call(target.name, caller_module, requester, table)",
    "extern_declaration_index_has(resolved.module, target.name, table)",
    "extern_module_owner_is_extern_only",
    "extern_effect_index_refs",
    "function_effect_refs(table, target.name, resolved.module, true)",
    "function_effect_refs(table, target.name, selected.module, true)",
    'target.qualifier == "" and names_contains(visible_names, target.name)',
    'target.name == "panic" and target.qualifier == ""',
)):
    raise SystemExit("body effect forwarding must resolve exact extern owner and honor local callback/panic shadowing")
source_walk = function_text(checker, "body_statement_effect_facts")
for statement_shape in (
    "Stmt.Expr(expression, line)",
    "Stmt.Return(value, line)",
    "Stmt.VarDecl(name, type_expression, value, line)",
    "Stmt.Assign(target, operator, value, line)",
    "Stmt.If(condition, then_body, else_body, line)",
    "Stmt.For(bind, variables, iterable, body, line)",
    "Stmt.Match(scrutinee, arms, line)",
    "visible_names.push(name)",
):
    if statement_shape not in source_walk:
        raise SystemExit(f"effect source inference must walk {statement_shape} with source-order bindings")
source_expr = function_text(checker, "body_expression_effect_facts")
if not all(fragment in source_expr for fragment in (
    "Expr.Call(callee, arguments, argument_names, call_pos)",
    "body_effect_refs_for_call(expression, line, caller_module, visible_names, table)",
    "body_statement_effect_facts(arm.body, false, caller_module, arm_names, table)",
    "Expr.Block(block_statements, value, captures, block_pos)",
    "body_block_tail_visible_names(block_statements, visible_names)",
)):
    raise SystemExit("effect source inference must find qualified/imported calls nested in expressions and blocks")
block_tail = function_text(checker, "body_block_tail_visible_names")
if not all(fragment in block_tail for fragment in (
    "Stmt.VarDecl(name, type_expression, value, line)",
    "Stmt.Assign(target, operator, value, line)",
    "body_assignment_bound_names(target, visible_names) if operator == TokenKind.Assign",
)):
    raise SystemExit("value-block tails must see source-order local declarations and destructured assignment binders")
assignment_names = function_text(checker, "body_assignment_bound_names")
if not all(fragment in assignment_names for fragment in (
    "Expr.Ident(name, position)",
    "Expr.Array(targets, position) | Expr.Tuple(targets, position)",
    "body_assignment_bound_names(child, names)",
    "Expr.Paren(inner, position)",
)):
    raise SystemExit("sequential local shadow tracking must extract nested array/tuple/paren assignment targets")
if "body_assignment_bound_names(target, visible_names) if operator == TokenKind.Assign" not in source_walk:
    raise SystemExit("the body effect walk must expose destructured assignment names after assignment")
gap_statements = function_text(checker, "register_block_grant_gaps")
if "body_assignment_bound_names(target, visible_names) if operator == TokenKind.Assign" not in gap_statements:
    raise SystemExit("the grant-gap walk must expose destructured assignment names after assignment")
collector_source = function_text(checker, "collect_effect_sources")
if not all(fragment in collector_source for fragment in (
    "body_statement_effect_facts(body, false, current_module, bound_names, table)",
    'source_refs.push("Abort.Panic") if body_facts.panic',
    "for effect_ref in body_facts.effect_refs",
    "table.function_effect_source_module <- table.function_effect_source_module.push(current_module)",
    "table.function_effect_source_ref <- table.function_effect_source_ref.push(source_ref)",
)):
    raise SystemExit("effect source collection must preserve panic priority and every forwarded effect ref")
facts_merge = function_text(checker, "body_effect_facts_merge")
if "for candidate in right.effect_refs" not in facts_merge or "not (any known in effect_refs where known == candidate)" not in facts_merge:
    raise SystemExit("effect source traversal must retain all refs while deduplicating repeated calls")
for helper in ("function_effect_refs", "function_first_effect_ref"):
    helper_source = function_text(effect_refs, helper)
    if "effect_name_has_multiple_module_owners(table, owner)" not in helper_source or \
            "function_effect_module" not in helper_source or "module_matches" not in helper_source:
        raise SystemExit(f"effect helper {helper} must filter declared rows by selected module for cross-module same-leaf functions")
declared_effects = function_text(symbols, "collect_range_with_variadics")
if "table.function_effect_module <- table.function_effect_module.push(table.current_module)" not in declared_effects:
    raise SystemExit("signature effect rows must preserve the declaring function's module")
if "function_effect_module: mutable darray[sview @source] = []" not in types:
    raise SystemExit("declared effect module identity must be stored in a parallel symbol-table array")
if "function_effect_module: [], extern_effect_modules:" not in source("src/semantic/semantic_types.elisa"):
    raise SystemExit("empty SymbolTable values must initialize the declared effect module side table")
install_effects = function_text(abstract_effects, "ae_collect_install_declarations")
add_install_effect = function_text(abstract_effects, "ae_add_function_effect")
if not all(fragment in install_effects for fragment in (
    "owner_module: sview",
    "ae_join_module_scope(owner_module, name, table)",
    "ae_collect_install_statements(name, owner_module, body",
)) or not all(fragment in add_install_effect for fragment in (
    "module: sview",
    "function_effect_module[row_index] == module",
    "function_effect_module <- table.function_effect_module.push(module)",
)):
    raise SystemExit("handler-install effect rows must retain their enclosing function module")
extern_add_ref = function_text(checker, "extern_effect_add_ref")
if not all(fragment in extern_add_ref for fragment in (
    "table.function_effect_module[row] == module",
    "table.function_effect_module <- table.function_effect_module.push(module)",
)):
    raise SystemExit("extern compatibility rows must dedupe by owner, module, and ref")
if not all(fragment in function_text(checker, helper) for helper in ("register_unsafe_can_grants", "extern_effect_add_ref") for fragment in (
    "function_effect_module <- table.function_effect_module.push(owner_module)" if helper == "register_unsafe_can_grants" else "function_effect_module <- table.function_effect_module.push(module)",
)):
    raise SystemExit("inferred unsafe and extern effect rows must retain module identity")
if "function_effect_refs(table, owner, module, module_known)" not in function_text(effect_refs, "function_has_effect"):
    raise SystemExit("function_has_effect must use module-filtered inferred rows when the call resolver supplies an owner")
for helper in ("function_declares_effect", "function_body_panics"):
    if "effect_name_has_multiple_module_owners(table, owner)" not in function_text(resolve_types, helper):
        raise SystemExit(f"legacy name-only helper {helper} must fail closed for duplicated module owners")
if not all(fragment in global_effect_sources for fragment in (
    "function_effect_source_module <- table.function_effect_source_module.push(module)",
    "gp_source_module_at(authority, read_slot)",
    "gp_source_module_at(authority, write_slot)",
)):
    raise SystemExit("Global source rows must retain the module of their exact GlobalAuthority function slot")
if "extern_regular_function_owner_is_unique(owner_module, owner, table)" not in function_text(checker, "register_unsafe_can_grants"):
    raise SystemExit("Unsafe can rows must retain caller module identity and fail closed for same-module overloads")
if not all(fragment in fixture for fragment in (
    "effect Writer[T]:",
    "module First:",
    "extern inspect() -> void can[Disk.Read]",
    "extern inspect_via() -> void can[Writer[sview] via Memory.Allocate]",
    "module Second:",
    "extern inspect() -> void can[Console.Write]",
    "extern inspect_via() -> void can[Writer[sview] via Console.Write]",
    "Second::inspect()",
    "Second::inspect() can Console.Write",
    "can Disk.Read:",
    "Second::inspect() can Disk.Read",
    "from Second import inspect",
    "Second::inspect_via()",
    "inspect()",
    "unresolved_bare_call",
    "imported_wrong_grant_call",
    "via_wrong_grant_call",
    "qualified_shadow_outside(inspect: fn() -> void)",
    "qualified_shadow_block(inspect: fn() -> void)",
    "imported_shadow_call(inspect: fn() -> void)",
    "call_imported_shadow()",
    "qualified_source_worker()",
    "qualified_source_caller()",
    "imported_source_worker()",
    "imported_source_caller()",
    "imported_return_source_worker()",
    "imported_return_source_caller()",
    "panic_callback_source(panic: fn() -> void)",
    "panic_callback_caller()",
    "imported_block_tail_shadow(callback: fn() -> void)",
    "call_imported_block_tail_shadow()",
    "inspect, callback_copy = callback, callback",
    "extern inspect_multi() -> void can[Memory.Allocate, Console.Write]",
    "multi_source_worker()",
    "multi_source_caller()",
    "shared_source_worker()",
    "shared_source_caller()",
    "shared_source_grant_caller()",
    "def shared_source_worker() -> void can[Disk.Read]:",
    "def shared_source_worker() -> void can[Console.Write]:",
    "module NestedFirst:",
    "module NestedSecond:",
    "module Child:",
    "NestedSecond::Child::nested_module_worker()",
    "nested_module_caller()",
    "Second::inspect()",
)):
    raise SystemExit("fixture must cover extern call ownership through enclosing source rows and local shadowing")
