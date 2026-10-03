# Fuzz findings, round 1 (2026-10-03, stage0 a5be463e, stage1 50df0c9a)

Repros are in `repros/`. stage0's verdict counts as a rejection if it rejects under `-Wstrict`. Execution checks run only stage1 products (built on Linux, at -O0 and -O2, with `guard.so`). Fixture rule: add a pad allocation after the owner, because the tail of an arena grows in place and hides stale reads.

## S1: confirmed by execution
| ID | Repro | stage0 | stage1 | Owner |
|---|---|---|---|---|
| F1 | esc_return_struct_field_view (+ esc_return_local_view_control) | accept | accept | both-escape agent |
| F2 | setter_store_through_local_view | accept | accept | both-escape agent |
| F3 | callarg_mutref_and_view_overlap | accept | accept | both-escape agent |
| F4 | region_store_field_view_escape | reject | accept | s1-holes agent |
| F5 | slice_tuple_owner_reassign | reject | accept | s1-holes agent |
| F6 | lmut_rebind_{ref,view}_held_across_growth | reject | accept | s1-holes agent |
| F7 | fstring_bound_to_sview (segfault) | reject | accept | s1-type/scope agent |
| F8 | fwd_condition_extern_cstr_arg_unchecked (segfault) | reject | accept | s1-type/scope agent |

## S2: unsafe program accepted
| ID | Repro | stage0 / stage1 | Owner |
|---|---|---|---|
| F9 | region_block_local_used_after_block (scope leak) | reject / accept | s1-type/scope agent |
| F10 | aff_match_arm_move_then_move | reject / accept | affine agent |
| F11 | aff_ternary_move_then_use | reject / accept | affine agent |
| F12 | aff_closure_move_called_twice | accept / accept | affine agent |
| F13 | clear_during_drain | reject / accept | affine agent |
| F14 | lmut_field_grow_in_region_block | reject / accept | s1-holes agent |
| F15 | duplicate_region_statement_accepted | reject / accept | s1-type/scope agent |
| F16 | drain_with_live_ref | accept / accept | affine agent |
| F17 | s0hole_loop_carried_view, ref_identity_helper_loop_grow, ref_generic_identity_grow, s0hole_break_path_grow | stage0 misses | stage0-holes agent |

## S3: crashes and divergences
- F18: stage1 SIGSEGV on valid programs, crash_struct_ref_field_into_field_darray and crash_ref_darray_index_arith. Owner: the IR-crash agent.
- F19: stage0 panic in s0_panic_machine_arm_chain (machine.go:1194). Owner: stage0-holes agent.
- F20 (no safety impact):
  - ref_alias_chain_grow_param: stage0 is over-strict.
  - slice_struct_clear_stale: OK.
  - Dead code after `return` is not type-checked by stage1.
  - stage0 LLVM error on `global mutable gk: sview = ""`.
- Untriaged: about 220 stage0-accept/stage1-reject rows, plus parse-level forms that stage1 accepts.

Tools: `pull.sh run2`, `triage.py`, `v.sh -x`, `m.sh`. To stop: `kill $(cat /root/fuzz/run2.pid)` on each box.
