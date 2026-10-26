"""Typestate widening facts must belong to one exact extern in its module."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/semantic/check_typestate_call_widening.elisa").read_text()
FIXTURE = (ROOT / "test/repro/typestate_call_widening_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/typestate_call_widening_owner_line_zero_smoke.sh").read_text()
RUN_ALL = (ROOT / "test/parity/run_all.sh").read_text()
EXTERN_PARSER = (ROOT / "src/parser/parser_export_surface.elisa").read_text()


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


source = compact(SOURCE)
scan_start = SOURCE.index("def typestate_widen_scan(")
scan_end = SOURCE.index("def typestate_widen_statements(", scan_start)
scan = compact(SOURCE[scan_start:scan_end])
if "widening_param_indices[widening_index]==typestate_param_indexandwidening_positions[widening_index]==call_line" not in scan or \
        "ifnotalready_recorded:widening_param_indices.push(typestate_param_index)widening_positions.push(call_line)" not in scan or \
        "widening_positions:mutabledarray[Ast::Pos]=[]" not in source:
    raise SystemExit("one mutable argument cannot emit duplicate widening facts for the same parameter and callsite")
if "pc.line==extern_lineandpc.function_offset==extern_offset" not in source:
    raise SystemExit("extern postcondition lookup must match the exact declaration line and offset")
if "extern_lines.push(extern_line.line)" not in SOURCE or \
        "extern_offsets.push(extern_line.offset)" not in SOURCE:
    raise SystemExit("extern signature collection must preserve its declaration position")
if "extern_param_mutable_at(extern_index," not in SOURCE or \
        "extern_param_mutable_at(extern_names," in SOURCE:
    raise SystemExit("mutable parameter lookup must use the selected extern row, not the first matching name")
if "extern_modules[index] == resolved_module" not in SOURCE or \
        "function_modules[fn_index] == resolved_module" not in SOURCE or \
        "return extern_names.count if selected < extern_names.count" not in SOURCE:
    raise SystemExit("extern call ownership must use the resolved callee module and fail closed on multiple viable externs")
if "typestate_call_leaf(callee)" not in SOURCE or \
        "typestate_call_qualifier(callee, table)" not in SOURCE or \
        "callable_qualified_module_matches_candidate(annotations, symbol.module_owner, lexical_module, qualifier, name, table, call_position.offset)" not in SOURCE or \
        "callable_program_selective_import_row_visible(annotations, name, symbol.module_owner, lexical_module)" not in SOURCE or \
        "typestate_possible_import_may_select(name, lexical_module, possible_imports)" not in SOURCE or \
        "typestate_resolve_callable_owner(called, current_module, qualifier, call_line, file, table)" not in SOURCE or \
        "errorset_import_precedes_call(annotation, call_position.line, call_position.offset, call_offset_present)" not in SOURCE or \
        "typestate_import_annotations_before_call(table.protocol_annotations, call_position, file, table)" not in SOURCE or \
        "owners.count != 1.usize()" not in SOURCE or \
        "imported_owners.count != 1.usize()" not in SOURCE:
    raise SystemExit("qualified and selectively imported calls must resolve one owner at the call's source position or fail closed")
if "extern_call_shape_matches(index, argument_count, argument_names" not in SOURCE or \
        "function_call_shape_matches(fn_index, argument_count, argument_names" not in SOURCE or \
        "extern_owner_index_at(extern_names, extern_modules, extern_starts, extern_arities, extern_variadics, extern_params, function_names, function_modules, function_param_starts, function_arities, function_variadics, function_params, called, resolved_owner.owner, arguments.count, argument_names)" not in SOURCE or \
        "extern_lines[extern_index], extern_offsets[extern_index]" not in SOURCE:
    raise SystemExit("candidate selection must narrow by call shape and preserve the selected extern identity")
if "extern_call_parameter_position_at(extern_index, position, argument_names" not in SOURCE:
    raise SystemExit("named arguments must map to the selected extern's formal parameter before mutability lookup")

walk_start = SOURCE.index("def typestate_widen_walk(")
walk_end = SOURCE.index("def collect_typestate_structs(", walk_start)
function_walk = compact(SOURCE[walk_start:walk_end])
if "typestate_params:mutabledarray[Ast::ParamDecl]=[]" not in function_walk or \
        "typestate_params.push(parameter)ifstruct_name!=\"\"" not in function_walk or \
        "typestate_widen_statements(body,file,function_name,typestate_params," not in function_walk or \
        "typestate_widen_statements(body,function_name,parameter.name," in function_walk:
    raise SystemExit("each function body must be scanned once with its complete set of typestate parameters")
if compact(SOURCE).count("typestate_resolve_callable_owner(called,current_module,qualifier,call_line,file,table)") != 1 or \
        "anytypestate_paramintypestate_paramswheretypestate_param.name==argument_name" not in source:
    raise SystemExit("each call site must resolve its owner once and match arguments against the full typestate parameter set")
if source.count("continueifnottypestate_static_scope_may_be_active(file,scoped_line,current_module,table)") < 4:
    raise SystemExit("inactive static-if scopes must be excluded from struct, callable, extern, and body scans")
if "ifkind==\"static\":continueifnottypestate_static_scope_may_be_active(file,line,current_module,table)" not in source or \
        "pma_import_annotation_in_inactive_static_branch(annotation,table.protocol_annotations,file,table)" not in source or \
        "typestate_function_candidate_may_be_active(file,name,symbol,table)" not in source:
    raise SystemExit("inactive statement arms, imports, and function candidates must be filtered conservatively")
if 'parser <- parser.record_static_if_branch_rows("__function_static_branch", name, token) if has_params and name != ""' not in EXTERN_PARSER:
    raise SystemExit("callable extern symbols must carry the exact static-if ancestry used by owner lookup")

statement_start = SOURCE.index("def typestate_widen_statements(")
statement_end = SOURCE.index("def typestate_widen_walk(", statement_start)
statement_walk = compact(SOURCE[statement_start:statement_end])
if not all(fragment in statement_walk for fragment in (
        "Stmt.Assign(target,operator,value,line):table<-typestate_widen_scan(target,",
        "Stmt.If(condition,then_body,else_body,line):table<-typestate_widen_scan(condition,",
        "Stmt.While(condition,body,line):table<-typestate_widen_scan(condition,",
        "Stmt.For(bind,variables,iterable,body,line):table<-typestate_widen_scan(iterable,",
        "Stmt.Match(scrutinee,arms,line):table<-typestate_widen_scan(scrutinee,",
        "table<-typestate_widen_scan(arm.guard,",
        "table<-typestate_widen_statements(arm.body,",
        "Stmt.Contract(kind,expression,line):table<-typestate_widen_scan(expression,",
        "Stmt.Block(kind,clause,binding,body,line):ifkind==\"static\":continueifnottypestate_static_scope_may_be_active(file,line,current_module,table)",
)):
    raise SystemExit("statement walker must scan every direct expression position and nested match arm")

expression_start = SOURCE.index("def typestate_widen_scan(")
expression_end = SOURCE.index("def typestate_widen_statements(", expression_start)
expression_walk = compact(SOURCE[expression_start:expression_end])
if not all(fragment in expression_walk for fragment in (
        "table<-typestate_widen_scan(callee,",
        "Expr.Move(operand,line)|Expr.RegionNew(operand,region,line):table<-typestate_widen_scan(operand,",
        "Expr.Field(object,field,line)|Expr.Scope(object,field,line):table<-typestate_widen_scan(object,",
        "Expr.Index(object,index,line):table<-typestate_widen_scan(object,",
        "Expr.Slice(object,low,high,line):table<-typestate_widen_scan(object,",
        "Expr.IndexN(object,arguments,line):table<-typestate_widen_scan(object,",
        "Expr.StaticEffectCall(effect_type,operation,candidates,arguments,argument_names,line):",
        "Expr.If(condition,then_expression,else_expression,line):",
        "Expr.Match(scrutinee,arms,line)|Expr.Catch(scrutinee,arms,line):",
        "Expr.Comprehension(variable,iterable,condition,body,line,scope_id):",
        "Expr.GetElse(guarded,recovery,line):",
        "Expr.Block(block_statements,value,captures,line):",
        "Expr.Block(block_statements,value,captures,line):table<-typestate_widen_statements(block_statements,file,",
)):
    raise SystemExit("expression walker must recurse through effectful call receivers and expression children")

if FIXTURE.count("#line 0 typestate-call-widen-owner.elisa") != 11 or not all(
    fragment in FIXTURE
    for fragment in (
        "extern inspect(ticket: mutable Ticket[Fresh]&) -> void",
        "extern inspect(ticket: Ticket[Fresh]&) -> void",
        "inspect(ticket)",
        "def inspect(ticket: mutable Ticket[Fresh]&) -> void ensures ticket => Fresh:",
        "def inspect(code: i64, enabled: bool) -> void:",
        "extern inspect(ticket: mutable Ticket[Fresh]&) -> i64",
        "extern inspect(ticket: mutable Ticket[Fresh]&) -> bool",
        "extern inspect(ticket: mutable Ticket[Fresh]&, other: i64) -> void",
        "extern inspect(arg: i64, other: i64) -> void",
        "inspect(other: 0, ticket: ticket)",
        "module MutableProvider:",
        "module ConstProvider:",
        "module ContractProvider:",
        "module ArityProvider:",
        "module AmbiguousProvider:",
        "module LabelProvider:",
        "module QualifiedCaller:",
        "MutableProvider::inspect(ticket)",
        "from MutableProvider import inspect",
        "def call_before_import(ticket: mutable Ticket[Fresh]&) -> void:",
        "def call_before_alias(ticket: mutable Ticket[Fresh]&) -> void:",
        "FutureProvider::inspect(ticket)",
        "using MutableProvider as FutureProvider",
        "static if false:\n    from ConstProvider import inspect",
        "def call_imported(ticket: mutable Ticket[Fresh]&) -> void:",
        "module StatementPositions:",
        "if if_predicate(ticket):",
        "while while_predicate(ticket):",
        "for value in loop_values(ticket):",
        "match match_subject(ticket):",
        "selected if match_guard(ticket):",
        "match_body(ticket)",
        "extern make_decision(ticket: mutable Ticket[Fresh]&) -> Decision",
        "extern inspect_pair(first: mutable Ticket[Fresh]&, second: mutable Ticket[Fresh]&) -> void",
        "def call_two(first: mutable Ticket[Fresh]&, second: mutable Ticket[Fresh]&) -> void:",
        "def call_twice(ticket: mutable Ticket[Fresh]&) -> void:",
        "inspect(ticket)\n        inspect(ticket)",
        "inspect_pair(first, second)",
        "static if false:\n        def inspect_pair(first: mutable Ticket[Fresh]&, second: mutable Ticket[Fresh]&) -> void:",
        "extern inspect_alone(ticket: mutable Ticket[Fresh]&) -> void",
        "static if false:\n        extern inspect_alone(ticket: mutable Ticket[Fresh]&) -> void",
        "def call_inactive_extern(ticket: mutable Ticket[Fresh]&) -> void:",
        "if make_decision(ticket).accepted:",
        "def call_field_receiver(ticket: mutable Ticket[Fresh]&) -> void:",
        "_ = move make_decision(ticket)",
        "new[scratch] make_decision(ticket)",
        "def call_move_operand(ticket: mutable Ticket[Fresh]&) -> void:",
        "def call_region_operand(ticket: mutable Ticket[Fresh]&) -> void:",
        "def call_inactive_static_block(ticket: mutable Ticket[Fresh]&) -> void:",
        "static if false:\n            make_decision(ticket)",
        "def call_active_static_block(ticket: mutable Ticket[Fresh]&) -> void:",
        "static if true:\n            make_decision(ticket)",
        "inspect(ticket)",
    )
):
    raise SystemExit("same-line regression must distinguish extern mutability, a different-arity def, and an ambiguous shape")
if not FIXTURE.index("def call_before_import") < FIXTURE.index("from MutableProvider import inspect") < FIXTURE.index("def call_imported"):
    raise SystemExit("a selective import must not be visible to a call that appears before its source row")
if not FIXTURE.index("def call_before_alias") < FIXTURE.index("using MutableProvider as FutureProvider"):
    raise SystemExit("a module alias written after a qualified call must not retroactively select its target")
if "typestate_call_widening_owner_line_zero.elisa" not in SMOKE or \
        "check_typestate_call_widening_owner_identity.py" not in SMOKE or \
        'before "call_mutable" returns' not in SMOKE or \
        'before "call_const" returns' not in SMOKE or \
        'before "call_arity" returns' not in SMOKE or \
        'before "call_ambiguous" returns' not in SMOKE or \
        'before "call_label" returns' not in SMOKE or \
        'before "call_qualified" returns' not in SMOKE or \
        'before "call_imported" returns' not in SMOKE or \
        'before "call_before_import" returns' not in SMOKE or \
        'before "call_before_alias" returns' not in SMOKE or \
        'before "call_if_condition" returns' not in SMOKE or \
        'before "call_while_condition" returns' not in SMOKE or \
        'before "call_for_iterable" returns' not in SMOKE or \
        'before "call_match_scrutinee" returns' not in SMOKE or \
        'before "call_match_guard" returns' not in SMOKE or \
        'before "call_match_body" returns' not in SMOKE or \
        'before "call_field_receiver" returns' not in SMOKE or \
        'before "call_move_operand" returns' not in SMOKE or \
        'before "call_region_operand" returns' not in SMOKE or \
        "call_offset_present" not in SOURCE or \
        "alias.offset >= before_offset" not in Path(ROOT / "src/semantic/check_try_fallible/callable_rows.elisa").read_text() or \
        "semantic_possible_import_alias_head_target(alias_head, enclosing_module, before_offset, table)" not in Path(ROOT / "src/semantic/check_try_fallible/callable_rows.elisa").read_text():
    raise SystemExit("smoke must cover local, qualified, imported, arity, and ambiguous-shape owner selection")

if 'for smoke in "$REPO_ROOT"/test/parity/*_smoke.sh' not in RUN_ALL or \
        "typestate_call_widening_owner_line_zero_smoke.sh" in RUN_ALL:
    raise SystemExit("the typestate widening smoke must be picked up by run_all's parity-smoke glob")

print("typestate call-widening owner source checks passed")
