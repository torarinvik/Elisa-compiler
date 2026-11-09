"""Check static if backend checks."""
from static_if_source_inspection import compact, direct_children, function_section, source_code


def require_selector_layout(*, SELECTOR) -> None:
    section = function_section(SELECTOR.read_text(), "selected_static_if_rows")
    section_code = source_code(section)
    body = compact(section_code)
    ordered_fragments = (
        "forrowin0..<file.static_if_lines.count|taken,satisfied_by_depth,file,structs|:",
        "branch_kind:StaticIfBranch::Kind=file.static_if_kinds[row]",
        "row_depth:usize=file.static_if_depths[row].usize()ifrow<file.static_if_depths.countelseStaticIfBranch::TOP_LEVEL_DEPTH.usize()",
        "whilesatisfied_by_depth.count<=row_depth|satisfied_by_depth|:",
        "satisfied_by_depth.push(false)",
        "starts_new_chain:bool=matchbranch_kind:StaticIfBranch::Kind.ChainHead:true_:false",
        "satisfied_by_depth[row_depth]<-falseifstarts_new_chain",
        "action:StaticIfPolicy::Action=StaticIfPolicy::row_action(branch_kind,satisfied_by_depth[row_depth])",
        "matchaction:",
        "condition_ok:mutablebool=row<file.static_if_conds.countandrow<file.static_if_modules.count",
        "condition_value:mutablei64=0",
        "ifcondition_ok:",
        "previous_owner:sview=structs.visibility.current_owner",
        "structs.visibility.current_owner<-file.static_if_modules[row]",
        "condition_value<-fold_const_expr(file.static_if_conds[row],structs,condition_ok)",
        "structs.visibility.current_owner<-previous_owner",
        "continueifnotStaticIfPolicy::condition_selects_branch(condition_ok,condition_value)",
    )
    positions = [body.find(fragment) for fragment in ordered_fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("static-if selector no longer resets each chain at its own depth before applying policy")
    if body.count("taken.push(row.u32())") != 2:
        raise SystemExit("fallback and true-condition arms must each append their selected row identity")
    if body.count("satisfied_by_depth[row_depth]<-true") != 2:
        raise SystemExit("both selected fallback and selected condition arms must satisfy only their depth")
    lines = section_code.splitlines()
    loop_index = next((index for index, line in enumerate(lines)
                       if "for row in 0..<file.static_if_lines.count" in line), None)
    if loop_index is None:
        raise SystemExit("static-if source-order row loop is missing")
    loop_indent = len(lines[loop_index]) - len(lines[loop_index].lstrip(" \t"))
    expected_loop_children = [
        "branch_kind: StaticIfBranch::Kind = file.static_if_kinds[row]",
        "row_depth: usize = file.static_if_depths[row].usize() if row < file.static_if_depths.count else StaticIfBranch::TOP_LEVEL_DEPTH.usize()",
        "while satisfied_by_depth.count <= row_depth |satisfied_by_depth|:",
        "starts_new_chain: bool = match branch_kind:",
        "satisfied_by_depth[row_depth] <- false if starts_new_chain",
        "action: StaticIfPolicy::Action = StaticIfPolicy::row_action(branch_kind, satisfied_by_depth[row_depth])",
        "match action:",
    ]
    if direct_children(lines, loop_index, loop_indent) != expected_loop_children:
        raise SystemExit("depth growth, chain reset, policy call, and action match must be direct row-loop steps")
    action_index = next((index for index, line in enumerate(lines)
                         if line.strip() == "match action:"), None)
    if action_index is None:
        raise SystemExit("static-if action match is missing")
    action_indent = len(lines[action_index]) - len(lines[action_index].lstrip(" \t"))
    expected_arms = [
        "StaticIfPolicy::Action.Skip:",
        "StaticIfPolicy::Action.SelectFallback:",
        "StaticIfPolicy::Action.EvaluateCondition:",
    ]
    if direct_children(lines, action_index, action_indent) != expected_arms:
        raise SystemExit("static-if action match must handle skip, fallback, and condition evaluation explicitly")
    arm_children = {}
    for arm in expected_arms:
        arm_index = next(index for index, line in enumerate(lines) if line.strip() == arm)
        arm_indent = len(lines[arm_index]) - len(lines[arm_index].lstrip(" \t"))
        arm_children[arm] = direct_children(lines, arm_index, arm_indent)
    if arm_children[expected_arms[0]] != ["continue"]:
        raise SystemExit("a previously satisfied static-if chain must continue to the next source row")
    if arm_children[expected_arms[1]] != [
        "taken.push(row.u32())",
        "satisfied_by_depth[row_depth] <- true",
    ]:
        raise SystemExit("fallback selection must append its own line and satisfy only its depth without folding")
    if arm_children[expected_arms[2]] != [
        "condition_ok: mutable bool = row < file.static_if_conds.count and row < file.static_if_modules.count",
        "condition_value: mutable i64 = 0",
        "if condition_ok:",
        "continue if not StaticIfPolicy::condition_selects_branch(condition_ok, condition_value)",
        "taken.push(row.u32())",
        "satisfied_by_depth[row_depth] <- true",
    ]:
        raise SystemExit("condition branches must decline missing metadata and update selection only after a row-module fold")
    fold_index = next((index for index, line in enumerate(lines)
                       if line.strip() == "if condition_ok:"), None)
    if fold_index is None:
        raise SystemExit("condition fold guard is missing")
    fold_indent = len(lines[fold_index]) - len(lines[fold_index].lstrip(" \t"))
    if direct_children(lines, fold_index, fold_indent) != [
        "previous_owner: sview = structs.visibility.current_owner",
        "structs.visibility.current_owner <- file.static_if_modules[row]",
        "condition_value <- fold_const_expr(file.static_if_conds[row], structs, condition_ok)",
        "structs.visibility.current_owner <- previous_owner",
    ]:
        raise SystemExit("static-if condition folding must restore the prior owner after using the row's lexical module")

def require_backend_position_identity(*, BACKEND_ID_FIXTURE, CODEGEN_DECL_HOISTING, CODEGEN_MODULE, CODEGEN_STMT, CODEGEN_TABLE, DRIVER_AST_DECL, DRIVER_UNSAFE, DRIVER_UNSAFE_SEGMENTS, FULL_PIPELINE, PARSER_DECL_IMPL, SELECTOR, STATIC_IF_CONDITION, STATIC_RUNTIME_SMOKE) -> None:
    selector = compact(SELECTOR.read_text())
    module = compact(function_section(CODEGEN_MODULE.read_text() + CODEGEN_MODULE.with_name("codegen_module_emit.elisa").read_text(), "select_module_declarations"))
    statement_backend = compact(CODEGEN_STMT.read_text())
    backend_annotations = compact(CODEGEN_TABLE.read_text() + CODEGEN_TABLE.with_name("codegen_enum_tables.elisa").read_text())
    unsafe = compact(DRIVER_UNSAFE.read_text())
    unsafe_segments = compact(DRIVER_UNSAFE_SEGMENTS.read_text())
    impl_registration = compact(function_section(CODEGEN_DECL_HOISTING.read_text(), "record_impl_member_lines"))
    impl_parser = compact(function_section(PARSER_DECL_IMPL.read_text(), "impl_declaration"))
    condition_check = compact(function_section(STATIC_IF_CONDITION.read_text(), "check_static_if_condition"))
    condition_owner_walk = compact(function_section(STATIC_IF_CONDITION.read_text(), "static_if_mark_statement_owners"))
    function_owner_walk = compact(function_section(STATIC_IF_CONDITION.read_text(), "static_if_collect_function_owners"))
    pipeline = compact(FULL_PIPELINE.read_text())
    ast_condition = compact(function_section(DRIVER_AST_DECL.read_text(), "emit_ast_static_condition"))
    selected_offsets = compact(function_section(SELECTOR.read_text(), "static_if_offsets_for_rows"))
    if not all(fragment in selected_offsets for fragment in (
            "forrowintaken_rows",
            "row.usize()>=file.static_if_offsets.count",
            "taken_offsets.push(file.static_if_offsets[row.usize()])")) or not all(fragment in selector for fragment in (
            "flatten_static_branches[@r](decls:darray[Decl]&,branch_offsets:darray[u32]&,taken_offsets:darray[u32]&",
            "static_branch_is_taken(branch_offsets,scoped_line.offset)",
            "static_branch_is_taken(taken_offsets,scoped_line.offset)",
            "taken_offset==offset",
            "flatten_static_branches(module_body,branch_offsets,taken_offsets,flattened_members)")):
        raise SystemExit("backend declaration flattening must select static branches by exact source offsets")
    if not all(fragment in module for fragment in (
            "static_branch_offsets:darray[u32]=file.static_if_offsets",
            "round_rows:darray[u32]=selected_static_if_rows(file,structs)",
            "round_taken_offsets:darray[u32]=static_if_offsets_for_rows(file,selected_rows)",
            "flatten_static_branches(file.top_decls,static_branch_offsets,round_taken_offsets,round_top)",
            "structs.annotations.static_branch_offsets<-file.static_if_offsets",
            "structs.annotations.static_taken_offsets<-structs.annotations.static_taken_offsets.push(file.static_if_offsets[selected_row.usize()])")) or not all(fragment in backend_annotations for fragment in (
            "static_branch_lines:mutabledarray[u32]=[]",
            "static_branch_offsets:mutabledarray[u32]=[]",
            "static_taken_lines:mutabledarray[u32]=[]",
            "static_taken_offsets:mutabledarray[u32]=[]")):
        raise SystemExit("backend annotations must preserve diagnostic lines while carrying exact branch and selection offsets")
    if not all(fragment in statement_backend for fragment in (
            "static_branch_is_taken(structs.annotations.static_branch_offsets,block_line.offset)",
            "static_branch_is_taken(structs.annotations.static_taken_offsets,block_line.offset)")):
        raise SystemExit("runtime statement codegen must use branch offsets to distinguish same-line static blocks")
    if not all(fragment in impl_registration for fragment in (
            "annotation.owner==\"__impl_scope\"",
            "annotation.owner==\"__impl_concrete\"",
            "annotation.owner==\"__ext_concrete\"",
            "annotation.line==scoped_line.line",
            "annotation.offset==scoped_line.offset")) or not all(fragment in impl_parser for fragment in (
            'owner:"__impl_scope"',
            'owner:"__impl_concrete"',
            'owner:"__ext_concrete"',
            "offset:head.start")):
        raise SystemExit("impl metadata must carry and match the exact scoped declaration position")
    if not all(fragment in unsafe for fragment in (
            "unsafe_static_offset_is_taken(taken_offsets:darray[u32]&,offset:u32)",
            "us_b_line.offset",
            "static_taken_offsets:darray[u32]&")) or \
            "Backend::selected_static_offsets_for_report(file)" not in unsafe_segments:
        raise SystemExit("unsafe reporting must select statement branches by source offset too")
    if not all(fragment in condition_owner_walk for fragment in (
            'kind=="static"',
            "file.static_if_lines[row]==position.line",
            "file.static_if_offsets[row]==position.offset",
            "row_owner_offsets[row]<-function_offset",
            "row_owner_found[row]<-true",
            "static_if_mark_statement_owners(body,function_offset,file,row_owner_offsets,row_owner_found)")) or not all(fragment in function_owner_walk for fragment in (
            "position.offset",
            "static_if_mark_statement_owners(body,position.offset,file,row_owner_offsets,row_owner_found)",
            "static_if_collect_function_owners(module_body,file,row_owner_offsets,row_owner_found,param_owner_offsets,param_names)",
            "static_if_collect_function_owners(scoped_body,file,row_owner_offsets,row_owner_found,param_owner_offsets,param_names)")) or not all(fragment in condition_check for fragment in (
            "static_if_offsets:darray[u32]&",
            "row>=static_if_offsets.count",
            "static_if_lines[row]",
            "notrow_owner_found[row]",
            "row_owner_offsets[row]")) or \
            "file.static_if_conds,file.static_if_lines,file.static_if_offsets,file.static_if_kinds" not in pipeline or not all(fragment in ast_condition for fragment in (
            "file.static_if_offsets[condition_index]==branch_pos.offset",
            "file.static_if_lines[condition_index]==branch_pos.line")):
        raise SystemExit("semantic validation and AST output must use static branch offsets while retaining logical lines for diagnostics")
    fixture = BACKEND_ID_FIXTURE.read_text()
    smoke = STATIC_RUNTIME_SMOKE.read_text()
    if not all(fragment in fixture for fragment in (
            "#line 40 first-head.elisa",
            "static if true:",
            "def active_first()",
            "#line 40 second-head.elisa",
            "static if false:",
            "def inactive_second()",
            "def active_second()")) or not all(fragment in smoke for fragment in (
            "static_if_same_line_heads.elisa",
            "@active_first",
            "@active_second",
            "@inactive_second")):
        raise SystemExit("backend regression must exercise distinct conditional heads that share a #line value")
