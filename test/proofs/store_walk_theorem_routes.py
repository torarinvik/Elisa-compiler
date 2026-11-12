"""Bind store-through theorem inputs to concrete traversal edges."""
from store_walk_holder_traversal_edges import (
    HOLDER_WALK_STATEMENT_EDGES,
    FOR_ITERATOR_VIEW_TAINT_EDGES,
    FOR_ITERATOR_REF_ALIAS_EDGES,
    HOLDER_WALK_EXPRESSION_EDGES,
)
from store_walk_view_flow_edges import (
    BINARY_AND_RIGHT_WALK_EDGE,
    BINARY_RIGHT_VIEW_EDGES,
    BINARY_OPERATOR_FALLBACK_EDGES,
)
from store_walk_view_flow_edges import (
    BINARY_NON_RUNTIME_TARGET_EDGES,
    CONSTRUCT_VIEW_TAINT_EDGES,
    RECORD_UPDATE_VIEW_TAINT_EDGES,
    FIELD_PROJECTION_VIEW_TAINT_EDGES,
    ARRAY_VIEW_TAINT_EDGES,
    COMPREHENSION_VIEW_TAINT_EDGES,
    COMPREHENSION_BINDER_VIEW_TAINT_EDGES,
    IDENTIFIER_VIEW_TAINT_EDGES,
    METHOD_CALL_VIEW_RESULT_EDGES,
    CALLABLE_VIEW_RESULT_EDGES,
    CALL_RESULT_VIEW_TAINT_EDGES,
    STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES,
    ASSIGN_VIEW_TAINT_EDGES,
    VIEW_FLOW_MERGE_EDGES,
    REF_ALIAS_FLOW_MERGE_EDGES,
    REF_ALIAS_HELPER_EDGES,
    INDEX_OPERATOR_EDGES,
    INDEX_VIEW_RESULT_EDGES,
    INDEXN_VIEW_RESULT_EDGES,
    UNARY_NEGATION_EDGES,
    BINARY_VIEW_WALK_EDGES,
    BINARY_BOOLEAN_RESULT_EDGES,
    REINTERPRET_TARGET_MARKER_EDGES,
    UNARY_VIEW_RESULT_EDGES,
    REF_ALIAS_ADDRESS_EDGES,
    SUMMARY_CALL_EDGES,
    OVERLOAD_SUMMARY_EDGES,
    FIELD_UNKNOWN_CALL_EDGES,
    NAMED_CALL_EDGES,
    NAMED_ARGUMENT_UNIFIER_EDGES,
)


theorem_routes = {
    "proof_sts_match_names_reach_fallback": {
        "scrutinee": (("Expr.Match(scrutinee, arms, _):", "sts_collect_names_except(scrutinee, out, copy_safe, copy_values)"),),
        "guard": (("for arm in arms |out, copy_safe, copy_values|:", "sts_collect_names_except(arm.guard, out, copy_safe, copy_values)", 0),),
        "body": (("for arm in arms |out, copy_safe, copy_values|:", "sts_collect_statement_names(arm.body, out)", 0),),
    },
    "proof_sts_catch_names_reach_fallback": {
        "guarded": (("Expr.Catch(guarded, arms, _):", "sts_collect_names_except(guarded, out, copy_safe, copy_values)"),),
        "guard": (("for arm in arms |out, copy_safe, copy_values|:", "sts_collect_names_except(arm.guard, out, copy_safe, copy_values)", 1),),
        "body": (("for arm in arms |out, copy_safe, copy_values|:", "sts_collect_statement_names(arm.body, out)", 1),),
    },
    "proof_sts_block_names_reach_fallback": {
        "capture": (("for capture in captures |out, copy_safe, copy_values|:", "out.push(capture) if capture != \"\""),),
        "statement": (("Expr.Block(statements, value, captures, _):", "sts_collect_statement_names(statements, out)"),),
        "value": (("Expr.Block(statements, value, captures, _):", "sts_collect_names_except(value, out, copy_safe, copy_values)"),),
    },
    "proof_sts_dict_names_reach_fallback": {
        "key": (("for entry in entries |out, copy_safe, copy_values|:", "sts_collect_names_except(entry.key, out, copy_safe, copy_values)"),),
        "value": (("for entry in entries |out, copy_safe, copy_values|:", "sts_collect_names_except(entry.value, out, copy_safe, copy_values)"),),
    },
    "proof_sts_effect_names_reach_fallback": {
        "capture": (),
        "argument": (),
    },
    "proof_sts_match_statement_names_reach_fallback": {
        "scrutinee": (("Stmt.Match(scrutinee, arms, _):", "sts_collect_names(scrutinee, out)"),),
        "guard": (("for arm in arms |out|:", "sts_collect_names(arm.guard, out)"),),
        "body": (("for arm in arms |out|:", "sts_collect_statement_names(arm.body, out)"),),
    },
    "proof_sts_contract_expression_reaches_fallback": {
        "expression": (("Stmt.Contract(_, expression, _):", "sts_collect_names(expression, out)"),),
    },
    "proof_sts_hidden_names_are_unified": {
        "names_found": (("_:", "sts_unify_all(classes, hidden_names)", 2),),
    },
    "proof_sts_nested_callee_calls_reach_unifier": {
        "callee_call": (("Expr.Call(callee, arguments, argument_names, _):", "sts_unify_calls(callee, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),),
    },
    "proof_chv_static_effect_candidates_check_captures_and_arguments": {
        "captures_checked": (("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "candidate_arguments.extend(candidate.captures)"),),
        "arguments_checked": (("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "candidate_arguments.extend(arguments)"),),
    },
    "proof_chv_comprehension_scope_masks_shadowed_reference": {
        "reference_parameter": (("Expr.Comprehension(variable, iterable, condition, body, _, _):", "for outer_ref in ref_params |comprehension_ref_params|:"),),
        "binder_shadows_reference": (("for outer_ref in ref_params |comprehension_ref_params|:", "comprehension_ref_params.push(outer_ref) if outer_ref != variable"),),
    },
    "proof_chv_view_alias_join_preserves_owned_fact": {
        "left_branch_may_own": VIEW_FLOW_MERGE_EDGES,
        "right_branch_may_own": VIEW_FLOW_MERGE_EDGES,
    },
    "proof_chv_aggregate_construct_keeps_field_view_taint": {
        "field_walked": (CONSTRUCT_VIEW_TAINT_EDGES[0], CONSTRUCT_VIEW_TAINT_EDGES[1]),
        "field_taint_joined": (CONSTRUCT_VIEW_TAINT_EDGES[2],),
        "aggregate_taint_set": (CONSTRUCT_VIEW_TAINT_EDGES[3],),
    },
    "proof_chv_record_update_keeps_base_and_field_view_taint": {
        "base_taint_kept": (RECORD_UPDATE_VIEW_TAINT_EDGES[0], RECORD_UPDATE_VIEW_TAINT_EDGES[1]),
        "field_walked": (RECORD_UPDATE_VIEW_TAINT_EDGES[2], RECORD_UPDATE_VIEW_TAINT_EDGES[3]),
        "field_taint_joined": (RECORD_UPDATE_VIEW_TAINT_EDGES[4],),
        "aggregate_taint_set": (RECORD_UPDATE_VIEW_TAINT_EDGES[5],),
    },
    "proof_chv_projection_assignment_preserves_aggregate_taint": {
        "rhs_may_be_view": (ASSIGN_VIEW_TAINT_EDGES[5], ASSIGN_VIEW_TAINT_EDGES[6], ASSIGN_VIEW_TAINT_EDGES[7]),
        "previous_root_may_be_view": (ASSIGN_VIEW_TAINT_EDGES[3],),
        "compound_assignment": (ASSIGN_VIEW_TAINT_EDGES[9],),
        "target_is_projection": (ASSIGN_VIEW_TAINT_EDGES[1],),
    },
    "proof_chv_comprehension_result_tracks_yielded_view": {
        "body_may_be_owned_view": COMPREHENSION_VIEW_TAINT_EDGES,
    },
    "proof_chv_comprehension_element_view_reaches_yielded_result": {
        "collection_taint_reaches_iterable_binding": ARRAY_VIEW_TAINT_EDGES[:4] + (HOLDER_WALK_STATEMENT_EDGES[-1],) + IDENTIFIER_VIEW_TAINT_EDGES,
        "iterable_taint_reaches_binder": COMPREHENSION_BINDER_VIEW_TAINT_EDGES[:3],
        "binder_taint_reaches_result": IDENTIFIER_VIEW_TAINT_EDGES + COMPREHENSION_BINDER_VIEW_TAINT_EDGES[3:],
    },
    "proof_chv_for_iterator_inherits_iterable_view_taint": {
        "iterable_may_be_owned_view": FOR_ITERATOR_VIEW_TAINT_EDGES,
    },
    "proof_chv_for_iterator_inherits_iterable_reference_alias": {
        "yielded_element_alias": (FOR_ITERATOR_REF_ALIAS_EDGES[1], FOR_ITERATOR_REF_ALIAS_EDGES[2]),
        "mutable_slot_alias": (FOR_ITERATOR_REF_ALIAS_EDGES[0], FOR_ITERATOR_REF_ALIAS_EDGES[3]),
        "binder_bound": (FOR_ITERATOR_REF_ALIAS_EDGES[4], FOR_ITERATOR_REF_ALIAS_EDGES[5]),
    },
    "proof_chv_method_result_tracks_receiver_or_arguments": {
        "receiver_may_be_owned": (METHOD_CALL_VIEW_RESULT_EDGES[2],),
        "arguments_may_be_owned": (METHOD_CALL_VIEW_RESULT_EDGES[3],),
    },
    "proof_chv_callable_result_tracks_argument_view": {
        "argument_may_be_owned": CALLABLE_VIEW_RESULT_EDGES,
    },
    "proof_chv_call_result_tracks_argument_view": {
        "direct_result_may_be_owned": (CALL_RESULT_VIEW_TAINT_EDGES[0],),
        "argument_may_be_owned": (CALL_RESULT_VIEW_TAINT_EDGES[1],),
    },
    "proof_chv_static_effect_result_tracks_runtime_views": {
        "runtime_child_may_be_owned": STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES,
    },
    "proof_chv_aggregate_field_projection_requires_tainted_root": {
        "root_is_known": FIELD_PROJECTION_VIEW_TAINT_EDGES[:2],
        "aggregate_may_contain_view": (FIELD_PROJECTION_VIEW_TAINT_EDGES[2],),
    },
    "proof_chv_reference_alias_join_preserves_either_path": {
        "left_path_may_alias": REF_ALIAS_FLOW_MERGE_EDGES,
        "right_path_may_alias": REF_ALIAS_FLOW_MERGE_EDGES,
    },
    "proof_chv_reference_targets_cover_alias_routes": {
        "direct_parameter": (REF_ALIAS_HELPER_EDGES[2],),
        "local_alias": REF_ALIAS_HELPER_EDGES[:2],
        "call_result": (REF_ALIAS_HELPER_EDGES[3],),
        "projection_fallback": (REF_ALIAS_HELPER_EDGES[5],),
        "aggregate_alias": REF_ALIAS_HELPER_EDGES[8:],
    },
    "proof_chv_comprehension_result_tracks_yielded_alias": {
        "yielded_element_alias_checked": (),
        "binder_alias_bound": (),
        "body_alias_checked": (),
    },
    "proof_chv_getelse_recovery_termination_excludes_recovery_state": {
        "guarded_path_joined": (),
        "recovery_terminates": (),
        "recovery_path_joined": (),
        "recovery_path_excluded": (),
        "recovery_value_joined": (),
    },
    "proof_chv_scalar_sview_rebinding_prefers_latest_fact": {
        "flow_row_found": (),
        "flow_scalar": (),
        "initializer_scalar": (),
    },
    "proof_chv_binary_operator_checks_both_operands": {
        "receiver_checked": (HOLDER_WALK_EXPRESSION_EDGES[21],),
        "operand_checked": (BINARY_NON_RUNTIME_TARGET_EDGES[0], BINARY_NON_RUNTIME_TARGET_EDGES[1], HOLDER_WALK_EXPRESSION_EDGES[23], BINARY_AND_RIGHT_WALK_EDGE),
        "fallback_checked": (BINARY_NON_RUNTIME_TARGET_EDGES[0], BINARY_NON_RUNTIME_TARGET_EDGES[1]) + BINARY_OPERATOR_FALLBACK_EDGES,
    },
    "proof_chv_binary_target_operators_skip_runtime_value_path": {
        "target_operator": (BINARY_NON_RUNTIME_TARGET_EDGES[0],),
        "target_classified": (BINARY_NON_RUNTIME_TARGET_EDGES[1],),
        "right_walk_guarded": (HOLDER_WALK_EXPRESSION_EDGES[22], HOLDER_WALK_EXPRESSION_EDGES[23], BINARY_AND_RIGHT_WALK_EDGE),
        "fallback_guarded": (HOLDER_WALK_EXPRESSION_EDGES[22],) + BINARY_OPERATOR_FALLBACK_EDGES,
    },
    "proof_chv_binary_operator_result_tracks_reference_operands": {
        "boolean_result": (REF_ALIAS_HELPER_EDGES[6], BINARY_BOOLEAN_RESULT_EDGES[1], BINARY_BOOLEAN_RESULT_EDGES[2]) + REINTERPRET_TARGET_MARKER_EDGES,
        "left_alias": (REF_ALIAS_HELPER_EDGES[4],),
        "right_alias": (REF_ALIAS_HELPER_EDGES[4],),
    },
    "proof_chv_binary_operator_result_tracks_view_operands": {
        "boolean_result": BINARY_BOOLEAN_RESULT_EDGES + REINTERPRET_TARGET_MARKER_EDGES,
        "left_may_be_view": (BINARY_VIEW_WALK_EDGES[0], BINARY_VIEW_WALK_EDGES[3]),
        "right_may_be_view": (HOLDER_WALK_EXPRESSION_EDGES[22], BINARY_AND_RIGHT_WALK_EDGE,
                               BINARY_RIGHT_VIEW_EDGES[0], HOLDER_WALK_EXPRESSION_EDGES[23],
                               BINARY_RIGHT_VIEW_EDGES[1], BINARY_VIEW_WALK_EDGES[3]),
    },
    "proof_chv_binary_boolean_result_clears_view_taint": {
        "boolean_result_classified": BINARY_BOOLEAN_RESULT_EDGES[:3] + REINTERPRET_TARGET_MARKER_EDGES,
        "result_taint_cleared": (BINARY_BOOLEAN_RESULT_EDGES[3],),
    },
    "proof_chv_index_overloads_check_receiver_and_keys": {
        "receiver_checked": (INDEX_OPERATOR_EDGES[0], INDEX_OPERATOR_EDGES[7]),
        "key_checked": (INDEX_OPERATOR_EDGES[2],),
        "call_checked": INDEX_OPERATOR_EDGES[3:7],
        "type_application_skipped": (INDEX_OPERATOR_EDGES[1], INDEX_OPERATOR_EDGES[8], INDEX_OPERATOR_EDGES[9]),
    },
    "proof_chv_index_result_tracks_receiver_view": {
        "receiver_may_be_view": (INDEX_VIEW_RESULT_EDGES[3],),
        "index_key_may_be_view": (INDEX_VIEW_RESULT_EDGES[2],),
        "runtime_index_guarded": (INDEX_VIEW_RESULT_EDGES[1],),
    },
    "proof_chv_indexn_result_tracks_receiver_only": {
        "receiver_may_be_view": INDEXN_VIEW_RESULT_EDGES,
    },
    "proof_chv_address_of_uses_operand_reference_provenance": {
        "boolean_not": (REF_ALIAS_ADDRESS_EDGES[1],),
        "operand_alias_checked": (REF_ALIAS_ADDRESS_EDGES[0],),
    },
    "proof_chv_unary_negation_tracks_reference_operand": {
        "boolean_not": (REF_ALIAS_ADDRESS_EDGES[1],),
        "operand_alias_checked": (REF_ALIAS_ADDRESS_EDGES[0],),
    },
    "proof_chv_unary_negation_visits_operand": {
        "operand_checked": (UNARY_NEGATION_EDGES[0],),
    },
    "proof_chv_unary_negation_tracks_view_operand": {
        "boolean_not": (UNARY_VIEW_RESULT_EDGES[1],),
        "operand_may_be_view": (UNARY_VIEW_RESULT_EDGES[0],),
    },
    "proof_chv_projection_fallback_requires_caller_reference": {
        "caller_reference_exists": (REF_ALIAS_HELPER_EDGES[5],),
    },
    "proof_chv_overload_bodies_contribute_store_rows": {
        "overload_body_checked": OVERLOAD_SUMMARY_EDGES,
    },
    "proof_chv_method_calls_check_receiver_and_arguments": {
        "receiver_checked": (("Expr.Field(receiver, method, _):", "method_arguments: mutable darray[Ast::Expr] = [receiver]"),),
        "arguments_checked": (("Expr.Field(receiver, method, _):", "method_arguments.extend(call_arguments)"),),
    },
    "proof_chv_indirect_calls_fail_closed": {
        "reference_target_checked": (("for target in 0..<call_arguments.count |table| -> table:", "if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow, table):"),),
        "owned_view_checked": (("for source in 0..<call_arguments.count |table| -> table:", "if source != target and chv_owned_view_at(call_arguments, argument_owned_views, source, flow):"),),
    },
    "proof_chv_summary_calls_check_reference_aliases": {
        "reference_alias_checked": SUMMARY_CALL_EDGES[:2],
        "owned_view_checked": SUMMARY_CALL_EDGES[2:],
    },
    "proof_chv_named_callees_cover_dispatch_routes": {
        "direct_call_checked": (
            ("Expr.Scope(_, scoped_name, _):", "table <- chv_check_named_call(scoped_name, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
            ("Expr.Index(head, _, _):", "table <- chv_check_named_callee(head, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
        ),
    },
    "proof_chv_named_arguments_use_unknown_call_fallback": {
        "named_arguments_present": NAMED_CALL_EDGES,
    },
    "proof_sts_named_argument_calls_use_conservative_fallback": {
        "named_arguments_present": NAMED_ARGUMENT_UNIFIER_EDGES,
    },
    "proof_chv_field_calls_use_unknown_fallback": {
        "field_call_present": FIELD_UNKNOWN_CALL_EDGES,
    },
}
