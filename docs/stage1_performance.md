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
| backend round (claude/s1-perf-be, 43990782), stage1-built | 21.1 | 30.2 | 138.7 | 0.030 | 16.4 | 16.3 | 8-13 |
| claude/s1-perf-fe: + AST-printer views (`-emit ast` self 20.5 -> 2.1 s) | 20.8 | - | - | - | - | - | ~6 |
| + incremental param-growth fixpoint, store-through chains | 20.4 | - | - | - | - | - | 13-24 |
| + private-field / destroyed-alias chains | 20.0 | - | - | - | - | - | 13-24 |

The last two rows were measured in one run on a loaded box, next to 0317f89f's compiler at
24.8 s; per-pass CPU (ms): region_storage_stability 1566 -> 1306, call_holder_view_store
587 -> 274, private_fields 311 -> 159.

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
- `-emit ast` (self) is 2.1 s, of which read+lex+parse is 1.8 s. It was 20 s: a per-param
  scan to the end of the token stream (`emit_ast_param_grown_in_body`) and per-declaration
  scans of the whole enum-annotation table, now one set of sorted/filtered views
  (`src/driver/elisac_emit_ast_marks.elisa`).

### Parallel semantic checking (measured, not committed)

A fork-based scheduler was built and verified on the self unit (diagnostics byte-identical
to the serial run): a call-closure scan of the semantic sources classified 345 of the ~410
pipeline passes as diagnostic-only (write no table field but `diagnostics`, read no
diagnostics); runs of them between other passes went to forked children (a leader per run
that forks its lanes, lanes balanced on measured pass cost), findings spliced back in pass
order. On the gate box it gave only 20-22 s -> 17-19 s: the ~45 non-pure passes stay on the
parent (~8 s), each fork of the compiler-sized process costs the forking process ~45 ms
under the box's gVisor kernel, and every fork re-shares the parent's pages so its writer
passes run ~1.5x slower on copy-on-write faults. Worth revisiting once the writer passes are
cheaper, or on a host with ordinary fork costs.

Phase detail at the last row (-O2): parse 1.2, lex 0.33, semantic ~19 (largest passes:
region_storage_stability 3.0, destroyed_region 1.0, borrow_after_move 1.0,
resolve_declarations 0.9), LLVM IR generation 9.9, verify 0.8, LLVM -O2 pipeline 92.7,
object emission 9.7.

Baseline hot spots (check, before 42aedbe6): check_destroyed_region 758.9 s,
resolve_declarations 56.1 s, check_fn_value_effect_row 16.1 s,
check_region_storage_stability 6.6 s.

## Backend round (claude/s1-perf-be)

Measured against the round-1 compiler on the same tree (`-emit obj`, 32 emit jobs):

| phase (self-host unit) | before | after |
|---|---|---|
| LLVM IR generation | 9.2 s | 5.6-5.8 s |
| verify | 0.8 s (critical path) | overlapped with -O0 emission |
| -O0 object emission (wall) | ~5 s + 0.8 s verify | 3.4-3.7 s |
| -O2 object emission (wall) | 9.7 s | 7.8 s |
| small file | 0.058 s | 0.030 s (0.015 s with LLVM linked statically, below) |

What changed, by commit:

- 5889320e: the include line map (`ELISA_STAGE1_LINE_MAP`) is parsed once per environment
  string, not per `source_original_line` call; it is hidden from `system` children (the
  self-host map is >128 KB, one exec string's limit, so `ld -r` for parallel emission and
  `-emit exe` links failed with E2BIG from long tree paths); parallel emission forks at most
  one worker per 20000 instructions (a 30-line file spent 26 of 50 ms forking 32 workers).
- 2a2c93df, db32e19e, 43990782: hash chains (`codegen_name_chains.elisa`,
  `codegen_annotation_pair_index.elisa`) for const/struct/enum/generic-template name lookups,
  region-fact and local-binding line lookups, and (owner, name) annotation questions;
  packed row widths memoized under a layout stamp; generic-instance chain heads indexed by
  struct slot; LLVM value names discarded for object/exe output (`setName` was 8%).
- 666677ed, c795e4c5: emission workers are forked as a tree (32 sequential forks of a 2 GB
  process cost ~2 s); at -O0 other partitions' functions become available_externally
  instead of having their bodies erased (erasing dirtied every copy-on-write page in every
  worker); at -O2 they are still erased (an optimising machine runs IR codegen passes over
  available_externally bodies). The verifier runs in the parent during -O0 emission. Main
  no longer disposes the module before exiting.

Objects are byte-identical through all of it (self-host -O0 and -O2, 32 jobs), and the
stage1 binary is a fixpoint. The only visible output change: a verifier diagnostic for
invalid backend IR in an object build prints numbered values instead of names.

### Remaining, measured

- IR generation (callgrind, 19.2 G instructions after this round, from 29.0 G): diffuse.
  `ctx_aos_store_record` (AST store reads, 9.5%), `emit_module_bodies` self time (6.6%),
  `register_module_types`/`register_enums_from_metadata` (3.4/3.3%), `declare_function`
  (3.6%), region forwarding scans (~7%), ~1.5% `getenv` from per-call option probes
  (`darray_llvm_type`, `scalar_type_of_name`, ...). Parallelising IR generation per
  partition is not feasible with the current shared, mutating `StructTable`.
- -O2: LLVM's `default<O2>` is 93-100 s single-threaded on 2.03M instructions / 9350
  functions. `opt -time-passes` on the module: InstCombine 20%, Inliner 7.6%, SimplifyCFG
  7.1%, GVN 7.0%, SROA 5.7%, JumpThreading 5.3%, then a long tail; analyses (MemorySSA,
  DomTree, Loop) ~8 s. No pass is pathological and the IR has no obviously wasteful shape
  (470k loads, 346k stores, 185k allocas, 14k `llvm.trap` blocks from checks). Cutting it
  materially needs parallel optimisation (ThinLTO-style per-partition pipelines with
  imported callee bodies), which changes inlining and so must be proven at runtime parity
  first; not done.
- Small file: 0.030 s, of which ~15 ms is loading `libLLVM.so` (relocations and static
  initialisers; an empty C program linked to it takes 17-20 ms). Relinking the same
  object against LLVM's static archives (`llvm-config --link-static --libs core passes
  x86 aarch64 arm riscv webassembly bitwriter bitreader analysis irreader target mc
  support`, `--gc-sections`; on the box `-l:libzstd.so.1` since there is no libzstd.a)
  measured 0.014-0.017 s for the same compile, link 4 s, binary 94 MB unstripped. That is
  a build-script change (seed and gen2 link lines) left for a decision.
