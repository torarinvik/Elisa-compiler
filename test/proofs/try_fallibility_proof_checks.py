"""Check catchability walks and try proof fixtures."""
import re


def check_try_fallibility_proofs(
    NEGATIVE,
    NEGATIVE_NAMES,
    POSITIVE,
    POSITIVE_NAMES,
    compact_inline,
    contains_contiguous_block,
    declarations,
    function_section,
    negative_text,
    normalize_code_line,
    pipeline_text,
    positive_text,
    semantic_text,
    source_text,
    strip_line_comment,
):
    may_raise_source = function_section(source_text, "try_noncall_expression_may_raise_catchably_with_annotations")
    call_argument_scan = """
Expr.Call(callee, arguments, _, _):
    direct_raise: bool = callee is Expr.Ident("raise", _)
    if not direct_raise:
        return true if try_noncall_expression_may_raise_catchably_with_annotations(callee, annotations, lexical_module)
        return false if try_noncall_expression_aborts_with_annotations(callee, annotations, lexical_module)
    for argument in arguments:
        return true if try_noncall_expression_may_raise_catchably_with_annotations(argument, annotations, lexical_module)
        return false if try_noncall_expression_aborts_with_annotations(argument, annotations, lexical_module)
"""
    if not contains_contiguous_block(may_raise_source, call_argument_scan):
        raise SystemExit("Try call catchability must scan ordinary arguments in evaluation order before callable metadata")

    main_try_check = function_section(source_text, "check_try_fallible")
    static_binding_selection = compact_inline(function_section(source_text, "try_static_binding_branch_selection"))
    static_binding_filter = compact_inline(function_section(source_text, "try_static_binding_filtered_annotations"))
    if not all(fragment in static_binding_selection for fragment in (
            'marker.owner != "__static_if_branch"',
            'marker.detail_name != marker_detail',
            "pma_static_if_row_selection(file, marker.identity_id.usize(), annotation.module, table)",
            "return (true, true, false) if branch.known and not branch.selected",
            "return (true, false, false) if unresolved")) or not all(fragment in static_binding_filter for fragment in (
            "try_static_binding_branch_selection(annotation, file.enum_annotations, file, table)",
            "if branch.tracked and branch.known and not branch.active:",
            'owner: "__try_unresolved_static_binding"',
            'name: "__using_alias"')):
        raise SystemExit("Try must filter proven-inactive import/alias rows and retain unresolved bindings as conservative sentinels")
    unresolved_static_binding = compact_inline(function_section(source_text, "callable_try_static_binding_uncertain"))
    if not all(fragment in unresolved_static_binding for fragment in (
            'unresolved.owner != "__try_unresolved_static_binding"',
            'unresolved.name == "__from_member"',
            'unresolved.name == "__binding_wildcard_import"',
            'unresolved.name == "__using_alias"')):
        raise SystemExit("Try callable resolution must decline a family when an unresolved static binding could affect the call")
    rows_call = "table <- check_try_fallible_rows(file, file.top_decls, try_annotations, projection.try_named_arguments, projection.try_argument_positions, projection.error_set_annotations, projection.error_set_family_paths, module_index, projection.module_annotations, projection.try_qualifiers, projection.try_arities, error_index, try_site_count, table) can Global{Read,Write} if try_site_count > 0"
    if compact_inline(main_try_check).count(compact_inline(rows_call)) != 1:
        raise SystemExit("check_try_fallible must invoke the source-row checker when at least one try site exists")
    if 'try_annotations: darray[Ast::EnumAnnotation] = try_static_binding_filtered_annotations(file, table)' not in compact_inline(main_try_check):
        raise SystemExit("check_try_fallible must derive its callable imports from the static-branch-filtered annotation set")

    if semantic_text.count('include "./check_try_fallible.elisa"') != 1:
        raise SystemExit("semantic module no longer includes the try-fallibility checker exactly once")
    pipeline_function = function_section(pipeline_text, "check_full_into_pipeline")
    pipeline_steps = [
        normalize_code_line(line)
        for line in pipeline_function.splitlines()
        if strip_line_comment(line).strip()
    ]
    pipeline_call = normalize_code_line("table <- check_try_fallible(loop_view, table) can Global{Read,Write}")
    pipeline_timer = normalize_code_line('PhaseTimer::minor("sem:check_try_fallible") can Global{Read,Write}')
    if not any(pipeline_steps[index:index + 2] == [pipeline_call, pipeline_timer]
               for index in range(len(pipeline_steps) - 1)):
        raise SystemExit("semantic pipeline no longer invokes and times check_try_fallible")

    if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
        raise SystemExit("try enclosing-function proof inventory is incomplete or contains extras")
    if 'include "./try_enclosing_function_index.elisa"' not in negative_text:
        raise SystemExit("negative controls no longer include the positive predecessor proof")

    positive_shapes = {
        "try_predecessor_is_last": (
            "offsets[index] != TRY_ENCLOSING_NO_OFFSET and offsets[index] <= query",
            "forall later in index + TRY_ENCLOSING_POSITION_STEP..<offsets.count",
            "forall candidate in TRY_ENCLOSING_FIRST_POSITION..<offsets.count",
        ),
        "try_linear_predecessor": (
            "if offsets[index] != TRY_ENCLOSING_NO_OFFSET and offsets[index] <= query:",
            "selected <- index",
            "invariant found implies (",
            "invariant found or (",
            "forall prior in TRY_ENCLOSING_FIRST_POSITION..<index",
            "offsets[prior] == TRY_ENCLOSING_NO_OFFSET or offsets[prior] > query",
            "return (found, selected)",
        ),
        "try_binary_predecessor": (
            "requires try_offsets_are_valid(offsets)",
            "requires try_offsets_are_nondecreasing(offsets)",
            "invariant forall prior in TRY_ENCLOSING_FIRST_POSITION..<low: offsets[prior] <= query",
            "invariant forall later in high..<offsets.count: offsets[later] > query",
            "if offsets[middle] <= query:",
            "low <- middle + TRY_ENCLOSING_POSITION_STEP",
            "high <- middle",
            "return (true, low - TRY_ENCLOSING_POSITION_STEP)",
            "return (false, TRY_ENCLOSING_FIRST_POSITION)",
        ),
        "last_predecessor_results_are_unique": (
            "requires try_predecessor_is_last(offsets, query, left_found, left_index)",
            "requires try_predecessor_is_last(offsets, query, right_found, right_index)",
            "ensure left_found == right_found and left_index == right_index",
            "left_found == right_found and left_index == right_index",
        ),
        "sorted_binary_predecessor_equals_linear_reference": (
            "ensure try_binary_predecessor(offsets, query) == try_linear_predecessor(offsets, query)",
            "linear: (found: bool, index: usize) = try_linear_predecessor(offsets, query)",
            "indexed: (found: bool, index: usize) = try_binary_predecessor(offsets, query)",
            "return last_predecessor_results_are_unique(offsets, query, linear.found, linear.index, indexed.found, indexed.index)",
        ),
        "duplicate_offsets_select_the_last_qualifying_position": (
            "indexed.index == TRY_ENCLOSING_SECOND_POSITION",
        ),
        "zero_offset_is_a_real_position": (
            "offsets: darray[u32] = [0, TRY_ENCLOSING_DUPLICATE_OFFSET]",
            "try_binary_predecessor(offsets, 0)",
            "indexed.found and indexed.index == TRY_ENCLOSING_FIRST_POSITION and indexed == linear",
        ),
        "unsorted_offsets_keep_zero_in_linear_fallback": (
            "offsets: darray[u32] = [TRY_ENCLOSING_DUPLICATE_OFFSET, 0]",
            "try_linear_predecessor(offsets, 0)",
            "linear.found and linear.index == TRY_ENCLOSING_SECOND_POSITION",
        ),
        "try_offsets_are_valid": (
            "forall position in TRY_ENCLOSING_FIRST_POSITION..<offsets.count",
            "offsets[position] != TRY_ENCLOSING_NO_OFFSET",
        ),
        "try_offsets_are_nondecreasing": (
            "forall left in TRY_ENCLOSING_FIRST_POSITION..<offsets.count",
            "forall right in left..<offsets.count: offsets[left] <= offsets[right]",
        ),
        "sorted_binary_predecessor_preserves_parallel_line_mapping": (
            "requires offsets.count == lines.count",
            "requires try_offsets_are_valid(offsets)",
            "requires try_offsets_are_nondecreasing(offsets)",
            "indexed == linear and lines[indexed.index] == lines[linear.index] and offsets[indexed.index] == offsets[linear.index]",
        ),
        "empty_index_reports_no_predecessor": (
            "offsets: darray[u32] = []",
            "not indexed.found and indexed.index == TRY_ENCLOSING_FIRST_POSITION",
        ),
        "sorted_index_without_a_predecessor_reports_fallback_case": (
            "requires try_offsets_are_valid(offsets)",
            "requires try_offsets_are_nondecreasing(offsets)",
            "offsets.count == TRY_ENCLOSING_FIRST_POSITION or offsets[TRY_ENCLOSING_FIRST_POSITION] > query",
            "not indexed.found and indexed.index == TRY_ENCLOSING_FIRST_POSITION and indexed == linear",
        ),
    }
    for name, fragments in positive_shapes.items():
        body = compact_inline(function_section(positive_text, name))
        if any(compact_inline(fragment) not in body for fragment in fragments):
            raise SystemExit(f"positive predecessor theorem changed its stated contract or algorithm: {name}")
    for name in NEGATIVE_NAMES:
        if f"def {name}(" not in negative_text:
            raise SystemExit(f"negative predecessor control missing: {name}")
    negative_shapes = {
        "false_claim_duplicate_offsets_select_the_first_position": "indexed.index == TRY_ENCLOSING_FIRST_POSITION",
        "false_claim_duplicate_offsets_keep_the_first_line": "lines[indexed.index] == lines[TRY_ENCLOSING_FIRST_POSITION]",
        "false_claim_empty_index_has_a_predecessor": "return indexed.found",
        "false_claim_no_predecessor_has_a_position": "return indexed.found",
    }
    for name, fragment in negative_shapes.items():
        if compact_inline(fragment) not in compact_inline(function_section(negative_text, name)):
            raise SystemExit(f"negative predecessor control no longer states its counterclaim: {name}")
    for raw_value in ("middle: usize = low + (high - low) / 2", "low <- middle + 1", "low - 1"):
        if raw_value in positive_text:
            raise SystemExit(f"proof model contains a raw position-search value: {raw_value}")
