# stage1 compile-speed tracking

Current execution policy: use local compute. All rented Vast instances and their
SSH endpoints below are historical evidence, not available infrastructure. Do not
wait for or reconnect to them. Serialize local seeds and coordinate CPU use.
Mac paired measurements are exploratory only; qualified speed claims require a
controlled host and recorded toolchain.

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

- Historical measurements used the 64-core Linux gate box (x86_64, LLVM 21).
  That host is retired. Record the actual local host and contention for new runs.
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

### Compile-time index scorecard (unmeasured)

Record these costs with the next controlled stage1 compile-speed run before changing the
static cutoffs or making the source-AST owner index lazy:

| index | current build policy | cost to record | follow-up decision |
|---|---|---|---|
| Type-alias name chains | built per pass when there are at least 8 aliases | pass CPU/wall time and peak RSS on small and self-hosting inputs | keep the cutoff only if the lookup savings cover map/chain construction and memory |
| Zeroed bare-alias resolution | reuse the symbol-name chain and binary-search `TypeAliasDeclaration` rows by stable declaration ID | pass CPU/wall time, bare-alias query count, average same-hash chain length, and AST fallback count | retain the lookup if declaration-walk savings outweigh the binary searches; do not add another index until measured |
| Callback-name slots | built on the first callback-result lookup, and only for at least 8 callbacks | pass CPU/wall time and peak RSS with no result lookup, then with repeated result lookups | preserve the lazy path if unused callback indexing has no measurable cost |
| Source-AST aggregate owner chains | one row per named struct/enum declaration; function-local synthetic payloads remain per-expression rows | pass CPU/wall time, peak RSS, and declaration/expression row counts on small and self-hosting inputs | retain declaration handles if reducing repeated member rows offsets AST matching cost; consider lazy owner materialization if unused declarations still make setup expensive |
| Qualified module-scope paths | deduplicated and hash-indexed on the first qualified-scope lookup | pass CPU/wall time, peak RSS, unique module-path count, and qualified-scope lookup count | retain the index only if repeated path scans saved more time than index construction costs |
| Symbol-name bucket counts | maintained while building the general symbol-name chains | full self-host compile CPU/wall time and peak RSS | retain the completeness check if its table-build and memory cost is reasonable |
| Active enum payload discovery | lazily builds exact `(owner, name)` hash chains on the first zeroed aggregate type query; rows contain only the first (zero-tag) variant's payload expressions | pass CPU/wall time, index-build cost, payload-row count, and active-payload queries on enum-heavy inputs and inputs without an invalid zeroed/omitted initializer | preserve declaration order across duplicate enum fragments, module/scope lookup, and first-variant-only semantics; compare eager scan and lazy index before keeping |
| Backend submit-presence scans | lazily open-addressed per-function memo for nested statement lists | codegen CPU/wall time and memo allocations on nested-submit inputs, plus flat functions in files that contain submit annotations | keep only if saved subtree walks outweigh hashing and table growth costs |
| Region-forwarding named-call mapping | compute source-argument positions and the callee fact row once per named call | callgrind/helper counts and temporary allocations for named, positional, duplicate, unknown, and receiver calls; stage1 IR-generation CPU | keep only if repeated mapping work saved exceeds per-call map construction; preserve partial mappings before an invalid argument |
| Mutable-global name chains | build after 32 rows, then extend on each append; small registries keep the linear path | codegen CPU/wall time, mutable-global lookup counts, peak RSS, and bucket allocations on small and self-hosting inputs | keep the cutoff/index only if lookup savings cover the fixed bucket allocation; preserve owner priority and declaration-order fallback |
| Packed-enum name chains | build after 32 rows, then extend on each placeholder/final-row append; smaller registries keep the linear path | codegen CPU/wall time, packed-enum lookup counts, candidate rows visited, peak RSS, and bucket allocations on self-hosting and enum-heavy inputs | keep only if owner and qualified-scope scan savings cover index costs; preserve owner precedence, ambiguity rules, scope ranking, and source-order ties |
| Packed owner-membership cache | classify each enum declaration and payload row once after building packed-name metadata; reuse flags for placeholder reservation and payload-registration rounds | IR-generation CPU/wall time, `packed_listed_for_owner` calls, annotation rows scanned, and flag-table memory on self-hosting and enum-heavy inputs | keep only if repeated metadata scans saved exceed one-time classification and flag-table costs; preserve module ownership and interface-only fallback |
| Packed variant-path lookup | hash the final enum-name slice, compute the maximum matching scope rank in one candidate pass, then visit tied rows in source order | codegen CPU/wall time, path queries, same-name candidates, and bytes hashed on nested-module and enum-heavy inputs | keep only if narrower candidate walks offset path-slice hashing; preserve qualified owner matching, lexical precedence, variant order, and rank ties |
| Payload-enum name chains | build after payload finalization when there are at least 32 live rows; registration and smaller tables keep the linear path | codegen CPU/wall time, qualified enum lookup counts, peak RSS, and bucket allocations on enum-heavy and self-hosting inputs | keep only if saved owner/rank scans exceed index construction and memory; preserve owner precedence, alias fallback, and declaration-order ties |
| Enum scope ranking | compute the owner/enclosing common prefix once and walk namespace separators backward | codegen CPU/wall time, `enum_scope_path_rank` calls, and bytes examined on nested-module inputs | keep if it reduces repeated prefix scans while preserving nearest-scope rank and first-row ties |
| Const-enum member resolution | resolve dotted paths through the existing enum-name chain and owner ranking; scan the selected variant span once, then read its explicit value from the parallel pool | codegen CPU and variant rows visited on enum-heavy and self-hosting inputs; const-enum field-read, `is`, and path-pattern query counts | preserve module ownership, the distinction between declaration ordinal and explicit member value, and `-1` as a valid value rather than a membership sentinel |
| Annotation alias fallback | skip the legacy global resolver when owner or top-level alias lookup already found a row | codegen CPU/wall time, legacy alias resolver calls, and annotation count on alias-heavy and self-hosting inputs | keep if skipping duplicate lexical scans helps without changing unresolved-alias precedence |
| Function declaration lookup | reuse the source-ordered function-name chain for overload counts and prior extern matching | IR-generation CPU and candidate rows visited versus total function rows on self-hosting and extern-heavy inputs | preserve owner/signature filters and first compatible extern selection; retain if the narrower scans reduce declaration cost |
| Generic declaration body selection | keep the linear membership path below 32 rows, then build collision-safe line chains for generic and errorset declaration lines | codegen CPU, membership query count, indexed row count, and bucket allocation cost on small and self-hosting inputs | preserve the `< GENERIC_BOUND_ROW_START` filter, errorset inclusion, and exact line equality; keep the cutoff only if lookup savings cover chain construction |
| DArray LLVM header | cached per `StructTable`, LLVM context, and target pointer width | codegen CPU/wall time and temporary allocation count on container-heavy inputs | keep if repeated header construction savings exceed the one-time cache and table-field cost |
| String equality callee | cache the native `__elisa_sview_eq` handle in the module's `StructTable`; component modules keep the runtime entry point | IR-generation CPU and helper-name lookup count on string-heavy and self-hosting inputs | preserve `memcmp` linkage fallback and module ownership; keep only if avoided LLVM lookups exceed cache-field overhead |
| Module environment flags | snapshot linkage, noalias-metadata, component-mode, and C ABI target flags once per module, then reuse them in function, access, and export classification | codegen CPU/wall time, environment-read count, and temporary allocation count on function-heavy, darray-heavy, component, and aggregate-export inputs | preserve per-module sampling and WASM → x86-64 → default priority; compare output linkage, alias metadata, and export ABI against the prior policy |

These are open measurement items, not performance claims. The stage1 timing output gives
per-pass CPU and wall time; collect peak RSS on the same host and record input size and
declaration counts alongside it. Do not infer a net win from fewer lookup probes alone.

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

### Unmeasured source changes

- The reclaimed-block fallback in `arena_alloc` is attempted only when the current bump region
  is absent, claimed, or full. A normal bump allocation avoids the atomic owner-tag load and
  cache lock entirely. On a fallback lookup, empty or mismatched hints skip the lock, while
  matching owners still lock and validate the region pointer. The tag stays outside the public
  `Arena` layout and is advisory. A miss can forgo reuse on growable arenas; fixed and
  reserve-commit arenas exhaustively scan their free blocks only after bump
  overflow, so a displaced hint cannot hide reusable capacity and cause a spurious overflow
  panic. The next controlled run should compare self-host check/object CPU and instructions,
  record fast-miss versus hit counts, and use workloads with realistic DArray growth/reclaim
  frequency plus concurrent reclaim, arena free, and address reuse. No speedup is claimed for
  all allocations or yet overall.
- Qualified struct lookup in `struct_index_of` now hashes the final type-name slice into the
  existing struct-name chain, then compares only same-named candidates against the module-path
  prefix. This removes its all-struct scan without allocating a joined path. Include nested
  `A::B::Item`, same-leaf declarations under different owners, and an unindexed registry tail
  in the next controlled backend run; no runtime or compile-time gain is claimed yet.
- Function overload counting and prior-extern matching now traverse the source-ordered
  function-name chain instead of rescanning all earlier declarations; owner, signature, and
  first-compatible-extern rules are unchanged. Compare candidate rows visited and declaration
  CPU on self-hosting and extern-heavy inputs; no compile-time gain is measured yet.
- Packed variant path resolution now hashes the final enum-name slice before the variant dot,
  computes the highest matching scope rank in one candidate pass, then processes tied rows in
  registry order. The existing full path matcher still chooses the lexical or qualified owner.
  Compare path query CPU, name-slice hashing, and candidate rows on nested-module and enum-heavy
  inputs; no compile-time gain is measured yet.
- Const-enum member reads and `is` comparisons now scan the enum's variant span once for the
  ordinal, then use that ordinal to read its explicit value from the parallel pool. Membership
  checks use the ordinal so an explicit value of `-1` remains valid. Compare codegen CPU and
  variant rows visited on enum-heavy and self-hosting inputs; no gain is measured yet.
- Loop back-edge storage diagnostics reuse their probe and result arrays across invalidated
  names. Compare allocation counts and semantic CPU on loop-heavy inputs; no gain is measured
  yet.
- Zeroed aggregate checks now lazily index active enum payload expressions by exact owner and
  name, keeping declaration order and the first variant selected by the zero tag. This avoids
  rescanning the declaration tree and allocating a temporary field array at each repeated type
  query. Record index-build cost and query counts on enum-heavy inputs, and verify that files
  without invalid zeroed or omitted initializers pay no build cost; this change has not been built or
  measured.
- Thread shareability now stores one source `Decl` row per named struct or enum instead of
  duplicating its owner/module/line metadata for every member expression. A queried declaration
  walks its original members in order, while synthetic function-local enum fields remain
  expression rows. Record index size, pass CPU, and peak RSS before making a net-win claim; this
  change has not been built or measured.
- Mode-2 AoS record reads bypass the generic `ctx_aos_store_record` call when the active store
  and ABI are known. Sized AST stores load the per-record address slot; optimized fixed-row
  stores use the stored stride, avoiding the generic reader's sized/fixed dispatch. Both paths
  retain the chunk-count trap and require the supported 64-bit pointer/word alignment plus
  pointer/i64 operands. Unknown layouts and operands fall back to the runtime reader, as do
  fixed-row reads in unoptimized builds. Compare optimized self-host object runtime and
  instructions, plus compile-time codegen cost and parity for compiler AST and fixed-store
  workloads; these direct-reader changes have not been built or measured.

## Round 4 (claude/s1-perf-r4: 0cdb5c72, bd9fdb13, 341f72ba, ddbc803d)

Measured in one QUIET window on the gate box, 64 emit jobs, same input tree (main at
8006b660), each compiler stage1-built. `check` is the median of three runs.

| measure (self-host unit) | 8006b660 | ddbc803d |
|---|---|---|
| callgrind, `-emit check` (instructions) | 49.08 G | 44.07 G (-10.2%) |
| `-emit check` wall | 19.5 s | 18.3 s |
| semantic CPU (sum of passes) | 17.1 s | 16.1 s |
| read+includes / lex / parse CPU | 0.24 / 0.33 / 1.22 s | 0.17 / 0.24 / 1.15 s |
| `-O0` object wall | 34.1 s | 30.6 s |
| `-O2` object wall (LLVM optimise) | 160 s (108 s) | 143 s (97 s) |
| small file `-O0` | 0.024-0.039 s | 0.027-0.036 s |

What changed:

- `view_return_origin_rows` (an up-to-8-round whole-AST fixpoint) runs once per unit and is
  lent to both passes that used it (~0.63 G).
- Hash chains for scans callgrind still showed: enum-variant owners (`bare_enum_module`,
  0.49 G), function effect owners/sources (`function_has_effect`, the global-permissions
  dedup probe), generic-parameter names (`is_protocol_constraint_name`). Every chain falls
  back to the old scan when it is not current.
- `binding_import_module_owner` no longer allocates per call (its region teardown memset was
  0.75 G); length/first-byte rejects before string compares in `type_of_name`,
  `is_integer_type_name`, `is_lambda_keyword`, and the lexer's keyword table split by length
  (~50 compares per identifier before).
- Optimised builds give the runtime's `ctx_aos_store_record` an available_externally body
  (the runtime's own code, 64-bit layout, trap on a bad chunk) so LLVM inlines every
  packed-AST read; the linked definition stays authoritative and -O0 output is unchanged.
  This changes -O2 code of every program that reads packed ASTs (fewer calls only);
  differential_corpus is unchanged against main (same mismatch, same declines once the
  load-dependent easm_* skips are accounted for).
- `read_file` and `expand_includes` copy blocks instead of pushing bytes.

Wall time moved less than instructions (memory-bound walks). What remains, measured:

- Fusing the lint walks: the 108 `loop_view.top_decls` passes under 60 ms sum to ~1.5 s of
  the semantic CPU on a loaded box (~5%), and fusion saves only their walk overhead, not their
  checks. The expensive passes are the stateful ones (region storage, view provenance's
  6-round fixpoint, borrow-after-move, resolve), and those are not fusable without merging
  their state machines. Diagnostics are emitted in pass order (no sort), so a fused walk needs
  per-check buffers spliced back at each pass's position and per-check coverage masks
  (lambda descent, GetElse, contract skipping differ across the 152 walkers). Estimated gain
  under 1 s; not done.
- Parallel per-function checking: needs a per-thread arena and diagnostic buffer, and
  read-only sharing of `SymbolTable` after collection. ~45 passes write table fields during
  the walk (indexes, memo dicts, `local_type_*` scopes, `text_storage`), so each would have to
  be split into a collect phase and a pure check phase first. A multi-week refactor; not
  started.
- -O2: LLVM's single-threaded module pipeline is still ~97 s of 143 s. Splitting it per
  partition changes inlining and so needs runtime-parity proof first; not done this round.
- Remaining callgrind hot spots: AST-walk self time in the stateful passes
  (`lmut_mutation_check_statements`, `check_pointer_erasure_*`, `precondition_multiparam_walk`,
  ~0.3-0.4 G each, inlined so not attributable further without debug info), the arena
  allocator (`arena_alloc`/`arena_free`/`darray_grow`, ~1.6 G), and dict probes behind
  `function_param_chain_head` / `symbol_chain_head` (~0.7 G each; ~350 instructions a call,
  mostly name hashing and linear probing).

## Round 5 (claude/perf-r5)

Measured in one QUIET window on the gate box (load ~1.3), three rotated runs each, same
input tree (main at 40914111), each compiler built by the shared seed at -O2, 64 emit jobs.

| measure (self-host unit) | 40914111 | perf-r5 |
|---|---|---|
| `-emit check` wall (3 runs) | 18.5 / 18.7 / 18.9 s | 17.6 / 18.1 / 18.4 s |
| semantic CPU (sum of passes) | 16.8 s | 15.8-16.6 s |
| `-emit ast` / `-emit tokens` wall | 1.86-1.93 / 0.80-0.82 s | 1.85-1.90 / 0.83-0.85 s (unchanged) |

### Where the misses are (cachegrind, `--cache-sim=yes`, `-emit check`, 40914111)

47.7 G instructions, 12.3 G data reads, 1.08 G D1 read misses (8.8%), 274 M LL read misses
(2.2%; the simulated LL is the box's 40 MB L3 per socket). Two different kinds:

- **AST streaming.** The packed AST store is one array of fixed 148-byte records (the size of
  the largest variant, `Decl.Func`: name, four darrays, return type, Pos), far larger than
  L3. Every whole-AST walker shows ~1.03 M LL misses (one stream of the AST per pass; ~150
  walkers ~ 150 M of the 274 M). Cutting this needs a denser node layout (per-variant size
  classes, or `Pos`/darray headers moved to side tables) -- a codegen change for the sealed
  compiler AST and every `Decl.Func(...)` match site, or fewer walks (fusion). Not done.
- **Side-table rescans.** Passes that scan the whole `enum_annotations` table, `top_decls`,
  `table.symbols` or the diagnostics per declaration/call/statement: L1 misses that hit L2/L3
  (high D1mr, few LL misses). These were fixed this round; every replacement visits exactly
  the rows the scan matched, in the same order:

| pass | was | now | pass CPU (loaded box) |
|---|---|---|---|
| check_append_only_store | annotation scan per struct | owner NameSet | 955 -> 119 ms |
| check_protocol_variance | 4 annotation scans per impl method | prefiltered rows | 577 -> <20 ms |
| check_uninitialized_zeroed | nested protocol_annotations scans per alias path | `SymbolTable.using_alias_rows` | 421 -> 112 ms |
| check_thread_shareability | annotation scan per empty block | `__submit` rows only | 287 -> 93 ms |
| check_destroyed_region | quadratic function-name dedup | NameSet | 658 -> 546 ms |
| check_contract_wellformed, check_impl_conformance, check_region_param_ref_field, lmut rebind-claim / mutation passes, check_handler_capture_escape, check_call_of_invalid, check_poisoned_operand, enum value wall, qualified module names | per-site scans | owner/line chains, NameSets, line windows, skip when no poisoning diagnostic | |

On a quiet box the gain is smaller than the loaded-box pass CPU suggests (~0.6 s, 3-4%):
the rescans were L2/L3 hits, cheap when the box is idle and expensive when other jobs evict
the caches. What remains of `-emit check` is the AST streaming above plus the stateful
passes (region_storage_stability ~2 s, resolve 0.9 s, borrow_after_move 0.7 s).

### -O2 parallel optimisation (measured, not committed)

Prototype with LLVM's own tools on the self-host module (`-emit bc -O0`, internal symbols
externalized as hidden `elisa.part.*` first, as the partitioner does):

| pipeline | optimise + codegen wall (loaded box) |
|---|---|
| `opt default<O2>` + `llc -O2`, one module | 160 + 95 s |
| `llvm-split -j32` + 32x `thinlto-pre-link<O2>` + lld ThinLTO (`--thinlto-jobs=32`) | 24 + 6 + 54 s |

Runtime of the resulting compilers (QUIET, 3 rotated runs, same bitcode, neither has the
`ctx_aos_store_record` inline body): ThinLTO vs full-module O2 is +0.4-1.8% on `-emit check`,
+2.5% on `-emit ast`, +3-4% on `-emit tokens`. That is real ThinLTO (summaries, importing,
whole-program internalization at the executable link); an in-process per-partition pipeline
that cannot internalize across the object boundary would only be worse. Parity fails, so
nothing is defaulted. At -O0/-O1 there is little optimisation to split. The useful shape, if
taken further: emit ThinLTO bitcode partitions from the existing fork tree and let the final
link run the backends (the executable link is where internalization is legal); this changes
the product from an object to a link step and would need the same parity proof.

### Parallel per-function checking: inventory and plan

408 `PhaseTimer::minor("sem:...")` passes in `src/semantic/semantic_api.elisa`. Apart from
the setup steps (symbol collection, hash indexes, metadata copies), only ~25 passes write a
SymbolTable field other than `diagnostics` during their walk:

- producers later passes read: resolve_declarations (`ref_*`, `definition_references`,
  `binding_moves`, `binding_declared_types`, transition candidates), record_protocol_ownership,
  check_global_permissions / check_abstract_effects / check_ungranted_panic (effect rows),
  check_redundant_cast (`ref_reinterpret_lines`), check_pointer_erasure_cast (unsafe rows),
  region_storage_stability (`param_growth_rows`);
- private memo/indexes: check_fn_value_effect_row (`fver_*`), check_readonly_refs,
  check_private_fields, check_firm_arg_type_mismatch (`firm_extern_*`), the region-storage
  segment/candidate/ref_pos chains, check_tuple_var_scalar_mismatch;
- per-function scratch: `local_type_*` scopes, `current_module` save/restore (about ten passes,
  e.g. borrow_after_move, region_escape, construct_field_type), `text_storage` for type-path
  text, `walk_depth`, `current_function_*`.

The hot passes destroyed_region, append_only_store, view_provenance,
call_argument_exclusivity, protocol_variance, contract_wellformed, uninitialized_zeroed and
call_holder_view_store already write only diagnostics.

Tried this round and backed out: splitting region_storage_stability into a collect pass and
a check walk. Its summary rows (`view_fns`) are sviews built in the pass's own inferred region
(`storage_owned_fn_rows`, the sort), and stage0's region checker rightly rejects storing them
in the table for a later pass. A collect step has to copy such rows into table-owned storage
(as the param-growth rows already are, via `text_storage`), which is step 3 below.

Plan, in order:

1. Move per-walk cursor state out of SymbolTable: a `WalkCursor { current_module,
   local_type_*, walk_depth, current_function_* }` passed to walkers instead of
   save/restoring table fields. Mechanical but touches the shared type helpers that read
   `table.current_module` (annotation_type_id, type_of_name, ...).
2. Collect steps for the memo passes (fver, readonly, firm externs, private fields): build
   each index once before the check phase, as done here for region storage.
3. Give `text_storage` per-worker arenas (type-path text is scratch) or precompute it.
4. Then the 345 diagnostic-only passes plus the split check walks are pure over a frozen
   table and can run per function (or per pass group) on threads with per-thread
   arenas/diagnostic buffers, spliced back in pass order. The fork experiment of round 3
   showed fork costs (~45 ms each, CoW faults) eat the gain on this host; threads sharing the
   frozen table avoid both.

## Round 6 (claude/perf-r6): sized AST records

The packed AST store used one fixed 148-byte row per node (4-byte tag + `[36 x i32]`, sized
by `Decl.Func`), so most nodes carried 100+ bytes of padding through every walk. Hierarchies
with at least 48 variants (`PACKED_AST_SIZED_MIN_VARIANTS`, i.e. the compiler's own AST) now
get one record per node sized to its variant (4 + 4 x row slots, rounded to 8), bump-allocated
from 64 KB blocks; chunk slots hold record addresses (`record_bytes == 0` marks a sized store,
`ctx_aos_store_alloc_sized` / `ctx_aos_store_sized_record`). The in-record layout is unchanged,
so no match or field site changes; small AST-shaped fixtures keep the fixed row. Rejected
earlier: widening the row (148 -> 292 bytes made check 13-18% and ast 22% slower), which
confirmed stride is the cost.

Measured in one QUIET window on the gate box (load rose from 3 to ~24 mid-window from other
tenants; round 1 is the quiet one), five rotated rounds, both compilers self-built at -O2:

| measure (self-host unit) | main b26659e2 | perf-r6 |
|---|---|---|
| `-emit check` wall, quiet round (load ~3) | 18.07 s | 14.88 s (-18%) |
| `-emit check` wall, median of 5 | 20.49 s | 16.92 s (-17%) |
| semantic CPU, quiet round | 16.2 s | 13.2 s |
| `-emit ast` wall, median of 5 | 2.03 s | 1.85 s |
| `-emit tokens` wall, median of 5 | 0.89 s | 0.87 s (unchanged) |

Verification: fast gates at baseline (emit_ast 28, diagnostics_diff 409, semantic_internal 54,
semantic_acceptance 3); never_leak, borrow_exclusivity, loop_value_codegen, backend_aos and
packed_aos_row_width smokes OK; backend_native 565/566 (the known arm64-triple check);
self_host_gen3 fixpoint. Corpus (2854 files): tokens/ast/check identical everywhere; -O0
objects identical except 37 programs that compile the compiler's AST (expected: they now use
sized records), and those 37 executables give identical exit codes and output under both
compilers. The new compiler rebuilds itself to a byte-identical object.

## HANDOFF (round 8, parallel semantic passes, WIP on claude/parallel-check)

Done:
- stage0 (Elisa-core, claude/parallel-check d965439b): `submit` of a worker with a hidden
  `__packed_store_` param captures the submitting scope's store; workers that build nodes
  (including payload-less variants such as `Expr.Absent`) are rejected. go test failures are
  the same 290 as main.
- stage1: store-capturing submit in codegen (codegen_submit_store_capture.elisa), 64 MB pool
  worker stacks, the parallel runner (semantic_parallel.elisa), the generated pass list
  (semantic_parallel_passes.elisa, 221 passes), and the audit/generator
  scripts/semantic_parallel_gen.py (`--check/--write/--report`; run `--write` on main's
  sequential semantic_api.elisa).
- The seed builds. Serial `-emit check` of the self-host unit works (~18.5 s).

Historical blocker: the first parallel `-emit check` segfaulted in `par_pass_run`'s splice loop
because a worker's diagnostics pointed into its frame's auto region after that region had been
unmapped. The current worktree includes a deep-copy path: workers copy diagnostic records and
all text fields into a job-owned arena, then the parent copies them into its own stable storage
before freeing each job arena. This matches the lifetime failure's proposed fix, but parallel
execution and output parity have not been verified; the serial `-emit check` result below does
not establish that the parallel path works.

Next:
- Verify the diagnostic-ownership mitigation and append-only pass audit.
- Run gen2, det.sh, gates.sh (fast gates, the smokes, self_host_gen3), the corpus diff and the
  QUIET timing, then write the round-8 table.
- Land stage0, then stage1.
- Bigger lever: remove the `Expr.Absent` sentinel constructions. 62 passes are blocked only by
  these.

Historical round-8 artifacts lived on a retired remote host; its endpoint is no longer configured.

## Round 7 (claude/perf-r7-pos)

### Profile after sized records (cachegrind, `-emit check`, 7ec9def9)

45.7 G instructions, 742 M D1 read misses (was 1.08 G), 263 M LL read misses (was 274 M).
Sized records cut L1 traffic; the LL stream barely moved: ~90% of LL misses are in semantic
passes, spread over ~300 functions, each whole-AST walk ~0.9 M misses (~56 MB, more than the
40 MB L3). The AST is ~3.3 M nodes / ~150 MB of records, and the 24-byte `Pos` span that ends
55 of the 68 payload variants is about half of it.

Per-pass CPU (quiet box): semantic passes ~12.7 s of ~15 s. An audit of every pass's
transitive SymbolTable writes (helpers included, `in table.X:` region blocks, `&table.X`
borrows, mutable globals) finds 307 of 438 passes append-only (write only `diagnostics`, never
read earlier ones): ~5.1 s in 39 contiguous runs, ~4.3 s saved if each run ran in parallel
(bounded by its longest pass). That is the larger lever, but it is blocked (below), so this
round takes the cold-`Pos` split.

### Option 1 (pending): threads over a frozen table

**Blocker.** Every function that touches the AST takes the store as a hidden trailing
parameter (`runtime.active_store`, codegen_declare.elisa). A thread entry cannot supply it,
the source cannot name it, `spawn1`/`spawn_raw` are rejected outside the runtime std, and
stage0 rejects `nursery: submit worker(job)` because `pool_submit1`'s `fn(A) -> R` type
cannot carry the store region (`__packed_store_Ast_Node: <invalid>` vs `Store[Local]`). The
worker itself is otherwise ready (claude/perf-r7, `semantic_parallel.elisa`: shallow byte copy
of the table with empty diagnostics, per-job arena via `in job.arena:`, splice in pass order;
stage1 accepts it).

**stage0 change (Elisa-core).** Let a submitted function's packed-store region unify with the
submitting scope's store: when checking `pool_submit1`/`spawn1` and the `submit` desugar,
instantiate the callee's implicit `__packed_store_*` region parameters from the caller's
active store instead of leaving them `<invalid>`; the store is frozen for the nursery's
lifetime, so the thread-shareability rule should treat a read-only store handle like a
`static` ref (and reject constructors/mutation inside the submitted function). Codegen:
capture the store pointer in the work item and pass it as the hidden argument in the
generated entry thunk.

**stage1 change.** The same two pieces: (1) the semantic rule (`check_thread_shareability`,
`check_thread_transfer_provenance`) accepts a submitted function that only reads the
caller's AST store; (2) codegen for `submit f(x)` when `f` needs `ast_store_needed`: box
`{arg, active_store}` into the work1 state and emit a per-callee entry thunk that unpacks it
and calls `f(arg, store)`. Then `semantic_parallel.elisa` replaces each append-only run
(largest runs first) with `par_pass_run`.

**Risks.** Data races through state the audit misses (the audit is textual: a helper writing
the table under another name, or a lazily built index in the table, would race; mitigate by
re-running the audit in `scripts/test.sh` and failing on any new writer in a parallel run);
allocator sharing (per-job arenas are required, never the table's region); nondeterministic
diagnostic order (the splice is by pass id, so order is fixed by construction; pin it with
diagnostics_diff); thread stacks (passes recurse deeply; workers need the main thread's
512 MB stack, so the pool must be created with an explicit stack size); and a stage0 change
that lands in the shared seed, so the seed provenance has to move with it.

**Gates.** Elisa-core's own suite for the stage0 change; then the usual set here: stage0 seed,
self_host_gen3, never_leak / borrow_exclusivity / loop_value_codegen / backend_native smokes,
fast gates at baseline, corpus diff (tokens/ast/check/-O0 objects), the compiler rebuilding
itself to an identical object, plus 20 repeated `-emit check` runs of the self-host unit with
byte-identical diagnostics (determinism under scheduling), and a ThreadSanitizer build of the
check path on the box.

### Cold-Pos split: status (WIP, not on main)

Commit d6d10088 on claude/perf-r7-pos (codegen_packed_cold_pos.elisa; runtime
`ctx_aos_store_side_slot` + side chunks for sized stores). Verified so far:
- the self-built compiler (p2) gives the same self-host `-emit check` output as main;
- p2 rebuilds itself to a byte-identical object (p2.o == p3.o);
- a parser probe built by the new codegen reports the same positions as main's;
- stage0 6f0988a2 `-emit semantic` accepts the tree.

Pitfalls fixed on the way:
- every whole-payload read must go through the cold-aware loader, including the nested `is`/sub-pattern binders;
- the cold decision must be program-level (`packed_cold_pos_program`) plus "enum is an AST refinement or root". A per-enum-index check made `Ast::expr_pos` read spans from the record.

Remaining before landing:
1. Results of the full gate on stage0 6f0988a2. It was launched from the worktree with
   `ELISA_REMOTE_DIR=/root/work/r7-gate ELISA_REMOTE_CORE=/root/work/r5-core` and logs to
   /private/tmp/claude-501/r7gate.log. Baselines: emit_ast 28, diagnostics_diff 409,
   semantic_internal 54, semantic_acceptance 3, backend_native 565/566 (the arm64-triple row is
   known to fail).
2. The stage0 seed and self_host_gen3 against stage0 **778c8281**, using a private copy:
   `ELISA_CORE=claude-worktrees/r7-core778 ELISA_REMOTE_CORE=/root/work/r7-core778 ... gen3`.
   Never touch /root/Elisa-core.
3. The corpus diff. /root/work/r7/corpjob.sh writes cb.m (main) and cb.n (branch).
   tokens/ast/check must be identical. -O0 objects may differ only for programs that include
   the compiler AST; for those, run the executables and compare exit codes and output, as in
   round 6.
4. A QUIET-window table: mm (main built by itself) against p2, over check/ast/tokens, using
   /root/work/r5/quiet.sh.
5. Rebase onto origin/main, fast-forward main, and remove the worktrees (perf-r7-pos,
   r7-core, r7-core778) and the box directory /root/work/r7.
