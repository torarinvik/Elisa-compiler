# stage1 compile-speed tracking

Targets (stage1 compiling itself, `src/driver/elisac.elisa`, ~253k lines after includes):

| workload | target |
|---|---|
| `-emit check` (lex + parse + full semantic gate, no codegen) | <= ~2 s (>= 100k lines/s) |
| `-emit obj -O0`, parallel emit | <= ~20 s |
| `-emit obj -O2` | no quadratic frontend; frontend small next to LLVM optimisation |
| small file (`test/fixtures/captured_loop_ternary_neighbors.elisa`, `-O0`) | ~0.02 s |
| `test/parity/preserves_filter_smoke.elisa`, `effect_law_filter_smoke.elisa` (`-O0`) | seconds |

Generated-code quality is never traded for compile speed.

## Method

- Machine: the 64-core Linux gate box (x86_64, LLVM 21); load average recorded per run.
  Never time on the Mac (it is shared and overloaded).
- `ELISA_STAGE1_TIMINGS=1` prints `stage1-timing: PHASE wall_ms=W cpu_ms=C` rows on stderr:
  read/includes, lex, parse, static-generate, each semantic pass that took >= 20 ms (the
  rest summed as "short passes"), LLVM IR generation, verify, optimise, object emission,
  link. Unset, a mark is one global load and a branch.
- `-emit check` stops after the semantic gate.
- `ELISA_STAGE1_JOBS=32` for object builds (parallel per-function-partition emission).
- Script: run each workload once, serially, with `ulimit -s unlimited`,
  `ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1`.
- Profiling: ptrace attach is blocked on the box; `valgrind --tool=callgrind` works, and so
  does launching under gdb and interrupting with SIGINT. A stage1 binary built by stage1 with
  `ELISA_STAGE1_JOBS>1` keeps its internal functions as `elisa.part.*` symbols, so it
  symbolizes; the stage0 seed does not.

## Results (wall seconds)

| commit | check | -O0 | -O2 | small | preserves smoke | effect_law smoke | load |
|---|---|---|---|---|---|---|---|
| 8648f223 (baseline + timings), stage0 seed | 857.9 | - | - | - | 315 (idle box, reported) | 1182 (idle box, reported) | ~10 |
| 42aedbe6 (indexed scans), stage0 seed | 27.6 | - | - | - | - | - | ~7 |
| + sorted view-origin rows, stage1-built | 23.8 | 41.5 | 137.3 | 0.06 | 21.2 | 21.4 | 4-10 |
| + region-annotation windows, owned-candidate chains | 22.9 | - | - | - | - | - | ~8 |
| + ref_pos offset chains | 21.3 | 44.2 | 135.9 | 0.055 | 20.9 | 21.3 | ~8 |
| + field/declared-name/generic-instance/scope-owner indexes | 20.4 | 36.8 | 134.1 | 0.058 | 19.4 | 19.5 | 5-20 |

Box timings are noisy (other agents share it): the same `-emit ast` run measured 66 s and
10 s minutes apart. Compare rows only by phase CPU times when the difference is small.

## Where the time goes now (last row)

- `-emit check` 20.4 s: ~400 semantic passes, each walking the whole AST; no single pass
  above 1.6 s (region_storage_stability 1.5, borrow_after_move ~1.0, resolve_declarations
  0.9, destroyed_region 0.55, call_holder_view_store 0.54). The remaining gap to 2 s is
  structural (pass count x AST walks, `ctx_aos_store_record` AST reads ~6% of
  instructions), not one quadratic loop: it needs fused walks / shared facts.
- `-O0` 36.8 s: frontend ~20, LLVM IR generation 9.2 (const/struct/enum/generic
  `*_index_of` linear lookups are the next visible items), verify 0.8, emit ~5.
- `-O2` 134 s: LLVM's module O2 pipeline is 93 s, single-threaded. Splitting it per
  partition would change inlining across partitions, i.e. generated code, so it is not
  done.
- `-emit ast` on a unit that includes the semantic layer takes ~10 s: a separate
  quadratic in the AST printer (`emit_ast_decl`), not yet addressed.

Phase detail at the last row (-O2): parse 1.2, lex 0.33, semantic ~19 (largest passes:
region_storage_stability 3.0, destroyed_region 1.0, borrow_after_move 1.0,
resolve_declarations 0.9), LLVM IR generation 9.9, verify 0.8, LLVM -O2 pipeline 92.7,
object emission 9.7.

Baseline hot spots (check, before 42aedbe6): check_destroyed_region 758.9 s,
resolve_declarations 56.1 s, check_fn_value_effect_row 16.1 s,
check_region_storage_stability 6.6 s.
