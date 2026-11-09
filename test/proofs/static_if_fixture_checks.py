"""Check static if fixture checks."""
from static_if_source_inspection import compact, direct_children, function_section, source_code


def require_static_runtime_block_identity(*, STATIC_RUNTIME, STATIC_RUNTIME_FIXTURE, STATIC_RUNTIME_IMPORT_FIXTURE, STATIC_RUNTIME_INACTIVE_FIXTURE, STATIC_RUNTIME_NESTED_FIXTURE, STATIC_RUNTIME_SIBLING_FIXTURE, STATIC_RUNTIME_SMOKE) -> None:
    source = STATIC_RUNTIME.read_text()
    classifier = compact(function_section(source, "srs_static_if_branch_selection"))
    static_function = compact(function_section(source, "srs_static_function_at"))
    collector = compact(function_section(source, "srs_collect_functions"))
    function_kind = compact(function_section(source, "srs_function_kind"))
    candidate_visibility = compact(function_section(source, "srs_function_candidate_visibility"))
    static_walker = compact(function_section(source, "srs_walk_static"))
    walker = compact(function_section(source, "srs_walk"))
    checker = compact(function_section(source, "srs_check_declarations"))
    entrypoint = compact(function_section(source, "check_static_runtime_stmt"))
    if not all(fragment in classifier for fragment in (
            "position:Ast::Pos",
            "static_if_lines[row]==position.line",
            "file.static_if_offsets[row]==position.offset",
            "pma_static_if_row_selection(file,branch_row,current_module,table)")) or \
            not all(fragment in static_function for fragment in (
            'annotation.owner=="__static_fn"',
            "annotation.module==current_module",
            "annotation.line==position.line",
            "annotation.offset==position.offset")) or \
            not all(fragment in collector for fragment in (
            "srs_static_function_at(static_markers,current_module,function_name,position)",
            "modules<-modules.push(current_module)",
            "srs_static_if_branch_selection(file,scoped_position,current_module,table)",
            "continueifbranch.foundandbranch.knownandnotbranch.active")) or \
            not all(fragment in function_kind for fragment in (
            "srs_module_contains(current_module,modules[row])",
            "lexical_staticandlexical_runtime",
            "candidate.lexical",
            "imported_uncertain")) or \
            not all(fragment in candidate_visibility for fragment in (
            "sgi_function_visible(file,file.enum_annotations,table,symbol,current_module)",
            "pma_static_if_function_branch_selection(file,name,symbol,table,0)",
            "return(true,visibility.known,visibility.visible,visibility.lexical,branch.known,branch.active)")) or \
            not all(fragment in static_walker for fragment in (
            "srs_static_if_branch_selection(file,position,current_module,table)",
            "notbranch.knownorbranch.active",
            "srs_walk(body,file,current_module,names,modules,lines,offsets,is_static,table)")) or \
            not all(fragment in walker for fragment in (
            "srs_static_if_branch_selection(file,position,current_module,table)",
            "notbranch.knownorbranch.active",
            "srs_walk_static(body,file,current_module,names,modules,lines,offsets,is_static,table)")) or \
            "continueifbranch.foundandbranch.knownandnotbranch.active" not in checker or \
            "srs_collect_functions(file.top_decls,\"\",file,static_markers,table,function_names,function_modules,function_lines,function_offsets,function_is_static)" not in entrypoint:
        raise SystemExit("static-runtime analysis must use lexical function identity and prune proven-inactive nested static-if arms")
    fixture = STATIC_RUNTIME_FIXTURE.read_text()
    nested_fixture = STATIC_RUNTIME_NESTED_FIXTURE.read_text()
    inactive_fixture = STATIC_RUNTIME_INACTIVE_FIXTURE.read_text()
    sibling_fixture = STATIC_RUNTIME_SIBLING_FIXTURE.read_text()
    import_fixture = STATIC_RUNTIME_IMPORT_FIXTURE.read_text()
    smoke = STATIC_RUNTIME_SMOKE.read_text()
    if not all(fragment in fixture for fragment in (
            "#line 80 bare-static.elisa",
            "static:",
            "hook()",
            "#line 80 conditional-static-if.elisa",
            "static if true:")) or not all(fragment in nested_fixture for fragment in (
            "def hook() -> void:",
            "static:",
            "static if false:",
            "hook()")) or not all(fragment in smoke for fragment in (
            "static_if_inside_bare_static_runtime.elisa",
            "static_if_inactive_nested_bare_static.elisa",
            "static_runtime_sibling_static_name.elisa",
            "static_block_imported_runtime_call.elisa",
            "static_block_runtime_call_line_reset_rejected.elisa",
            "sibling-module runtime function",
            "proven-inactive static-if branch",
            "same #line value",
            "unrelated static-if head at the same #line value")):
        raise SystemExit("static-runtime regression must cover a bare block sharing a logical line with a later conditional head")
    if not all(fragment in inactive_fixture for fragment in (
            "static:",
            "static if false:",
            "static:",
            "hook()")) or not all(fragment in sibling_fixture for fragment in (
            "module Compile:",
            "static def emit()",
            "module Runtime:",
            "def emit()",
            "static:",
            "emit()")) or not all(fragment in import_fixture for fragment in (
            "module Provider:",
            "def via_wildcard()",
            "def via_selective()",
            "using Provider",
            "from Provider import via_selective",
            "via_wildcard()",
            "via_selective()")):
        raise SystemExit("static-runtime regression must cover inactive nested bare-static calls and sibling module name collisions")

def require_static_function_filter_identity(*, CODEGEN_MODULE, PARSER_DECL, STATIC_FN_FILTER_FIXTURE, STATIC_FN_FILTER_SMOKE) -> None:
    parser = compact(function_section(PARSER_DECL.read_text(), "parse_static"))
    backend_source = compact(CODEGEN_MODULE.read_text() + CODEGEN_MODULE.with_name("codegen_module_emit.elisa").read_text())
    declaration_match = compact(function_section(CODEGEN_MODULE.read_text() + CODEGEN_MODULE.with_name("codegen_module_emit.elisa").read_text(), "declaration_is_static_function"))
    recursive_filter = compact(function_section(CODEGEN_MODULE.read_text() + CODEGEN_MODULE.with_name("codegen_module_emit.elisa").read_text(), "declaration_without_static_functions"))
    if not all(fragment in parser for fragment in (
            'owner:"__static_fn"',
            "line:static_fn_pos.line",
            "offset:static_fn_pos.offset",
            "module:parser.current_module")):
        raise SystemExit("static-function parser rows must retain module and exact declaration position")
    if not all(fragment in declaration_match for fragment in (
            'annotation.owner=="__static_fn"',
            "annotation.name==function_name",
            "annotation.line==position.line",
            "annotation.offset==position.offset")):
        raise SystemExit("backend static-function filtering must match source declaration identity")
    if not all(fragment in recursive_filter for fragment in (
            "Decl.Module(module_name,module_body,module_pos)",
            "Decl.Scoped(scoped_body,scoped_pos)",
            "declaration_is_static_function(annotations,nested)",
            "declaration_without_static_functions(annotations,nested)")) or \
            "declaration_without_static_functions(static_fn_rows,kept_declaration)" not in backend_source:
        raise SystemExit("backend must recursively strip static functions from nested modules and impl scopes")
    fixture = STATIC_FN_FILTER_FIXTURE.read_text()
    smoke = STATIC_FN_FILTER_SMOKE.read_text()
    if not all(fragment in fixture for fragment in (
            "#line 70 static-helper.elisa",
            "module Outer:",
            "module Inner:",
            "static def helper()",
            "#line 70 runtime-helper.elisa",
            "module Kept:",
            "def helper()",
            "impl Value:",
            "static def compile_only_impl()")) or not all(fragment in smoke for fragment in (
            "static_function_nested_offset_filter.elisa",
            "grep -Ec '^[[:space:]]*define .*helper'",
            "compile_only_impl")):
        raise SystemExit("static-function regression must cover nested modules, impl scopes, and repeated #line identity")

def require_static_call_context_identity(*, LEXICAL_MODULE_FIXTURE, LEXICAL_MODULE_SMOKE, STATIC_CALL_CONTEXT, STATIC_CALL_CONTEXT_FIXTURE, STATIC_CALL_CONTEXT_SMOKE, TRY_FALLIBLE) -> None:
    source = STATIC_CALL_CONTEXT.read_text()
    declaration_match = compact(function_section(source, "is_static_function_declaration"))
    visible_match = compact(function_section(source, "is_visible_static_function"))
    branch_selection = compact(function_section(source, "static_call_function_branch_selection"))
    nearest_runtime = compact(function_section(source, "static_call_nearer_runtime_function_shadows"))
    inactive_scope = compact(function_section(source, "static_call_scope_is_inactive"))
    expression_walker = compact(function_section(source, "static_call_check_expression"))
    statement_walker = compact(function_section(source, "static_call_check_statements"))
    walker = compact(function_section(source, "check_static_call_context_walk"))
    entrypoint = compact(function_section(source, "check_static_call_context"))
    module_ancestor = compact(function_section(TRY_FALLIBLE.with_name("check_try_error_family.elisa").read_text(), "try_noncall_module_is_ancestor"))
    if not all(fragment in declaration_match for fragment in (
            'annotation.owner!="__static_fn"',
            "annotation.name==function_name",
            "annotation.line==function_position.line",
            "annotation.offset==function_position.offset",
            "annotation.module==current_module")):
        raise SystemExit("static-call body suppression must match the exact static declaration identity")
    if not all(fragment in visible_match for fragment in (
            'annotation.owner!="__static_fn"',
            "annotation.name!=function_name",
            "try_noncall_module_is_ancestor(annotation.module,current_module)",
            "static_call_nearer_runtime_function_shadows(file,annotation.module,current_module,function_name,table)",
            "static_call_function_branch_selection(annotation,file,table)",
            "returntrueifnotbranch.knownorbranch.active")):
        raise SystemExit("bare static calls must respect lexical visibility and exclude only statics proven inactive")
    if not all(fragment in branch_selection for fragment in (
            "symbol_chain_head(table,annotation.name)",
            "symbol.module_owner==annotation.module",
            "symbol.line==annotation.line",
            "symbol.offset==annotation.offset",
            "pma_static_if_function_branch_selection(file,annotation.name,symbol,table,0)")):
        raise SystemExit("static-call branch activity must bind the exact function symbol before filtering candidates")
    if not all(fragment in nearest_runtime for fragment in (
            "symbol.module_owner!=static_moduleandnottry_noncall_module_is_ancestor(static_module,symbol.module_owner)",
            "try_noncall_module_is_ancestor(static_module,symbol.module_owner)",
            "try_noncall_module_is_ancestor(symbol.module_owner,current_module)",
            'annotation.owner=="__static_fn"',
            "pma_static_if_function_branch_selection(file,function_name,symbol,table,0)",
            "returntrueifnotbranch.knownorbranch.active")):
        raise SystemExit("a nearer runtime declaration not proven inactive must shadow an ancestor static function")
    if not all(fragment in inactive_scope for fragment in (
            "pma_static_if_row_for_position(file,scope_position)",
            "pma_static_if_row_selection(file,branch_row,current_module,table)",
            "branch.knownandnotbranch.selected")):
        raise SystemExit("static-call walking must skip only scopes proven to be inactive static-if arms")
    if not all(fragment in expression_walker for fragment in (
            "defstatic_call_check_expression(file:Ast::File&",
            "Expr.Call(callee,arguments,argument_names,line)",
            "static_call_check_expression(file,callee",
            "static_call_check_expression(file,argument",
            "static_call_check_expression(file,left",
            "static_call_check_expression(file,right",
            "operator!=TokenKind.Isandoperator!=TokenKind.As",
            "Expr.StaticEffectCall(effect_type,operation,candidates,arguments,argument_names,pos)",
            "forcaptureincandidate.captures",
            "Expr.Field(object,field,pos)",
            "Expr.Scope(base,name,pos)",
            "Expr.Index(object,index,pos)",
            "Expr.Slice(object,low,high,pos)",
            "Expr.IndexN(object,arguments,pos)",
            "Expr.Move(operand,pos)",
            "Expr.RegionNew(operand,region,pos)",
            "Expr.Paren(inner,line)",
            "Expr.Array(elements,pos)|Expr.Tuple(elements,pos)|Expr.SetLit(elements,pos)",
            "Expr.DictLit(entries,pos)",
            "Expr.Construct(type_expression,fields,pos)",
            "Expr.RecordUpdate(base,fields,pos)",
            "Expr.If(condition,then_expr,else_expr,pos)",
            "Expr.Match(scrutinee,arms,pos)|Expr.Catch(scrutinee,arms,pos)",
            "Expr.Comprehension(variable,iterable,condition,body,pos,_)",
            "Expr.Refinement(base,predicate,pos)",
            "Expr.GetElse(guarded,recovery,pos)",
            "Expr.Lambda(parameters,body,pos)",
            "Expr.Block(statements,value,captures,pos)")) or not all(fragment in statement_walker for fragment in (
            "defstatic_call_check_statements(file:Ast::File&",
            "static_call_check_expression(file,expression",
            "Stmt.If(condition,then_body,else_body,line)",
            "Stmt.While(condition,while_body,line)",
            "Stmt.Assign(target,operator,value,line)",
            "static_call_check_expression(file,target",
            "Stmt.For(bind,variables,iterable,for_body,line)",
            "static_call_check_expression(file,iterable",
            "Stmt.Match(scrutinee,arms,line)",
            "Stmt.Contract(kind,expression,line)",
            'kind=="requires"orkind=="require"orkind=="assert"orkind=="ensure"orkind=="ensures"',
            "Stmt.Block(kind,clause,binding,body,line)",
            'kind=="static"',
            "static_call_check_statements(file,then_body",
            "static_call_check_statements(file,else_body")):
        raise SystemExit("static-call checking must recurse through runtime expression and statement children")
    if any(fragment in expression_walker for fragment in (
            "static_call_check_expression(file,type_expression",
            "static_call_check_expression(file,effect_type")) or "static_call_check_expression(file,type_expression" in statement_walker:
        raise SystemExit("static-call traversal must not treat declaration and constructor type expressions as runtime code")
    if not all(fragment in module_ancestor for fragment in (
            'returntrueifancestor==""orancestor==module_path',
            "module_path[0:ancestor.len]!=ancestor",
            "module_path[ancestor.len]==58andmodule_path[ancestor.len+1.usize()]==58")):
        raise SystemExit("static-call visibility must reject sibling module paths while allowing lexical ancestors")
    if not all(fragment in walker for fragment in (
            "Decl.Module(module_name,module_body,module_line)",
            "nested_module:sview@source=module_name",
            "Decl.Scoped(scoped_body,scoped_line)",
            "forparameterinparameters|table|->table",
            "parameter.has_default",
            "parameter.default_value",
            "static_call_check_expression(file,parameter.default_value,static_fns,current_module,table)",
            "member.has_default",
            "member.default_value",
            "static_call_check_expression(file,member.default_value,static_fns,current_module,table)",
            "Decl.Struct(struct_name,members,affinity,has_named_states,has_derive,invariants,struct_position)",
            "check_static_call_context_walk(file,module_body,static_fns,nested_module,table)",
            "check_static_call_context_walk(file,scoped_body,static_fns,current_module,table)",
            "static_call_scope_is_inactive(file,scoped_line,current_module,table)",
            "static_call_check_statements(file,body,static_fns,current_module,table)",
            "is_static_function_declaration(static_fns,function_name,function_position,current_module)")) or \
            'static_fns.push(annotation)ifannotation.owner=="__static_fn"' not in entrypoint or \
            "check_static_call_context_walk(file,file.top_decls,static_fns,\"\",table)" not in entrypoint:
        raise SystemExit("static-call walker must carry lexical module identity through modules and scoped declarations")
    fixture = STATIC_CALL_CONTEXT_FIXTURE.read_text()
    smoke = STATIC_CALL_CONTEXT_SMOKE.read_text()
    if not all(fragment in fixture for fragment in (
            "module Compile:",
            "static def parse()",
            "module Runtime:",
            "static def helper()",
            "def parse()",
            "return helper()",
            "def caller()",
            "return parse()",
            "module Outer:",
            "static def ancestor_helper()",
            "module Inner:",
            "return ancestor_helper()",
            "static def shadowed_helper()",
            "module RuntimeShadow:",
            "def shadowed_helper()",
            "return shadowed_helper()",
            "module NestedCalls:",
            "static def hidden()",
            "def comprehension()",
            "return [hidden() for item in 0..<1]",
            "def matched()",
            "return match 0:",
            "def loop_iterable()",
            "for item in [hidden()]:",
            "def indexed()",
            "return [1][hidden().usize()]",
            "def constructed()",
            "return Box{value: hidden()}",
            "value: i64 = hidden()",
            "def with_default(value: i64 = hidden())",
            "return with_default()",
            "def asserted()",
            "assert hidden() == 9",
            "return Box{}",
            "module BranchSelection:",
            "static if false:",
            "static def branch_pick()",
            "static else:",
            "def branch_pick()",
            "static if true:",
            "def selected_runtime_caller()",
            "branch_static()",
            "def bare_static_compile_time_caller()",
            "static:",
            "return branch_pick()",
            "module UnknownRuntimeShadow:",
            "static def compile_only()",
            "static def late_bound()",
            "static if ELISA_TARGET_OS_WASI:",
            "def late_bound()",
            "return late_bound() + compile_only()",
            "module MixedOverloads:",
            "static def choose(value: i64)",
            "def choose(value: f64)",
            "return choose(1.5)")) or not all(fragment in smoke for fragment in (
            "static_call_context_module_identity.elisa",
            'static function "helper" can only be called from a static context',
            'static function "hidden" can only be called from a static context',
            '[[ "$hidden_count" -eq 8 ]]',
            'static function "parse" can only be called from a static context',
            'static function "ancestor_helper" can only be called from a static context',
            'static function "branch_pick" can only be called from a static context',
            'branch_static_count="$(grep -Fc',
            '[[ "$branch_static_count" -eq 1 ]]',
            'unknown_branch_static_count="$(grep -Fc',
            '[[ "$unknown_branch_static_count" -eq 1 ]]',
            'static function "shadowed_helper" can only be called from a static context',
            'ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown',
            'static function "compile_only" can only be called from a static context',
            'static function "late_bound" can only be called from a static context',
            'static function "choose" can only be called from a static context')):
        raise SystemExit("static-call regression must cover exact declaration, module, and active branch identity")
    static_block = compact(function_section(source, "static_call_check_statements"))
    if not all(fragment in static_block for fragment in (
            "branch_row:usize=pma_static_if_row_for_position(file,line)",
            "ifbranch_row<file.static_if_lines.count:",
            "table<-static_call_check_statements(file,body,static_fns,current_module,table)ifnotstatic_call_scope_is_inactive(file,line,current_module,table)")):
        raise SystemExit("static-call statement walk must inspect mapped static-if arms unless proven inactive, while leaving bare static blocks compile-time-only")
    selected_runtime = compact(function_section(fixture, "selected_runtime_caller"))
    bare_static = compact(function_section(fixture, "bare_static_compile_time_caller"))
    if not all(fragment in selected_runtime for fragment in (
            "staticiftrue:", "staticelse:", "branch_static()")) or selected_runtime.count("branch_static()") != 2 or not all(fragment in bare_static for fragment in (
            "static:", "branch_static()")):
        raise SystemExit("static-call regression must pair a selected and inactive static-if statement call with a bare-static compile-time control")
    lexical_fixture = LEXICAL_MODULE_FIXTURE.read_text()
    lexical_smoke = LEXICAL_MODULE_SMOKE.read_text()
    if not all(fragment in lexical_fixture for fragment in (
            "module Outer:",
            "const FEATURE: bool = true",
            "static if FEATURE:",
            "module Inner:",
            "const FEATURE: bool = false",
            "static def compile_time_helper()",
            "return compile_time_helper()")) or not all(fragment in lexical_smoke for fragment in (
            "static_if_condition_lexical_module.elisa",
            'static function "compile_time_helper" can only be called from a static context')):
        raise SystemExit("static-if module-provenance regression must distinguish Outer::FEATURE from Outer::Inner::FEATURE")
