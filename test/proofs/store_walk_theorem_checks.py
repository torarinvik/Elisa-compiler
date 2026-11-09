"""Bind store-through theorem routes to their source walkers."""
from __future__ import annotations

from store_walk_collection_edges import (
    EXPRESSION_EDGES,
    STATEMENT_COLLECTOR_EDGES,
    EXPRESSION_UNIFIER_EDGES,
)
from store_walk_holder_traversal_edges import (
    HOLDER_WALK_STATEMENT_EDGES,
    FOR_ITERATOR_VIEW_TAINT_EDGES,
    FOR_ITERATOR_REF_ALIAS_EDGES,
    ITERABLE_BINDING_FACTS_ALIAS_EDGES,
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
    CALL_RESULT_CALLEE_JOIN_EDGE,
    CALL_CALLEE_INDEXED_VIEW_EDGES,
    STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES,
    ASSIGN_VIEW_TAINT_EDGES,
    EFFECT_CANDIDATE_EDGES,
    VIEW_FLOW_MERGE_EDGES,
    REF_ALIAS_FLOW_MERGE_EDGES,
    REF_ALIAS_HELPER_EDGES,
    COMPREHENSION_REF_ALIAS_EDGES,
    COMPREHENSION_CONTAIN_ALIAS_EDGES,
    ITERABLE_REF_ALIAS_EDGES,
    ITERABLE_CONTAIN_ALIAS_EDGES,
    GETELSE_RECOVERY_TERMINATION_EDGES,
    SCALAR_SVIEW_FLOW_EDGES,
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
    CALLEE_DISPATCH_EDGES,
    FIELD_UNKNOWN_CALL_EDGES,
    NAMED_CALL_EDGES,
    NAMED_ARGUMENT_UNIFIER_EDGES,
    UNKNOWN_CALL_EDGES,
    UNIFIER_FALLBACK_EDGES,
)
from store_walk_theorem_routes import theorem_routes
from store_walk_inspection import (function_section, validate_or_theorem, validate_exact_boolean_theorem, validate_exact_boolean_theorem_source_routes)


def validate_theorem_routes(
    collect_source,
    effect_text,
    holder_text,
    holder_walk_expressions,
    holder_walk_statements,
    positive_text,
    statement_collect_source,
    unifier_source,
):
    for name, routes in theorem_routes.items():
        source_route_sources = None
        source_route_edges = None
        if name == "proof_sts_effect_names_reach_fallback":
            proof_source, proof_edges = effect_text, ()
        elif name == "proof_chv_static_effect_candidates_check_captures_and_arguments":
            proof_source = function_section(holder_text, "chv_check_static_effect_call")
            proof_edges = EFFECT_CANDIDATE_EDGES
        elif name == "proof_chv_comprehension_scope_masks_shadowed_reference":
            proof_source, proof_edges = holder_walk_expressions, HOLDER_WALK_EXPRESSION_EDGES
        elif name == "proof_chv_binary_operator_checks_both_operands":
            source_route_sources = {
                "walker": holder_walk_expressions,
                "target": function_section(holder_text, "chv_binary_operator_has_non_runtime_target"),
            }
            source_route_edges = {
                "receiver_checked": (("walker", HOLDER_WALK_EXPRESSION_EDGES[21]),),
                "operand_checked": (("target", BINARY_NON_RUNTIME_TARGET_EDGES[0]),
                                    ("walker", BINARY_NON_RUNTIME_TARGET_EDGES[1]),
                                    ("walker", HOLDER_WALK_EXPRESSION_EDGES[23]),
                                    ("walker", BINARY_AND_RIGHT_WALK_EDGE)),
                "fallback_checked": (("target", BINARY_NON_RUNTIME_TARGET_EDGES[0]),
                                     ("walker", BINARY_NON_RUNTIME_TARGET_EDGES[1])) + tuple(
                                         ("walker", edge) for edge in BINARY_OPERATOR_FALLBACK_EDGES),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_binary_operator_result_tracks_reference_operands":
            source_route_sources = {
                "alias": function_section(holder_text, "chv_expression_may_alias_ref"),
                "operator": function_section(holder_text, "chv_binary_operator_returns_bool"),
                "marker": function_section(holder_text, "chv_is_reinterpret_target_marker"),
            }
            source_route_edges = {
                "boolean_result": (("alias", REF_ALIAS_HELPER_EDGES[6]),
                                   ("operator", BINARY_BOOLEAN_RESULT_EDGES[1]),
                                   ("operator", BINARY_BOOLEAN_RESULT_EDGES[2])) +
                                  tuple(("marker", edge) for edge in REINTERPRET_TARGET_MARKER_EDGES),
                "left_alias": (("alias", REF_ALIAS_HELPER_EDGES[4]),),
                "right_alias": (("alias", REF_ALIAS_HELPER_EDGES[4]),),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_binary_operator_result_tracks_view_operands":
            source_route_sources = {
                "walker": holder_walk_expressions,
                "operator": function_section(holder_text, "chv_binary_operator_returns_bool"),
                "marker": function_section(holder_text, "chv_is_reinterpret_target_marker"),
            }
            boolean_result_route = (("walker", BINARY_BOOLEAN_RESULT_EDGES[0]),
                                    ("operator", BINARY_BOOLEAN_RESULT_EDGES[1]),
                                    ("operator", BINARY_BOOLEAN_RESULT_EDGES[2])) + tuple(
                                        ("marker", edge) for edge in REINTERPRET_TARGET_MARKER_EDGES)
            source_route_edges = {
                "boolean_result": boolean_result_route,
                "left_may_be_view": (("walker", BINARY_VIEW_WALK_EDGES[0]),
                                     ("walker", BINARY_VIEW_WALK_EDGES[3])),
                "right_may_be_view": (("walker", HOLDER_WALK_EXPRESSION_EDGES[22]),
                                      ("walker", BINARY_AND_RIGHT_WALK_EDGE),
                                      ("walker", BINARY_RIGHT_VIEW_EDGES[0]),
                                      ("walker", HOLDER_WALK_EXPRESSION_EDGES[23]),
                                      ("walker", BINARY_RIGHT_VIEW_EDGES[1]),
                                      ("walker", BINARY_VIEW_WALK_EDGES[3])),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_binary_target_operators_skip_runtime_value_path":
            source_route_sources = {
                "walker": holder_walk_expressions,
                "target": function_section(holder_text, "chv_binary_operator_has_non_runtime_target"),
            }
            source_route_edges = {
                "target_operator": (("target", BINARY_NON_RUNTIME_TARGET_EDGES[0]),),
                "target_classified": (("walker", BINARY_NON_RUNTIME_TARGET_EDGES[1]),),
                "right_walk_guarded": (("walker", HOLDER_WALK_EXPRESSION_EDGES[22]),
                                       ("walker", HOLDER_WALK_EXPRESSION_EDGES[23]),
                                       ("walker", BINARY_AND_RIGHT_WALK_EDGE)),
                "fallback_guarded": (("walker", HOLDER_WALK_EXPRESSION_EDGES[22]),) + tuple(
                    ("walker", edge) for edge in BINARY_OPERATOR_FALLBACK_EDGES),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_binary_boolean_result_clears_view_taint":
            source_route_sources = {
                "walker": holder_walk_expressions,
                "operator": function_section(holder_text, "chv_binary_operator_returns_bool"),
                "marker": function_section(holder_text, "chv_is_reinterpret_target_marker"),
            }
            source_route_edges = {
                "boolean_result_classified": (("walker", BINARY_BOOLEAN_RESULT_EDGES[0]),
                                              ("operator", BINARY_BOOLEAN_RESULT_EDGES[1]),
                                              ("operator", BINARY_BOOLEAN_RESULT_EDGES[2])) +
                                             tuple(("marker", edge) for edge in REINTERPRET_TARGET_MARKER_EDGES),
                "result_taint_cleared": (("walker", BINARY_BOOLEAN_RESULT_EDGES[3]),),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_index_overloads_check_receiver_and_keys":
            proof_source, proof_edges = holder_walk_expressions, INDEX_OPERATOR_EDGES
        elif name == "proof_chv_index_result_tracks_receiver_view":
            proof_source = function_section(holder_text, "chv_is_owned_view")
            proof_edges = INDEX_VIEW_RESULT_EDGES
        elif name == "proof_chv_indexn_result_tracks_receiver_only":
            proof_source = function_section(holder_text, "chv_is_owned_view")
            proof_edges = INDEXN_VIEW_RESULT_EDGES
        elif name == "proof_chv_view_alias_join_preserves_owned_fact":
            proof_source = function_section(holder_text, "chv_flow_set_merge")
            proof_edges = VIEW_FLOW_MERGE_EDGES
        elif name == "proof_chv_aggregate_construct_keeps_field_view_taint":
            proof_source, proof_edges = holder_walk_expressions, CONSTRUCT_VIEW_TAINT_EDGES
        elif name == "proof_chv_record_update_keeps_base_and_field_view_taint":
            proof_source, proof_edges = holder_walk_expressions, RECORD_UPDATE_VIEW_TAINT_EDGES
        elif name == "proof_chv_projection_assignment_preserves_aggregate_taint":
            proof_source, proof_edges = holder_walk_statements, ASSIGN_VIEW_TAINT_EDGES
        elif name == "proof_chv_comprehension_result_tracks_yielded_view":
            proof_source, proof_edges = holder_walk_expressions, COMPREHENSION_VIEW_TAINT_EDGES
        elif name == "proof_chv_for_iterator_inherits_iterable_view_taint":
            proof_source, proof_edges = holder_walk_statements, FOR_ITERATOR_VIEW_TAINT_EDGES
        elif name == "proof_chv_for_iterator_inherits_iterable_reference_alias":
            source_route_sources = {
                "walker": holder_walk_statements,
                "iterable_alias": function_section(holder_text, "chv_iterable_element_may_alias_reference"),
                "iterable_contain": function_section(holder_text, "chv_iterable_element_may_contain_alias_ref"),
                "binding_facts": function_section(holder_text, "chv_iterable_binding_facts"),
                "container": function_section(holder_text, "chv_expression_may_contain_alias_ref"),
            }
            source_route_edges = {
                "yielded_element_alias": (("walker", FOR_ITERATOR_REF_ALIAS_EDGES[1]),) +
                                         tuple(("iterable_alias", edge) for edge in ITERABLE_REF_ALIAS_EDGES) +
                                         tuple(("iterable_contain", edge) for edge in ITERABLE_CONTAIN_ALIAS_EDGES) +
                                         tuple(("container", edge) for edge in COMPREHENSION_CONTAIN_ALIAS_EDGES),
                "mutable_slot_alias": (("walker", FOR_ITERATOR_REF_ALIAS_EDGES[0]),
                                       ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[3])),
                "binder_bound": (("walker", FOR_ITERATOR_REF_ALIAS_EDGES[4]),
                                 ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[0]),
                                 ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[1]),
                                 ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[2]),
                                 ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[3]),
                                 ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[4]),
                                 ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[5]),
                                 ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[6]),
                                 ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[7]),
                                 ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[8])),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_comprehension_result_tracks_yielded_alias":
            source_route_sources = {
                "comprehension": function_section(holder_text, "chv_expression_may_alias_ref"),
                "iterable_alias": function_section(holder_text, "chv_iterable_element_may_alias_reference"),
                "iterable_contain": function_section(holder_text, "chv_iterable_element_may_contain_alias_ref"),
                "container": function_section(holder_text, "chv_expression_may_contain_alias_ref"),
                "walker": holder_walk_expressions,
            }
            source_route_edges = {
                "yielded_element_alias_checked": (("comprehension", COMPREHENSION_REF_ALIAS_EDGES[0]),) +
                                                 tuple(("iterable_alias", edge) for edge in ITERABLE_REF_ALIAS_EDGES) +
                                                 tuple(("iterable_contain", edge) for edge in ITERABLE_CONTAIN_ALIAS_EDGES) +
                                                 tuple(("container", edge) for edge in COMPREHENSION_CONTAIN_ALIAS_EDGES),
                "binder_alias_bound": (("comprehension", COMPREHENSION_REF_ALIAS_EDGES[1]),
                                       ("walker", HOLDER_WALK_EXPRESSION_EDGES[10])),
                "body_alias_checked": (("comprehension", COMPREHENSION_REF_ALIAS_EDGES[2]),
                                       ("comprehension", COMPREHENSION_REF_ALIAS_EDGES[3]),
                                       ("walker", HOLDER_WALK_EXPRESSION_EDGES[11])),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_getelse_recovery_termination_excludes_recovery_state":
            # Keep the enclosing Expr.GetElse row in the source slice: the route
            # edges below are intentionally bound from that arm to its branch
            # merge operations.
            source_route_sources = {"getelse": holder_walk_expressions}
            source_route_edges = {
                "guarded_path_joined": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[2]),
                                        ("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[3])),
                "recovery_terminates": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[0]),),
                "recovery_path_joined": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[2]),),
                "recovery_path_excluded": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[3]),),
                "recovery_value_joined": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[1]),),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_scalar_sview_rebinding_prefers_latest_fact":
            source_route_sources = {"flow": function_section(holder_text, "chv_expression_is_scalar_sview")}
            source_route_edges = {
                "flow_row_found": (("flow", SCALAR_SVIEW_FLOW_EDGES[0]), ("flow", SCALAR_SVIEW_FLOW_EDGES[1])),
                "flow_scalar": (("flow", SCALAR_SVIEW_FLOW_EDGES[2]),),
                "initializer_scalar": (("flow", SCALAR_SVIEW_FLOW_EDGES[3]),),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_comprehension_element_view_reaches_yielded_result":
            proof_source = "\n".join((
                holder_walk_expressions,
                holder_walk_statements,
                function_section(holder_text, "chv_is_owned_view"),
            ))
            proof_edges = ARRAY_VIEW_TAINT_EDGES[:4] + (HOLDER_WALK_STATEMENT_EDGES[-1],) + IDENTIFIER_VIEW_TAINT_EDGES + COMPREHENSION_BINDER_VIEW_TAINT_EDGES
        elif name == "proof_chv_method_result_tracks_receiver_or_arguments":
            proof_source = function_section(holder_text, "chv_is_owned_view")
            proof_edges = METHOD_CALL_VIEW_RESULT_EDGES
        elif name == "proof_chv_callable_result_tracks_argument_view":
            proof_source = function_section(holder_text, "chv_is_owned_view")
            proof_edges = CALLABLE_VIEW_RESULT_EDGES
        elif name == "proof_chv_call_result_tracks_argument_view":
            source_route_sources = {
                "walker": holder_walk_expressions,
                "callee": function_section(holder_text, "chv_walk_call_callee"),
            }
            source_route_edges = {
                "direct_result_may_be_owned": (("walker", HOLDER_WALK_EXPRESSION_EDGES[0]),) +
                                              tuple(("callee", edge) for edge in CALL_CALLEE_INDEXED_VIEW_EDGES) +
                                              (("walker", CALL_RESULT_CALLEE_JOIN_EDGE),
                                               ("walker", CALL_RESULT_VIEW_TAINT_EDGES[2])),
                "argument_may_be_owned": (("walker", CALL_RESULT_VIEW_TAINT_EDGES[1]),
                                          ("walker", CALL_RESULT_VIEW_TAINT_EDGES[2])),
            }
            proof_source, proof_edges = "", ()
        elif name == "proof_chv_static_effect_result_tracks_runtime_views":
            proof_source, proof_edges = holder_walk_expressions, STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES
        elif name == "proof_chv_aggregate_field_projection_requires_tainted_root":
            proof_source = function_section(holder_text, "chv_is_owned_view")
            proof_edges = FIELD_PROJECTION_VIEW_TAINT_EDGES
        elif name == "proof_chv_reference_alias_join_preserves_either_path":
            proof_source = function_section(holder_text, "chv_flow_set_merge")
            proof_edges = REF_ALIAS_FLOW_MERGE_EDGES
        elif name == "proof_chv_reference_targets_cover_alias_routes":
            proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
            proof_edges = REF_ALIAS_HELPER_EDGES
        elif name == "proof_chv_address_of_uses_operand_reference_provenance":
            proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
            proof_edges = REF_ALIAS_ADDRESS_EDGES
        elif name == "proof_chv_unary_negation_tracks_reference_operand":
            proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
            proof_edges = REF_ALIAS_ADDRESS_EDGES
        elif name == "proof_chv_unary_negation_visits_operand":
            proof_source, proof_edges = holder_walk_expressions, UNARY_NEGATION_EDGES
        elif name == "proof_chv_unary_negation_tracks_view_operand":
            proof_source = function_section(holder_text, "chv_is_owned_view")
            proof_edges = UNARY_VIEW_RESULT_EDGES
        elif name == "proof_chv_projection_fallback_requires_caller_reference":
            proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
            proof_edges = REF_ALIAS_HELPER_EDGES
        elif name == "proof_chv_overload_bodies_contribute_store_rows":
            proof_source = function_section(holder_text, "chv_build_summary")
            proof_edges = OVERLOAD_SUMMARY_EDGES
        elif name == "proof_chv_method_calls_check_receiver_and_arguments":
            proof_source = function_section(holder_text, "chv_check_named_callee")
            proof_edges = FIELD_UNKNOWN_CALL_EDGES
        elif name == "proof_chv_named_callees_cover_dispatch_routes":
            proof_source = function_section(holder_text, "chv_check_named_callee")
            proof_edges = CALLEE_DISPATCH_EDGES
        elif name == "proof_chv_indirect_calls_fail_closed":
            proof_source = function_section(holder_text, "chv_check_unknown_call")
            proof_edges = UNKNOWN_CALL_EDGES
        elif name == "proof_chv_summary_calls_check_reference_aliases":
            proof_source = function_section(holder_text, "chv_check_call_target")
            proof_edges = SUMMARY_CALL_EDGES
        elif name == "proof_chv_named_arguments_use_unknown_call_fallback":
            proof_source = function_section(holder_text, "chv_check_named_call")
            proof_edges = NAMED_CALL_EDGES
        elif name == "proof_sts_named_argument_calls_use_conservative_fallback":
            proof_source, proof_edges = unifier_source, NAMED_ARGUMENT_UNIFIER_EDGES
        elif name == "proof_chv_named_arguments_use_unknown_call_fallback":
            proof_source = function_section(holder_text, "chv_check_named_call")
            proof_edges = NAMED_CALL_EDGES
        elif name == "proof_sts_named_argument_calls_use_conservative_fallback":
            proof_source, proof_edges = unifier_source, NAMED_ARGUMENT_UNIFIER_EDGES
        elif name == "proof_chv_field_calls_use_unknown_fallback":
            proof_source = function_section(holder_text, "chv_check_named_callee")
            proof_edges = FIELD_UNKNOWN_CALL_EDGES
        elif name in ("proof_sts_match_statement_names_reach_fallback", "proof_sts_contract_expression_reaches_fallback"):
            proof_source, proof_edges = statement_collect_source, STATEMENT_COLLECTOR_EDGES
        elif name == "proof_sts_hidden_names_are_unified":
            proof_source, proof_edges = unifier_source, UNIFIER_FALLBACK_EDGES
        elif name == "proof_sts_nested_callee_calls_reach_unifier":
            proof_source, proof_edges = unifier_source, EXPRESSION_UNIFIER_EDGES
        else:
            proof_source, proof_edges = collect_source, EXPRESSION_EDGES
        if source_route_edges is not None:
            boolean_expressions = {
                "proof_chv_binary_operator_checks_both_operands": "receiver_checked and operand_checked and fallback_checked",
                "proof_chv_binary_operator_result_tracks_reference_operands": "not boolean_result and (left_alias or right_alias)",
                "proof_chv_binary_operator_result_tracks_view_operands": "not boolean_result and (left_may_be_view or right_may_be_view)",
                "proof_chv_binary_boolean_result_clears_view_taint": "boolean_result_classified and result_taint_cleared",
                "proof_chv_call_result_tracks_argument_view": "direct_result_may_be_owned or argument_may_be_owned",
                "proof_chv_binary_target_operators_skip_runtime_value_path": "target_operator and target_classified and right_walk_guarded and fallback_guarded",
                "proof_chv_comprehension_result_tracks_yielded_alias": "yielded_element_alias_checked and binder_alias_bound and body_alias_checked",
                "proof_chv_for_iterator_inherits_iterable_reference_alias": "binder_bound and (yielded_element_alias or mutable_slot_alias)",
                "proof_chv_getelse_recovery_termination_excludes_recovery_state": "guarded_path_joined and ((recovery_terminates and recovery_path_excluded and not recovery_path_joined and not recovery_value_joined) or (not recovery_terminates and recovery_path_joined and recovery_value_joined))",
                "proof_chv_scalar_sview_rebinding_prefers_latest_fact": "(flow_row_found and flow_scalar) or (not flow_row_found and initializer_scalar)",
            }
            validate_exact_boolean_theorem_source_routes(
                positive_text, name, tuple(routes), boolean_expressions[name],
                source_route_sources, source_route_edges)
        elif name == "proof_chv_static_effect_candidates_check_captures_and_arguments":
            validate_exact_boolean_theorem(positive_text, name, routes, "captures_checked and arguments_checked", proof_source, proof_edges)
        elif name == "proof_chv_comprehension_scope_masks_shadowed_reference":
            validate_exact_boolean_theorem(positive_text, name, routes, "reference_parameter and not binder_shadows_reference", proof_source, proof_edges)
        elif name == "proof_chv_method_calls_check_receiver_and_arguments":
            validate_exact_boolean_theorem(positive_text, name, routes, "receiver_checked and arguments_checked", proof_source, proof_edges)
        elif name == "proof_chv_indirect_calls_fail_closed":
            validate_exact_boolean_theorem(positive_text, name, routes, "reference_target_checked and owned_view_checked", proof_source, proof_edges)
        elif name == "proof_chv_view_alias_join_preserves_owned_fact":
            validate_exact_boolean_theorem(positive_text, name, routes, "left_branch_may_own or right_branch_may_own", proof_source, proof_edges)
        elif name == "proof_chv_aggregate_construct_keeps_field_view_taint":
            validate_exact_boolean_theorem(positive_text, name, routes, "field_walked and field_taint_joined and aggregate_taint_set", proof_source, proof_edges)
        elif name == "proof_chv_record_update_keeps_base_and_field_view_taint":
            validate_exact_boolean_theorem(positive_text, name, routes, "base_taint_kept and field_walked and field_taint_joined and aggregate_taint_set", proof_source, proof_edges)
        elif name == "proof_chv_projection_assignment_preserves_aggregate_taint":
            validate_exact_boolean_theorem(positive_text, name, routes, "rhs_may_be_view or ((compound_assignment or target_is_projection) and previous_root_may_be_view)", proof_source, proof_edges)
        elif name == "proof_chv_comprehension_result_tracks_yielded_view":
            validate_exact_boolean_theorem(positive_text, name, routes, "body_may_be_owned_view", proof_source, proof_edges)
        elif name == "proof_chv_comprehension_element_view_reaches_yielded_result":
            validate_exact_boolean_theorem(positive_text, name, routes, "collection_taint_reaches_iterable_binding and iterable_taint_reaches_binder and binder_taint_reaches_result", proof_source, proof_edges)
        elif name == "proof_chv_for_iterator_inherits_iterable_view_taint":
            validate_exact_boolean_theorem(positive_text, name, routes, "iterable_may_be_owned_view", proof_source, proof_edges)
        elif name == "proof_chv_for_iterator_inherits_iterable_reference_alias":
            validate_exact_boolean_theorem(positive_text, name, routes, "binder_bound and (yielded_element_alias or mutable_slot_alias)", proof_source, proof_edges)
        elif name == "proof_chv_comprehension_result_tracks_yielded_alias":
            validate_exact_boolean_theorem_source_routes(
                positive_text, name, tuple(routes),
                "yielded_element_alias_checked and binder_alias_bound and body_alias_checked",
                source_route_sources, source_route_edges)
        elif name == "proof_chv_method_result_tracks_receiver_or_arguments":
            validate_exact_boolean_theorem(positive_text, name, routes, "receiver_may_be_owned or arguments_may_be_owned", proof_source, proof_edges)
        elif name == "proof_chv_callable_result_tracks_argument_view":
            validate_exact_boolean_theorem(positive_text, name, routes, "argument_may_be_owned", proof_source, proof_edges)
        elif name == "proof_chv_call_result_tracks_argument_view":
            validate_exact_boolean_theorem(positive_text, name, routes, "direct_result_may_be_owned or argument_may_be_owned", proof_source, proof_edges)
        elif name == "proof_chv_static_effect_result_tracks_runtime_views":
            validate_exact_boolean_theorem(positive_text, name, routes, "runtime_child_may_be_owned", proof_source, proof_edges)
        elif name == "proof_chv_aggregate_field_projection_requires_tainted_root":
            validate_exact_boolean_theorem(positive_text, name, routes, "root_is_known and aggregate_may_contain_view", proof_source, proof_edges)
        elif name == "proof_chv_reference_alias_join_preserves_either_path":
            validate_exact_boolean_theorem(positive_text, name, routes, "left_path_may_alias or right_path_may_alias", proof_source, proof_edges)
        elif name == "proof_chv_reference_targets_cover_alias_routes":
            validate_exact_boolean_theorem(positive_text, name, routes, "direct_parameter and local_alias and call_result and projection_fallback and aggregate_alias", proof_source, proof_edges)
        elif name == "proof_chv_binary_operator_checks_both_operands":
            validate_exact_boolean_theorem(positive_text, name, routes, "receiver_checked and operand_checked and fallback_checked", proof_source, proof_edges)
        elif name == "proof_chv_index_overloads_check_receiver_and_keys":
            validate_exact_boolean_theorem(positive_text, name, routes, "receiver_checked and key_checked and call_checked and type_application_skipped", proof_source, proof_edges)
        elif name == "proof_chv_index_result_tracks_receiver_view":
            validate_exact_boolean_theorem(positive_text, name, routes, "receiver_may_be_view or (runtime_index_guarded and index_key_may_be_view)", proof_source, proof_edges)
        elif name == "proof_chv_indexn_result_tracks_receiver_only":
            validate_exact_boolean_theorem(positive_text, name, routes, "receiver_may_be_view", proof_source, proof_edges)
        elif name == "proof_chv_address_of_uses_operand_reference_provenance":
            validate_exact_boolean_theorem(positive_text, name, routes, "not boolean_not and operand_alias_checked", proof_source, proof_edges)
        elif name == "proof_chv_unary_negation_tracks_reference_operand":
            validate_exact_boolean_theorem(positive_text, name, routes, "not boolean_not and operand_alias_checked", proof_source, proof_edges)
        elif name == "proof_chv_unary_negation_visits_operand":
            validate_exact_boolean_theorem(positive_text, name, routes, "operand_checked", proof_source, proof_edges)
        elif name == "proof_chv_unary_negation_tracks_view_operand":
            validate_exact_boolean_theorem(positive_text, name, routes, "not boolean_not and operand_may_be_view", proof_source, proof_edges)
        elif name == "proof_chv_projection_fallback_requires_caller_reference":
            validate_exact_boolean_theorem(positive_text, name, routes, "caller_reference_exists", proof_source, proof_edges)
        elif name == "proof_chv_summary_calls_check_reference_aliases":
            validate_exact_boolean_theorem(positive_text, name, routes, "reference_alias_checked and owned_view_checked", proof_source, proof_edges)
        elif name in ("proof_chv_named_arguments_use_unknown_call_fallback", "proof_sts_named_argument_calls_use_conservative_fallback", "proof_chv_field_calls_use_unknown_fallback"):
            validate_or_theorem(positive_text, name, routes, proof_source, proof_edges)
        else:
            validate_or_theorem(positive_text, name, routes, proof_source, proof_edges)
