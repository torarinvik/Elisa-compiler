# Fuzz findings, round 1 (2026-10-03, stage0 a5be463e, stage1 50df0c9a)

Repros are in `repros/`. stage0's verdict counts as a rejection if it rejects under `-Wstrict`. Execution checks run only stage1 products (built on Linux, at -O0 and -O2, with `guard.so`). Fixture rule: add a pad allocation after the owner, because the tail of an arena grows in place and hides stale reads.

## S1: confirmed by execution
| ID | Repro | stage0 | stage1 | Owner |
|---|---|---|---|---|
| F1 | esc_return_struct_field_view (+ esc_return_local_view_control) | accept | reject (2026-10-04, droots fixpoint) | stage0 still open |
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

## Fixed in stage1 (branch claude/fuzz-stage1-holes-2vuytr)
Every repro below is now rejected by stage1 with stage0's diagnostic. Each one is kept as a
`fuzz_f*.pos.elisa` fixture in `test/fixtures/diagnostics/` (should fire), next to a
`.neg.elisa` control (should stay silent).

| ID | Cause in stage1 | Fix |
|---|---|---|
| F4 | A struct built around a fresh container literal inside a region block was not tainted with that region | `check_region_escape`: taint it (non-empty literals only; an empty one allocates nothing) |
| F5 | A view held in a tuple literal field was not recorded as a view alias | `check_region_storage_stability`: a tuple/struct literal with a field that is directly a view now aliases that view's sources |
| F6 | `rebind n, p = lgrow(p)` lowers to `[n, p] = call`; replacement invalidation only handled a bare `Ident` target | Invalidate views of each rebind target |
| F7 | `y: sview = f"…"` was accepted | `resolve_types_infer`: an f-string (`darray[u8]`) can't initialise an `sview` |
| F8 | Argument typing fell back to file-wide local TypeIds still holding the *last* function resolved | `check_firm_arg_type_mismatch`: rebuild the table per function |
| F9 | Locals of a `region r(cap):` block stayed in scope after it | `resolve_flow`: a region block with a body is a scope |
| F10, F11 | The affine walk had no ternary or match-expression arm | Branch-wise walk, then join (a move in any branch consumes) |
| F13 | `clear`/`truncate`/`reserve` weren't relocating mutations for the iterated container, and a drain's `move xs` iterable had no place | Add them, and look through `move` |
| F14 | A growth inside a captured loop with a yield was never walked, and every parameter was exempt from the nested-growth rule | Walk the captured block, and drop the parameter exemption (current stage0 rejects `mutable darray&` too) |
| F15 | The statement form `region r(cap)` was not checked for duplicates | `resolve_mutability`: check it ("already defined as region") |

Check: across all diagnostic fixtures, counts match stock stage1 apart from the new fuzz files,
and stage1 still compiles itself.

# Generative runtime differential, round 2 (2026-10-04, tools/fuzz/difffuzz.py)

Valid programs from `tools/fuzz/gen_progs.py`, built by stage0 and by stage1 at -O0 and -O2
and RUN; output and exit code compared. ~9,000 programs on a Linux host.

Fixed on branch claude/difffuzz-20261004 (fixtures live with the fix):
- const enum member values other than a bare literal (`B = -3`, `D = 1 << 4`) took the running
  ordinal in stage1 -- every early MISMATCH. Fixture: adversarial `const_enum_folded_values`.
- `rows[i].f <- v` on an immutable field was checked only in the last function of a file
  (stale structural local-type channel). Fixture: diagnostics `field_immutable_assign_indexed`.
- darray `.count` and a `count` query were signed i64 in stage1, usize in stage0 (docs/18), so
  `xs.count - 3 <= 0` compared differently. Fixture: adversarial `usize_count_compares_unsigned`.

Open (repros here):
| Repro | stage0 | stage1 | class |
|---|---|---|---|
| fn_value_effect_row_ignored(_arg) | reject (effect row) | accept, runs | PERMISSIVE: no effect rows on fn values |
| query_same_line_binder_head_collision | 21 | declines | loud decline, known limit of the line-keyed __query table |
