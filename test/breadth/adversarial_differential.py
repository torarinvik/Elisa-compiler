#!/usr/bin/env python3
"""Adversarial DIFFERENTIAL tester for stage1.

Method is the differential corpus's, with adversarially CHOSEN inputs rather than a curated
tree: build each program with BOTH compilers, link, run, compare exit codes.

  MATCH     both ran, same exit code
  MISMATCH  both ran, DIFFERENT exit codes      <- a silent wrong answer, the worst outcome
  DECLINE   stage0 built it, stage1 could not   <- an acceptance gap
  SKIP      stage0 could not build it           <- not a parity signal (the program is bad)

Every bug found in this session lived in a shape the compiler's own source never uses, so
the generators below deliberately target those: overload resolution, generic instantiation
naming, extern declarations, container literals in value position, const enums.

WHAT THIS HARNESS STRUCTURALLY CANNOT COVER (checked 2026-08-08, don't re-derive it):
every program here is BARE MODE -- standalone source with no std include, linked against
elisacore_runtime.o. So any construct whose operands are STD TYPES is unreachable from
here no matter how the generator is written:

  * `parallel for` / `nursery` / `pool`. stage0 requires the iterable to be a mutable
    Slice[T], a frozen packed store, or a readonly dense view -- a plain darray is
    rejected outright ("not structurally shareable across threads"), and `Slice` is a std
    type (elisacore_std/elisacore_runtime_slice.elisa), so bare mode cannot even name it.
    These are NOT untested overall: test/parity/parallel_for_grant_smoke.sh covers the
    effect-grant and outer-mutation rules, and the std itself uses them, so the self-host
    exercises the codegen. They are simply out of scope for THIS corpus.
  * Anything else requiring a std container/protocol (Slice, MemoryPool, dict/set
    internals) for the same reason.

A zero mention-count for one of those in this file is therefore expected, not a gap to
close here. Prefer the parity smokes for them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adversarial_harness import main

import adv_gen_core
import adv_gen_tables_errors
import adv_gen_containers
import adv_gen_abi_literals
import adv_gen_operators
import adv_gen_widths
import adv_gen_refs_builtins
import adv_gen_patterns
import adv_gen_alternation
import adv_gen_regions_queries
import adv_gen_match_arms
import adv_gen_packed_soa
import adv_gen_soa_rows
import adv_gen_expect_views
import adv_gen_bitfields
import adv_gen_errors_dicts
import adv_gen_packed_regions


# The registry, in the order the single-file version accumulated it: the report is sorted by
# name, so order only decides which generator runs first, but keeping it identical keeps a
# `git log -p` of this file readable.
_BY_NAME = {}
for _module in (adv_gen_core, adv_gen_tables_errors, adv_gen_containers, adv_gen_abi_literals, adv_gen_operators, adv_gen_widths, adv_gen_refs_builtins, adv_gen_patterns, adv_gen_alternation, adv_gen_regions_queries, adv_gen_match_arms, adv_gen_packed_soa, adv_gen_soa_rows, adv_gen_expect_views, adv_gen_bitfields, adv_gen_errors_dicts, adv_gen_packed_regions):
    for _generator in _module.GENERATORS:
        _BY_NAME[_generator.__name__] = _generator

GENERATORS = [
    _BY_NAME['gen_overloads'],
    _BY_NAME['gen_generic_mangling'],
    _BY_NAME['gen_externs'],
    _BY_NAME['gen_container_values'],
    _BY_NAME['gen_numeric_edges'],
    _BY_NAME['gen_discard_and_scope'],
    _BY_NAME['gen_structs_enums'],
    _BY_NAME['gen_control_flow'],
    _BY_NAME['gen_refs_optionals'],
    _BY_NAME['gen_casts_arith'],
    _BY_NAME['gen_strings'],
    _BY_NAME['gen_generics_multi'],
    _BY_NAME['gen_match_exhaustive'],
    _BY_NAME['gen_when_tables'],
    _BY_NAME['gen_defer_region'],
    _BY_NAME['gen_error_unions'],
    _BY_NAME['gen_struct_defaults'],
    _BY_NAME['gen_lambdas_closures'],
    _BY_NAME['gen_loops_control'],
    _BY_NAME['gen_optionals_refs'],
    _BY_NAME['gen_ufcs_modules'],
    _BY_NAME['gen_arrays_fixed'],
    _BY_NAME['gen_struct_methods'],
    _BY_NAME['gen_comprehensions'],
    _BY_NAME['gen_casts_widths'],
    _BY_NAME['gen_payload_enums'],
    _BY_NAME['gen_bit_operations'],
    _BY_NAME['gen_generic_structs'],
    _BY_NAME['gen_std_containers'],
    _BY_NAME['gen_defaults_and_named_args'],
    _BY_NAME['gen_multi_assign'],
    _BY_NAME['gen_sview_slicing'],
    _BY_NAME['gen_optional_containers'],
    _BY_NAME['gen_aggregate_abi'],
    _BY_NAME['gen_shorthand_member_is'],
    _BY_NAME['gen_builtin_view_type_name'],
    _BY_NAME['gen_void_return_call'],
    _BY_NAME['gen_copy_array_builtin'],
    _BY_NAME['gen_discarded_darray_growth_methods'],
    _BY_NAME['gen_brace_membership_ranges'],
    _BY_NAME['gen_checked_index_else'],
    _BY_NAME['gen_record_update'],
    _BY_NAME['gen_move_as_destructure'],
    _BY_NAME['gen_float_pointer_cast'],
    _BY_NAME['gen_named_call_argument_order'],
    _BY_NAME['gen_user_enum_named_like_ast_node'],
    _BY_NAME['gen_nested_variant_subpattern'],
    _BY_NAME['gen_loop_where_filter'],
    _BY_NAME['gen_loop_bare_pattern_filter'],
    _BY_NAME['gen_struct_pattern_tests_and_nesting'],
    _BY_NAME['gen_untyped_literal_binding'],
    _BY_NAME['gen_do_block_declaration'],
    _BY_NAME['gen_flat_container_literal_declaration'],
    _BY_NAME['gen_extend_darray_from_view'],
    _BY_NAME['gen_resize_non_scalar_element'],
    _BY_NAME['gen_literal_payload_is_test'],
    _BY_NAME['gen_static_compile_time_call'],
    _BY_NAME['gen_darray_as_cstr'],
    _BY_NAME['gen_is_bracketed_alternation'],
    _BY_NAME['gen_is_grouped_alternation'],
    _BY_NAME['gen_extern_error_return_not_an_export'],
    _BY_NAME['gen_unified_else_recovery'],
    _BY_NAME['gen_get_else_raise'],
    _BY_NAME['gen_nullable_extern_ref_get'],
    _BY_NAME['gen_labelled_call_through_fn_alias'],
    _BY_NAME['gen_shadowing_assignment_declaration'],
    _BY_NAME['gen_proof_block_erasure'],
    _BY_NAME['gen_first_query'],
    _BY_NAME['gen_refined_type_alias'],
    _BY_NAME['gen_builtin_string_surface'],
    _BY_NAME['gen_fixed_array_slice_to_view'],
    _BY_NAME['gen_view_iteration'],
    _BY_NAME['gen_function_value_erasure_cast'],
    _BY_NAME['gen_fixed_array_slice_shapes'],
    _BY_NAME['gen_rev_iteration'],
    _BY_NAME['gen_region_qualifier_pin'],
    _BY_NAME['gen_arena_local_region_pin'],
    _BY_NAME['gen_enum_variant_view_after_is'],
    _BY_NAME['gen_bare_variant_loop_filter'],
    _BY_NAME['gen_loop_pattern_filter_guard'],
    _BY_NAME['gen_catch_per_variant_arms'],
    _BY_NAME['gen_each_collection_query'],
    _BY_NAME['gen_first_projection_query'],
    _BY_NAME['gen_query_guarded_pattern_filter'],
    _BY_NAME['gen_each_guarded_pattern_filter'],
    _BY_NAME['gen_projection_query_bare_pattern'],
    _BY_NAME['gen_optional_match_null_arm'],
    _BY_NAME['gen_nested_variant_match_arm'],
    _BY_NAME['gen_labelled_payload_match_arm'],
    _BY_NAME['gen_membership_range_enum_bounds'],
    _BY_NAME['gen_wide_payload_enum'],
    _BY_NAME['gen_struct_pattern_match_arm'],
    _BY_NAME['gen_user_packed_enum_store'],
    _BY_NAME['gen_packed_match_default_profile'],
    _BY_NAME['gen_packed_match_in_store_clause'],
    _BY_NAME['gen_packed_multi_field_payload'],
    _BY_NAME['gen_packed_common_field_read'],
    _BY_NAME['gen_packed_common_field_read_aos'],
    _BY_NAME['gen_packed_labelled_single_payload_match'],
    _BY_NAME['gen_packed_recursive_eval'],
    _BY_NAME['gen_typestate_struct_qualifier'],
    _BY_NAME['gen_darray_literal_spread'],
    _BY_NAME['gen_enum_variant_alias_after_is'],
    _BY_NAME['gen_projection_query_explicit_owner'],
    _BY_NAME['gen_soa_layout_columns'],
    _BY_NAME['gen_soa_row_api'],
    _BY_NAME['gen_soa_row_handles'],
    _BY_NAME['gen_soa_row_iteration'],
    _BY_NAME['gen_soa_row_iteration_wrappers'],
    _BY_NAME['gen_soa_row_view_binding'],
    _BY_NAME['gen_soa_row_destructured_loop'],
    _BY_NAME['gen_soa_row_let_destructure'],
    _BY_NAME['gen_packed_in_store_is_test'],
    _BY_NAME['gen_packed_is_payload_handle'],
    _BY_NAME['gen_packed_guarded_store_stays_active'],
    _BY_NAME['gen_enumerate_over_fixed_array'],
    _BY_NAME['gen_destructured_struct_loop_head'],
    _BY_NAME['gen_view_slice_offsets'],
    _BY_NAME['gen_with_arena_scoped_allocator'],
    _BY_NAME['gen_proof_carrying_view_helpers'],
    _BY_NAME['gen_derived_state_is_test'],
    _BY_NAME['gen_reduce_sum_over_view'],
    _BY_NAME['gen_zip_map_over_views'],
    _BY_NAME['gen_bitset_named_flags'],
    _BY_NAME['gen_bitfield_member_widths'],
    _BY_NAME['gen_bitfield_pack_width'],
    _BY_NAME['gen_packed_new_store_selector'],
    _BY_NAME['gen_renamed_struct_destructure'],
    _BY_NAME['gen_guarded_projection_query'],
    _BY_NAME['gen_multi_binder_enumerate_query'],
    _BY_NAME['gen_expect_statement'],
    _BY_NAME['gen_expect_struct_shape'],
    _BY_NAME['gen_expect_list_rest_shape'],
    _BY_NAME['gen_struct_payload_beside_scalar'],
    _BY_NAME['gen_array_payload_field'],
    _BY_NAME['gen_expect_variant_payload_shape'],
    _BY_NAME['gen_packed_nested_payload_decode'],
    _BY_NAME['gen_static_protocol_dispatch'],
    _BY_NAME['gen_index_profile_statement_match'],
    _BY_NAME['gen_return_type_generic_inference'],
    _BY_NAME['gen_shorthand_member_argument'],
    _BY_NAME['gen_flags_bit_test_index'],
    _BY_NAME['gen_index_returned_darray'],
    _BY_NAME['gen_view_over_borrowed_darray'],
    _BY_NAME['gen_slice_of_temporary'],
    _BY_NAME['gen_view_field_element_read'],
    _BY_NAME['gen_try_as_binary_operand'],
    _BY_NAME['gen_const_dict_table'],
    _BY_NAME['gen_subbyte_enum_bitfield'],
    _BY_NAME['gen_unannotated_comprehension_decl'],
    _BY_NAME['gen_signedness'],
    _BY_NAME['gen_string_escapes'],
    _BY_NAME['gen_const_enum_values'],
    _BY_NAME['gen_type_mismatches'],
    _BY_NAME['gen_queries'],
    _BY_NAME['gen_as_bindings'],
    _BY_NAME['gen_struct_operator_protocols'],
    _BY_NAME['gen_named_tuples'],
    _BY_NAME['gen_ref_returning_call_deref'],
    _BY_NAME['gen_struct_compound_assign_declines'],
    _BY_NAME['gen_index_compound_assign'],
    _BY_NAME['gen_darray_of_fixed_array'],
    _BY_NAME['gen_pin_and_range_match_arms'],
    _BY_NAME['gen_value_match_pin_and_range'],
    _BY_NAME['gen_borrowed_fixed_array_chain'],
    _BY_NAME['gen_borrowed_fixed_array_mixed_width_read'],
    _BY_NAME['gen_floats'],
    _BY_NAME['gen_lmut_place_required'],
    _BY_NAME['gen_flags_const_enum_sview'],
    _BY_NAME['gen_char_literal_never_fits_sview'],
    _BY_NAME['gen_clone_builtin_move_wrapped_source'],
    _BY_NAME['gen_range_match_value_slot'],
    _BY_NAME['gen_i16_u16_widths'],
    _BY_NAME['gen_shifts_bitwise_and_size_types'],
    _BY_NAME['gen_mutable_ref_local_rebind'],
    _BY_NAME['gen_generic_operator_no_bound'],
    _BY_NAME['gen_packed_forward_declared_payload_enum'],
    _BY_NAME['gen_packed_index_profile_commons'],
    _BY_NAME['gen_named_args_through_fn_field_alias'],
    _BY_NAME['gen_payload_carrying_error_set'],
    _BY_NAME['gen_try_as_right_binary_operand'],
    _BY_NAME['gen_linear_consume_marker_is_a_pointer'],
    _BY_NAME['gen_catch_arm_that_returns'],
    _BY_NAME['gen_dict_entry_api'],
    _BY_NAME['gen_payload_enum_labelled_fields'],
    _BY_NAME['gen_packed_is_variant_sparse_profile'],
    _BY_NAME['gen_packed_multi_field_word_packing'],
    _BY_NAME['gen_packed_store_ordinal_index'],
    _BY_NAME['gen_region_new_allocation'],
    _BY_NAME['gen_nested_or_pattern_binding'],
    _BY_NAME['gen_monomorphized_ref_arithmetic'],
    _BY_NAME['gen_ref_to_ref_indexing'],
]


if __name__ == "__main__":
    sys.exit(main(GENERATORS))
