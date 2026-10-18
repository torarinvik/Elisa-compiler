# Compiler incrementality reference study

**Research snapshot:** 2026-10-18  
**Purpose:** extract concrete incremental-compilation and data-layout ideas for Elisa from Zig, rustc, Clang/LLVM, and GCC. Source checkouts and generated comparison artifacts are under the ignored `build/research/compiler-sources/` directory.

## What the references do

### Zig: typed dependencies and compact compiler data

The current Zig checkout represents analysis units with compact typed handles (`AnalUnit` is a packed 64-bit value) and stores interned items as a small tag plus a 32-bit payload. The intern pool tracks distinct dependency kinds: source hashes, declaration values and types, inferred error sets, type layout, defaults, files and embeds, namespace contents, name existence, and memoized state. Distinguishing these facts lets an edit invalidate only analyses that depended on the changed fact. Name-existence dependencies matter for negative lookups: adding a declaration can invalidate a prior “not found” result even though no old declaration changed.

Dependency edges are indexed in both directions. A depender owns a compact linked edge chain; reanalysis can remove and replace all of its old outgoing edges. Edge slots are recycled. The update path marks transitive dependents as potentially outdated, waits until their dependencies have been checked, then prioritizes ready functions so useful code generation can proceed early. The frontend snapshots file state before scheduling work and avoids applying dependency invalidations when a failed frontend update makes the new analysis unreliable.

Zig also separates syntax tracking from semantic invalidation. During an update it maps old ZIR instructions to new locations; when an instruction cannot be tracked, it marks that instruction's source-hash dependency outdated. Semantic dependers move through a potentially-outdated state with a count of unresolved dependencies. As dependencies are confirmed current or outdated, the count falls and ready analysis units are queued. This lets the compiler wait for upstream results before reanalyzing dependers, while prioritizing ready functions for code generation. See [old-to-new ZIR tracking and failed mappings](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L807-L875), [dependency-count invalidation and ready-unit scheduling](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu.zig#L3212-L3420), and [tracked namespace-name invalidation](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L936-L992).

There is also a source-level scaling tradeoff in this update path. `updateZirRefs`
walks all tracked instructions to find those belonging to updated files, then
`rehashTrackedInsts` makes one pass to count surviving entries per shard and a
second to rebuild the maps. Thus targeted dependency invalidation coexists with
O(total tracked instructions) identity-maintenance work on a non-empty update.
This may be acceptable for Zig's workload, but Elisa should not copy the global
rehash pattern without a profile; a per-file tracked-ID index is a candidate if
that sweep becomes measurable. See Zig's
[`updateZirRefs`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L796-L1000)
and [`rehashTrackedInsts`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L328-L418).

The ZIR cache is a separate front-end layer. `updateFile` derives its cache
directory from the file path, Zig version, and backend, then validates a cached
file using recorded size, modification time, and inode. Later semantic analysis
gives each `Nav` a dependency on its declaration's ZIR source hash. This keeps
file-level parsing reuse distinct from declaration-level semantic invalidation;
it does not make a file-cache hit proof that unrelated semantic reads stayed
unchanged. See [`updateFile` cache key](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L489-L495), [cached-file metadata validation](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L761-L768), and [Nav source-hash dependencies](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L1716-L1717).

The concrete data layout is worth comparing with Elisa. Zig's `AnalUnit` is a packed 64-bit value containing a 32-bit kind and 32-bit ID. `TrackedInst` uses stable 32-bit IDs across an update and maps them to current ZIR locations; a lost mapping has an explicit sentinel. A `DepEntry` stores a depender handle and three 32-bit adjacency links. Its dependency key is implicit in the per-kind dependee-head maps, so it does not duplicate that endpoint in every edge. Zig also gives namespace-name existence its own dependency key, so an earlier missing-name result can be invalidated when that name is added. See [`AnalUnit` and tracked instruction IDs](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L137), [`AnalUnit`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L422), [`namespace_name` dependency heads](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L75), [`Dependee.namespace_name`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L746), [`NamespaceNameKey`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L918), Zig's [namespace name lookup dependency](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Sema.zig#L6026-L6045), [`DepEntry` plus edge insertion/removal](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L925), and [name-change invalidation](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L978-L992).

Elisa already uses compact 32-bit query and edge IDs, dense node/edge pools, recycled edge slots, forward and reverse adjacency, and a reusable invalidation worklist. Its current edge has two 32-bit endpoints, three 32-bit links, and a 64-bit observed result generation: 28 bytes of fields, likely 32 bytes with conventional 8-byte alignment. Zig's `DepEntry` omits the dependee endpoint because typed dependee-head maps retain that identity, and uses dummy heads when removing a list head. That pattern could reduce Elisa's edge payload, but it would need to preserve the current result-generation check and be evaluated against additional indexing and update costs. Zig's `potentially_outdated` and `outdated` maps also track unresolved dependency counts and prioritize ready functions after upstream dependencies settle; Elisa has `PotentiallyDirty` status but no ready-unit queue.

The useful data-oriented transfer is stable integer handles, typed dependency identities, dense pooled records, and hot fields placed for the traversal that consumes them. Zig also uses maps where dynamic dependency keys and scheduling need them; its source does not imply that every compiler table should become structure-of-arrays. Elisa's graph now has a private `SourceInput`/`FunctionBodyFacts` evaluate-and-commit caller, but the body-query hit overlaps the prior exact-body/surface reuse path and still validates the canonical payload against the previous typed facts. Its graph integration is experimental groundwork, not measured acceleration. The query node now stores its six key/input/result byte-span fields as checked `u32` values. With the current incoming-edge validation fields, the source-level estimate is 112 bytes per node instead of 136 bytes with `usize` spans on a conventional 64-bit layout. That saves 24 bytes (about 1.5 MiB at the 65,536-node cap) before allocator and index effects. This remains an unmeasured layout estimate; measure query-node allocation and retained-edit traversal before attributing a memory or speed improvement.

Zig's data-oriented choices extend beyond the dependency graph. `InternPool.Local` partitions mutable interned storage by thread, and its `List(Elem)` wrapper uses `std.MultiArrayList(Elem)` so each field occupies a contiguous array; typed integer handles keep references stable as those arrays grow. Mutation metadata is separate from the reader-visible state, cache-line aligned, and growth publishes the new backing storage atomically. The compact `Nav.Repr` is documented as 30 bytes, with flags packed into 16 bits; its representation is deliberately optimized for the common analysis-backed case, which the source reports as about 74% of navs. These choices support parallel access and selective field scans in large compiler tables. Elisa's current invalidation walk reads query status plus reverse-edge endpoints/links, while dependency validation reads edge endpoints and observed generations together, so a blanket SoA rewrite has no established advantage. Prefer measuring bytes and field-access patterns first; a narrower, bounded field such as the edge's observed result generation is a simpler experiment than splitting the whole graph.

Zig's analyzed IR makes the layout choice explicit: `Air.instructions` is a `std.MultiArrayList(Inst).Slice`, while variable-sized operands and other per-instruction payload live in a separate `std.ArrayList(u32)` ([`Air.zig`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Air.zig#L22-L25)). Passes can scan instruction columns without loading unrelated payload bytes, and compact indices connect the two stores. For Elisa, this is a candidate only for hot homogeneous scans—such as the bounded owner lists or query metadata—not a reason to split heterogeneous AST nodes wholesale. Compare bytes touched, allocations, and pass time on representative inputs before retaining a structure-of-arrays change.

The body-query path now evaluates against a checked span in the request-local snapshot and reuses the body's already computed FNV hash ([span evaluator](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/semantic/incremental_function_facts.elisa:2589>), [collection call](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/semantic/incremental_function_facts.elisa:1425>)). A matching fingerprint still requires exact byte comparison. Publication also evaluates against the span and only materializes an owned body input on a miss before committing it to the session pool ([publisher](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/semantic/incremental_function_facts.elisa:3064>)). This removes a temporary body copy and duplicate hash on the graph-hit path. The collector itself copies canonical body-token bytes into the snapshot, then rereads that span to compute `body_hash`; it also exact-compares equal-length/equal-hash bodies against the prior snapshot before it computes `trusted_surface_admitted`. Thus an unchanged candidate on a compatible surface incurs a copy, a hash scan, and an exact comparison; on a declaration-surface miss, that exact comparison cannot authorize reuse. A candidate experiment is to compute the hash while collecting token bytes and defer exact equality until after surface admission, only for cacheable length/hash matches. However, the current `darray.extend` preserves a bulk-copy path; a per-byte fused copy/hash loop may regress. Compare it with the current bulk-copy-plus-hash-scan path (and optionally source-hash-then-bulk-copy) before changing the collector. Exact bytes must remain the hit authority. With the graph enabled, a surviving hit then exact-compares the current span to the graph node's committed input as well. Skipping that comparison would require a checked invariant connecting the committed node/generation to the prior snapshot body; a matching hash or prior-snapshot equality alone is insufficient. Compare graph-on and typed-facts-only retained-body cases before adding that extra proof path. Measure retained edits and surface-miss edits separately, including bytes copied/hashed/compared and collection time, before claiming a compile-time gain.

The working tree now packs the six `NameLookup` input booleans into one flags byte and bumps the input schema from 2 to 3 ([encoder](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/semantic/incremental_function_facts.elisa:1880>)). The exact projection shrinks from 22 logical bytes to 17: a 32-bit schema, three 32-bit counts, and one flags byte instead of six single-byte flags. At the 65,536-node cap this saves at most 327,680 logical bytes. The field mapping is source-reviewed, but its performance effect remains unmeasured and likely modest. Qualification should report actual `NameLookup` node count, value-pool capacity, bytes hashed/compared, graph-clear frequency, and retained-edit time; a speed claim needs paired before/after measurements because the payload is tiny.

Zig's `InternPool.Local` does use arenas to preserve old backing buffers while concurrent readers may still hold their addresses; Elisa's synchronous query path does not need that lifetime extension. Likewise, omitting `dependee` from Zig's `DepEntry` is coupled to per-kind dependency-head maps and its potentially-outdated dependency-count protocol. Elisa currently reads each edge's `dependee` and `observed_result_generation` to validate query results, so dropping that endpoint alone would break the current check. Keep the present hot-first query-node layout and explicit edges until profiling identifies a measurable bandwidth or memory limit; any alternative should be benchmarked with graph build, lookup, invalidation, and dependency replacement workloads together.

Zig's incremental persistence is not a complete template to copy. The current source still has save-state TODOs for errors, namespaces, declarations, and linker state. The source study supports borrowing its in-memory dependency model and compact data layout selectively, not adopting its whole cache format.

Sources: [Zig `InternPool.zig` at the inspected commit](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig), [Zig `Zcu.zig`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu.zig), [frontend update path in `PerThread.zig`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig), [cache save-state path](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Compilation.zig).

### Rust: red-green query evaluation

rustc records query dependencies and fingerprints. When an input changes, dependent queries are reconsidered. A recomputed query can still be marked green if its result fingerprint matches the prior result, preventing unchanged downstream work from being invalidated. At the inspected revision, `try_mark_green` recursively checks an old node's dependencies; if a dependency is still unknown, it tries to force that query from its stable dep-node key. If the key cannot be forced, rustc returns `None` so the caller recomputes. The recorded dependency order matters because control flow can change which queries are read. Persistent data is selected by query/result policy rather than serializing every in-memory compiler object indiscriminately. Code-generation work products are tracked as a separate artifact layer.

The serialized graph stores node keys, value fingerprints, and dependency edges, then builds its node-to-index reverse map lazily per query kind on the first lookup. A successful green check promotes the old node and its edges into the current graph; disk-backed query values needed in the new cache can be loaded in a later promotion pass. These steps trade eager indexing and eager value loading for incremental maintenance, but they still have a cost on no-change builds. Measure reverse-index construction, green-node promotion, and cache promotion alongside queries skipped before treating a high green count as a speedup. See [`LazyNodeIndex` and its profiled per-kind map](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/serialized.rs#L115-L185), [serialized graph lookup](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/serialized.rs#L234-L248), [`try_mark_previous_green` edge promotion](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/graph.rs#L947-L1034), and [cache promotions](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/graph.rs#L1065-L1089).

rustc applies the same red-green decision to codegen units before compiling each unit's LLVM module. `determine_cgu_reuse` requires a prior work product and a green `CompileCodegenUnit` dep-node; the codegen loop then submits the cached pre- or post-LTO module instead of calling `backend.compile_codegen_unit`. This can skip per-unit IR generation, lowering, optimization, and object emission, subject to the complete CGU dependency fingerprint. Elisa Core's current `IncrementalObjectSession` operates later: it lowers and optimizes the full module, maps owners, clones and serializes every partition, then looks up exact bitcode plus target settings and skips only native emission on a hit. The rustc boundary is a longer-term target for Elisa, but requires stable codegen-unit identity and dependencies that include declarations, ABI, globals, and optimization inputs; current partition ownership can shift when functions are inserted. See [`determine_cgu_reuse` and reuse dispatch](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_codegen_ssa/src/base.rs#L853-L895) and [CGU reuse checks](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_codegen_ssa/src/base.rs#L1255-L1297).

For Elisa, the useful rule is: propagate change from semantic result fingerprints, not merely from changed source text or a changed dependency. Recompute at the right boundary, compare the canonical result, and stop invalidation when that result is unchanged. Query dependencies must capture the reads that determined the result, including resolution candidate sets and failed lookups. Elisa now has a request-scoped `NameLookup` query at the serial `Expr.Ident` read site, alongside collector `SourceInput` and `FunctionBodyFacts` queries. It caches only `(known, module_only)` from exact surface facts rebuilt from the current symbol table; it does not skip body checking or derive persistent per-name inputs from declaration deltas. Elisa also lacks rustc's generalized force-from-dep-node scheduling path, so this resolver query remains a narrow read-site prototype rather than reuse of semantic analysis units.

Sources: [Rust incremental compilation guide](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation.html), [detailed red-green explanation](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation-in-detail.html), [`try_mark_green` implementation at the inspected commit](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/graph.rs#L909-L1000), [rustc incremental implementation](https://github.com/rust-lang/rust/tree/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_incremental).

There is also a narrow scratch-storage comparison in the source. rustc keeps a
per-worker `green_edge_buf` while recursively trying to promote an old node,
then returns the emptied vector to the worker-local slot. Elisa's
`ifq_query_dependencies_check` creates local `dependency_ids` and `old_ids`
arrays on each validation. Its duplicate detection and old/new set comparison
use nested scans, so worst-case work is quadratic in dependency fan-out under
the 4,096-edge per-query cap. Current production call sites pass zero
dependencies for `SourceInput` and `NameLookup`, and one `SourceInput` edge for
`FunctionBodyFacts`; the quadratic case is therefore a future fan-out concern,
not a measured hot path today. A specialized zero/one-dependency check or
reusable request-local scratch could avoid general set-building overhead on the
current path. This is a source-level candidate, not evidence that the arrays
allocate or dominate runtime; rustc's buffer serves recursive edge traversal,
which has different invariants. Measure allocation count and validation time on
retained body edits and on a representative multi-dependency graph before
keeping a specialization. See rustc's
[`green_edge_buf` declaration and reuse](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/graph.rs#L157-L158), [take/call/return path](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/graph.rs#L930-L935), and Elisa's `ifq_query_dependencies_check`.

### Clang/LLVM: front-end reuse and artifact boundaries

Clang precompiled headers and modules serialize AST state and lazily load declarations and types. A precompiled preamble can let an editor reparse the edited portion of a source file while reusing the unchanged prefix and includes. These mechanisms target front-end work and are separate from object reuse.

The precompiled-preamble source shows the reuse proof and its limits. Clang requires the same preamble bounds and exact prefix bytes, then checks the files used by the preamble and candidate paths for file-not-found diagnostics; if a recorded missing path appears, or an input no longer matches, reuse fails and cached preamble declarations and diagnostics are discarded ([`ASTUnit.cpp`](https://github.com/llvm/llvm-project/blob/70a4494e073f57eebb77931a5a2e59f6b5e9e13a/clang/lib/Frontend/ASTUnit.cpp#L1293-L1313), [`PrecompiledPreamble.cpp`](https://github.com/llvm/llvm-project/blob/70a4494e073f57eebb77931a5a2e59f6b5e9e13a/clang/lib/Frontend/PrecompiledPreamble.cpp#L614-L705)). The negative-path set is deliberately incomplete: it collects plausible missing-file diagnostics but can omit entries under search roots that did not exist when the preamble was built ([`PrecompiledPreamble.cpp`](https://github.com/llvm/llvm-project/blob/70a4494e073f57eebb77931a5a2e59f6b5e9e13a/clang/lib/Frontend/PrecompiledPreamble.cpp#L77-L85)). During preamble construction Clang can skip function bodies ([`ASTUnit.cpp`](https://github.com/llvm/llvm-project/blob/70a4494e073f57eebb77931a5a2e59f6b5e9e13a/clang/lib/Frontend/ASTUnit.cpp#L1345-L1353)). Disk-file dependencies are recorded and checked using size and modification time in this implementation, while remapped in-memory buffers are hashed; Elisa should keep its stronger exact-byte or content-hash checks for cache authority. A future Elisa parse-prefix cache would also need negative include dependencies and request-local AST rebinding or a serialized representation, since current AST pointers and source views cannot outlive a request.

ThinLTO separates a summary index from per-module backends. The thin link can reason over summaries instead of loading every full module. Backend results use a cache key derived from module/import-export decisions and code-generation configuration; a hit is checked before parsing and optimizing the full module. This is a useful boundary lesson for Elisa: key artifacts by the exact canonical input snapshot and all target/backend settings that affect the object. A path, source timestamp, or LLVM version string alone is not enough.

The inspected LLVM implementation also keeps distinct cache entries for the generated object and optimized IR: `LTO.cpp` derives an IR key from the code-generation key with an additional `IR` domain tag, then arranges for the ThinLTO backend to produce whichever artifact is missing ([cache-key construction](https://github.com/llvm/llvm-project/blob/70a4494e073f57eebb77931a5a2e59f6b5e9e13a/llvm/lib/LTO/LTO.cpp#L1789-L1815)). Its shared key includes compiler revision, module summary hash, import/export identities and imported-module hashes, ODR resolution, and codegen settings; the source explicitly leaves a FIXME for additional target options ([`computeLTOCacheKey`](https://github.com/llvm/llvm-project/blob/70a4494e073f57eebb77931a5a2e59f6b5e9e13a/llvm/lib/LTO/LTO.cpp#L136-L203)). This gives Elisa a model for separating optimized-IR and native-object artifacts only after optimization is a reusable per-unit step. Elisa's current `-O2` optimization remains whole-module, so caching a post-optimization shard cannot avoid that earlier work.

The Go Core compiler's `IncrementalObjectSession` is a later cache boundary: it
lowers the whole module, runs its configured module-wide optimization (a no-op
at O0), clones and serializes each stable symbol-hash partition, then checks
exact bitcode and target keys before native emission. It skips machine-code
generation for matching partitions, but does not skip frontend work, module
lowering/optimization, or per-partition preparation; its retention is
process-local. ThinLTO's cache key instead includes the compiler
revision, module summary hash, imports/exports, resolved ODR state, and codegen
configuration, and its hit check precedes loading the full backend module. The
transferable opportunity is an earlier reusable summary/backend boundary with a
complete dependency key, not treating the current shard hit count as whole-module
incremental compilation.
LLVM's key implementation itself has a FIXME that more target-machine options
should be hashed, so copy the cache boundary and dependency audit, not an
assumption that the current implementation covers every configuration input.

Sources: [Clang precompiled-header internals](https://clang.llvm.org/docs/PCHInternals.html), [ThinLTO design](https://clang.llvm.org/docs/ThinLTO.html), [`ThinLTOCodeGenerator.cpp` cache implementation at the inspected LLVM commit](https://github.com/llvm/llvm-project/blob/70a4494e073f57eebb77931a5a2e59f6b5e9e13a/llvm/lib/LTO/ThinLTOCodeGenerator.cpp#L369).

### GCC: multiple reusable representations

GCC's pipeline provides another useful comparison point: its GIMPLE pass hierarchy operates on a language-independent high-level representation, while RTL passes lower toward machine instructions. Its LTO code has explicit streaming and partitioning paths for cross-file optimization. That reinforces the same architectural separation seen in LLVM: semantic-analysis reuse, IR/work-product reuse, and final machine-code reuse are different cache layers with different inputs and correctness boundaries. See GCC's [GIMPLE pass interfaces](https://github.com/gcc-mirror/gcc/blob/9a00f0797c90485cd70ac86a8751c9565c3979dd/gcc/tree-pass.h), [LTO partitioning](https://github.com/gcc-mirror/gcc/blob/9a00f0797c90485cd70ac86a8751c9565c3979dd/gcc/lto/lto-partition.cc), and [LTO streaming](https://github.com/gcc-mirror/gcc/blob/9a00f0797c90485cd70ac86a8751c9565c3979dd/gcc/lto-streamer-out.cc).

The GCC checkout is source-only and sparse; we did not build it or make an equivalent runtime comparison. `/usr/bin/gcc` on this machine resolves to Apple Clang, so it is not a usable GCC toolchain. The assembly experiment below uses Clang as the C frontend because it emits LLVM IR directly.

The inspected GCC source does have a concrete incremental artifact layer:
`-flto-incremental=<path>` lets `lto-wrapper` reuse matching LTRANS inputs and
skip that translation unit's LTRANS compilation. The cache hashes each input
file and byte-compares same-hash candidates, coordinates creation/deletion with
locks, and prunes old entries above a soft limit ([`lto-wrapper.cc`](https://github.com/gcc-mirror/gcc/blob/9a00f0797c90485cd70ac86a8751c9565c3979dd/gcc/lto-wrapper.cc#L2071-L2103), [`lto-ltrans-cache.cc`](https://github.com/gcc-mirror/gcc/blob/9a00f0797c90485cd70ac86a8751c9565c3979dd/gcc/lto-ltrans-cache.cc#L37-L95), [GCC option docs](https://github.com/gcc-mirror/gcc/blob/9a00f0797c90485cd70ac86a8751c9565c3979dd/gcc/doc/invoke.texi#L16252-L16269)).
This is reuse at the LTO backend boundary, not frontend or semantic reuse.
The inspected cache's content identity does not by itself establish how all
compiler-option identity is covered; treat the artifact boundary and exact-byte
collision check as design observations, not proof that its full cache key is
sufficient for Elisa.

### Elisa Core: parser suffix replay

The current Go Core working patch adds lexer suffix convergence: after an edit, it can resume from a saved lexer checkpoint once the remaining source bytes and lexical state converge, then rebase token offsets and line attribution while retaining source ownership. It tracks `#line` attribution epochs and declines convergence when the old stream has lexer errors or the current lexical state has pending layout work. The lexer tests compare shifted and `#line`-reset streams with cold lexing. A source-frozen `TokenizeSource` benchmark records a median 484.0 to 159.1 microseconds per early edit and 1,136,558 to about 752,002 allocated bytes, while allocations rise from 35 to 52. That benchmark includes source construction and bypasses the source-cache digest, parser, semantic analysis, and object emission; it demonstrates a narrow lexer-stage benefit, not edit-to-executable latency. Source equality checks and token rebasing still perform work proportional to the unchanged suffix.

Convergence still walks and rebases every reused suffix token, and the parser receives a copied full token slice, so this path remains O(n) in suffix-token count even when it avoids rescanning token contents. The native shifted-edit control executes `first()` but leaves its 64 trailing `workN` functions uncalled; it asserts lexer suffix reuse but does not assert native partition-cache reuse. Extend the behavioral control to consume at least one declaration after the convergence boundary, and report lexer and object-cache reuse as separate facts.

Parser suffix replay remains narrower. `MatchingTokenSuffix` still requires equal token counts and exact `Token` equality, including source positions, and the parser rejects replay when recorded state, inspected-token ranges, diagnostics, or recovery state do not match. So the lexer can reuse shifted tokens while AST suffix replay declines once surviving tokens move. `BenchmarkSourceSyntaxSuffixPaired` only replaces one six-digit literal with another, which preserves positions; report that parse benchmark as equal-width literal replacement. Supporting shifted AST suffixes would require rebasing every source span in the copied syntax graph and preserving diagnostic positions, with a cold fallback when a span cannot be mapped. The implementation and benchmarks are in `compiler/src/lexer/incremental_source.go`, `compiler/src/lexer/incremental_suffix.go`, `compiler/src/parser/syntax_suffix.go`, `compiler/src/ast/syntax_snapshot.go`, `compiler/src/lexer/incremental_suffix_test.go`, and `compiler/src/source_syntax_suffix_test.go` in the local Elisa Core checkout.

Saved paired results for the earlier `d1cc388` parser-suffix snapshot (Apple M5, 512 trailing functions, equal-width edit) show median 3.93 ms/edit with AST suffix replay versus 5.25 ms/edit with token reuse and fresh parsing, about 25% lower in that narrow parse-only comparison. The three samples varied substantially. Standalone mode samples used 6,774 allocations and about 4.98 MB/op with suffix replay versus 7,765 allocations and 4.44 MB/op with fresh parsing, so fewer allocations did not mean fewer bytes. These results predate the current lexer offset-rebasing patch and do not measure shifted AST reuse. Raw output is `build/verification/incremental-syntax-suffix-qualified-20261018/elisa-suffix-presized-bench.txt` in the local Elisa Core checkout.

## Equivalent generated-code comparison

A small wrapping-`u64` loop was first written in Zig, Rust, and C. It updates an accumulator with the same recurrence and uses a loop-carried dependency so the inner loop remains visible. We emitted optimized LLVM IR and assembly with Zig's LLVM backend, rustc, and Clang for Apple arm64 / `apple-m5`, with frame pointers omitted and optimization enabled.

The optimized LLVM text was not identical. Zig's LLVM output had already expressed the multiply-by-constant recurrence as an incrementing induction value; the Rust and Clang LLVM text still showed the multiply in the loop. After machine-code optimization, all three produced the same loop body:

```asm
add  x10, x1, x8
eor  x1, x10, x1, lsr #13
add  x8, x8, x9
subs x0, x0, #1
b.ne loop
```

The constant setup, empty-loop check, and return sequence also matched. This is a code-shape comparison, not a timing benchmark; it establishes no runtime speedup. It is a concrete warning against ranking compiler output by LLVM-IR instruction count alone. Compare final assembly and benchmark representative programs before adopting an optimization.

The initial saved outputs used different macOS deployment versions. I reran the probe with a common `arm64-apple-macosx11.0.0` deployment target and `apple-m5` CPU, and omitted frame pointers in all three builds. The emitted function bodies then match instruction-for-instruction at 13 AArch64 instructions, including the loop. Zig's optimized LLVM IR still strength-reduces the constant multiply into a second induction value; rustc and Clang retain a multiply in their optimized IR, but machine-code lowering removes that difference. The Clang assembly carries `sdk_version 27.0` metadata from the installed SDK; its deployment target remains macOS 11.0.0. This is still one code-shape probe, not a timing result or a broad compiler ranking.

The normalized rerun used Zig 0.17.0 (`-O ReleaseFast -fllvm -fomit-frame-pointer -fstrip`), rustc 1.99.0 / LLVM 23.1.2 (`-C opt-level=3 -C codegen-units=1 -C force-frame-pointers=no`), and Homebrew Clang 23.1.3 (`-O3 -fomit-frame-pointer`). It exercised Zig's LLVM backend, not its native backend. Inputs are in `build/research/compiler-sources/ir-compare/`; normalized outputs are in `build/research/compiler-sources/ir-compare/out/matched-target-11/`.

I then added the current Core compiler to the same code-shape probe. The exported C-ABI Elisa fixture is `build/research/compiler-sources/ir-compare/kernel-elisa-export.elisa`; it has no `main` call that could specialize or fold the measured function. I built Core from the working tree and emitted an object with `ELISACORE_TARGET_CPU=apple-m5`, `-target-triple arm64-apple-macosx11.0.0`, and `-O3`. Its final `_kernel` body is the same 13-instruction sequence as the Zig, rustc, and Clang objects. Elisa's saved pre-optimization LLVM module still contains the multiply; the selected LLVM machine pipeline strength-reduces it during native code generation. The object and LLVM module are saved as `elisa-core.o` and `elisa-core.ll` in the matched-target output directory, with a disassembly in `elisa-core-objdump.txt`. The older root-level `kernel.o` is from the earlier Zig probe and is not Elisa evidence. This remains one function and one CPU, with no timing samples, so it establishes code-shape parity for this probe rather than general performance parity.

A second probe covers unsigned saturating addition in C, Rust, Zig, and Elisa. The optimized LLVM IR for all four represents it as `llvm.uadd.sat.i64`; for the common macOS 11.0 / `apple-m5` target, the final function body is also identical:

```asm
mvn  x8, x1
umin x8, x0, x8
add  x0, x8, x1
ret
```

The C build used Homebrew Clang 23.1.3 by absolute path, Rust used 1.99.0, Zig used 0.17.0 with `-fomit-frame-pointer`, and Core used the same target recipe as above. Clang's assembly records SDK 27.0 metadata, but its minimum deployment target is still macOS 11.0. Sources and outputs are under `build/research/compiler-sources/ir-compare/saturating-add/`. The first Elisa variant exported a differently named wrapper around a private implementation; that object contains a branch relocation to the implementation. `llvm-objdump -dr` identifies the relocation target, so its initial zero-offset disassembly is not a self-loop. The same-name direct export used for the comparison removes that wrapper and emits exactly the four-instruction body. This confirms that alias/wrapper shape matters when comparing code, and that neither IR nor disassembly should be read without its target and relocation context. The result is a second narrow code-shape match, still without runtime timing evidence.

A third probe rotates a `u64` left by an arbitrary `u64` count, with the count reduced modulo 64 in every language. The optimized IR from C, Rust, Zig, and Elisa uses `llvm.fshl.i64`; all four objects emit the same three instructions on this target:

```asm
neg  w8, w1
ror  x0, x0, x8
ret
```

The Rust intrinsic, Zig `std.math.rotl`, C shift/or expression, and Elisa shift/or expression therefore converge to the same lowering. Sources and outputs are under `build/research/compiler-sources/ir-compare/rotate-left/`. This adds one bit-manipulation case to the code-shape evidence; it still does not establish runtime performance across representative programs.

A fourth probe counts set bits in a `u64`. C's `__builtin_popcountll`, Rust's `count_ones`, Zig's `@popCount`, and Elisa's `llvm.ctpop.i64` intrinsic all produce `llvm.ctpop.i64` in optimized IR. For macOS 11.0 / `apple-m5`, all four object files contain the same two instruction words:

```asm
cnt  x0, x0    // 0xdac01c00
ret             // 0xd65f03c0
```

The C, Rust, Zig, and Core builds used macOS 11.0 / `apple-m5`; the optimized IR target triples use the equivalent `arm64`/`aarch64` spellings. Exact commands and versions are recorded in `build/research/compiler-sources/ir-compare/popcount/commands.txt`, alongside the sources and outputs. This confirms exact object-code parity for one scalar bit-count function. It does not measure throughput or establish broad codegen parity.

A fifth probe returns the high 64 bits of an unsigned 64-by-64 product. C's `__uint128_t`, Rust's `u128`, Zig's `u128`, and Elisa Core's `elisa.mul_hi.u64` builtin all produce the same widened multiply/shift/truncate shape in optimized LLVM IR. The macOS 11.0 / `apple-m5` machine-code bytes for this function are identical:

```asm
umulh  x0, x1, x0    // 0x9bc07c20
ret                   // 0xd65f03c0
```

Sources, object files, IR, assembly, and the exact build commands are under `build/research/compiler-sources/ir-compare/mul-high/`. This is another narrow code-shape match without runtime timing evidence.

## Recommendations for Elisa

1. **Qualify the connected Core compile-server path, and keep Stage1 cache integration separate.** The Go Core compile-server creates an `IncrementalObjectSession` and routes named incremental object requests through `WriteObject`; the cache can reuse native partitions after fresh analysis. This establishes a narrow driver caller, but the saved measurements do not establish a current-tree speedup: server integration metadata records `447974b60498b1268365baa866a47c276cfc90a0`, native-execution evidence records `7cf85dc0600967090b1a68e2a3ec6410d3994960`, and the paired benchmark metadata has no source revision. That benchmark is synthetic source-to-object on a shared host; it does not link and execute the result. Requalify against one source-matched current revision with clean/warm parity, one-shard invalidation, corruption recovery, and edit-to-executable measurements. Separately, the Stage1 CLI helper and backend snapshot API still lack a restore/publish caller; its next milestone remains opt-in plain native `-O0` object output, exact loaded-toolchain and target recipe validation, deterministic logical merge order, and a cold fallback for unsupported inputs.

2. **Move reuse into real semantic read sites and qualify the existing host.** One-shot CLI compilation still uses a disabled session, while the opt-in `compile-session` and `semantic-session` hosts keep an enabled session across requests. Query-graph evaluation within those hosts is separately opt-in with `ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH=1` because retained arena capacity is not yet bounded. `compile-session` still rereads and reparses the current source, reruns semantic checking, and rebuilds and emits LLVM state. The graph serves `SourceInput`, `FunctionBodyFacts`, and an opt-in `NameLookup` query at serial `Expr.Ident` classification. The body-fact route still requires exact old-surface/body proof. NameLookup uses exact per-name surface facts, built lazily at the first eligible read after collection, rather than a whole-file `SourceInput` edge, so unrelated declaration changes can leave it green while changes to the matching symbol, member, visibility, or region facts change its input. The next step is to qualify the read-site path on retained edits through object emission while keeping current diagnostics authoritative; the surface-index changes have no build, parity, or benchmark qualification.

3. **Refine the first real dependency at a semantic read site.** The initial translation-unit `Expr.Ident` slice is wired into the serial resolver walk: it queries and caches the composite `(known, module_only)` classification before global symbol/member-chain scans, while preserving local binding and region-name behavior. The first eligible unbound classification in the serial resolver lazily finalizes a collision-safe exact-spelling surface after declarations, aliases, imports, and region annotations are collected; requests with no eligible reads skip the expected-linear `O(import annotations + symbols + members + regions)` build and its index construction, while a request with one still pays it. That serial walk precedes the parallel pass batches and remains the safest first consumer of the mutable session graph. The surface stores the explicit `name_indexed` gate, total and non-module symbol counts, module presence, member-row multiplicity, imported visibility, and region membership, plus an exact `(module owner, member)` index for current-module visibility. Empty spellings get stable negative inputs. The versioned query key contains only the current module and exact name; its input carries the current resolver facts. Session identity/options mismatches clear the graph, so those bytes do not need to be repeated in each name key. A changed unrelated declaration can therefore leave a NameLookup green, while changes to that spelling's declarations, alias rows, imported/current-module visibility, or region membership change its input. `SourceInput` remains a request-generation guard, not a NameLookup dependency. If index construction is invalid, the resolver skips the query and uses the fused cold classifier. The graph remains a dependency-correctness prototype until counters and retained-edit timings show that graph overhead is repaid. Never retain `DeclId`, `BindingId`, AST pointers, or symbol-table rows.

   `SourceInput` still contains options and declaration-surface bytes for collector/body queries, but NameLookup validates the current resolver facts directly. Its per-name input includes empty-name results, so adding a previously missing symbol or member changes that negative input; removals, alias multiplicity, import visibility, current-module membership, and region-name edits update the same input. `current_module` is part of the stable key, while exact current-module member presence is an input fact. Imported module and selective imported-member visibility are finalized before resolution. The full-check resolver performs this lazily on its first eligible unbound read; the ordinary `resolve_declarations` wrapper uses a disabled context and stays cold. A failed one-shot build uses cold classification for the rest of the request. The key copies exact name bytes and retains no request-owned view or binding row. This query covers only global `(known, module_only)` classification. It does not cache overload selection, call resolution, or the checker result, so a green NameLookup does not skip the body checker. NameLookup nodes have empty dependency lists, so add/remove controls exercise exact-input mismatch, recomputation, and diagnostic parity rather than reverse-edge dependency invalidation. The unindexed missing-name case exits at the O(1) `name_indexed` gate; the separate indexed hidden-member case exercises a chain miss followed by retained hits on body edits.

   Keep this boolean global-name-existence query separate from call/overload resolution: adding an overload can change the selected call while the name remains `Known`. Cache candidate selection only through a query that records its candidate-set and visibility reads. Zig's `Sema.lookupInNamespace` records `(namespace owner, interned identifier)` before probing pub/private maps, so missing results are dependencies too; its update path invalidates that exact name on add/remove/publicity changes and reserves whole-namespace invalidation for broader member-set changes. For Elisa's later `VisibleNameSet`, use a stable namespace/module ID plus session-owned `NameId` even on misses, and fingerprint the exact visible candidate set so unrelated declarations stay green. Likewise, local binder lookup currently uses a table-local `BindingId` tied to `DeclId`; keep it within the current table or reanalyze the body until a stable scope/binder identity exists.

   `resolver_name_classification` stores the composite `(known, module_only)` result for a graph hit, and its fused cold classifier walks the global symbol and member chains once on a miss. The opt-in full-check path lazily builds an exact per-spelling surface over symbols, members, imports, and regions at the first eligible unbound read; requests with no such read skip the pass, while any request that reaches one pays expected-linear `O(import annotations + symbols + members + regions)` work to reconstruct imported-name sets and build both the spelling and `(module, member)` indexes. That setup is included in whole-request timing but not the chain counter. The current call-facts fixture has no import annotations, so its measurements do not qualify this setup term; include an import-heavy fixture before making a setup-cost claim. Valid finalized facts provide region membership before the query, so hits no longer scan `region_names`; invalid or missing facts skip the query and use the cold classifier's region scan. Lexical `bound` scans still run before every lookup, including hits. `value_chain_is_module` routes bare identifiers used as field or namespace-call objects through that same classifier. The `classification_chain_visits` counter counts only symbol/member rows visited by the fused NameLookup cold classifier; direct `name_known` callers such as `Expr.RegionNew`, value-block captures, and flow checks, plus qualified `Expr.Scope` probes through `name_is_module`, `ancestor_names_module`, `two_part_names_module`, and `module_declares_member`, are outside it. Thus the metric does not represent all resolver name-chain work. Metrics-enabled chain walks still test the tracking flag per row. The current source replaces the prior full-identity/path NameLookup key with a versioned `(module,name)` key, removing the former O(unique names × identity/path bytes) duplication. Every active lookup encodes its exact key and input into request-scoped scratch buffers for evaluation; a miss reuses those bytes at commit rather than rebuilding them. The graph copies committed bytes into session-owned storage, so it does not retain request-buffer references. Encoding, hashing, graph probes, and scratch-buffer growth are outside the chain-visit counter and may outweigh saved chain walks for short names. This key reduction has no build or performance qualification. It is safe only while the graph remains session-local and the collision-safe surface input captures every changing resolver fact; identity/options mismatches currently clear the graph. The request context now attempts surface construction once at the first eligible global lookup; it memoizes failed construction so unsupported surfaces do not trigger a repeated prepass. Lexical `bound` scans and surface construction need separate workloads because neither is represented by the chain counter. The surface-index changes have no build, parity, or retained-edit timing qualification, so treat the current counters as path-specific evidence rather than a compile-time result. Keep `bound_last_index`, `record_reference`, and unique-function reference selection on the current table.

   A source review found that a valid finalized surface can classify `(known, module_only)` directly: `forced = builtin(name) || region_name_present`; if not forced and `name_indexed` is false, return `(false,false)`; otherwise `known = forced || imported_visible_member || current_module_member || nonmodule_symbol_count > member_count || nonmodule_symbol_count == 0`, and `module_only = known && module_present && nonmodule_symbol_count == 0`. The current persistent NameLookup stores only this cheap pair, has no dependers, and still builds/hashes the key and exact input; after direct classification replaces chain scans, bypass graph evaluate/commit on valid surfaces unless paired timings show a benefit. A small request-local last-row memo `{module, surface_row, known, module_only}` can catch repeated callee classification after the lexical-binding check; module is required because it changes during one resolver walk. Keep invalid surfaces and no-row names on the cold fallback, and never memoize a lexical binding as a global fact. This is an unmeasured path reduction, not yet a speedup claim. See [`resolve_scope.elisa`](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/semantic/resolve_scope.elisa:429>) and [`semantic_types.elisa`](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/semantic/semantic_types.elisa:489>).

4. **Make one bounded data-layout change at a time.** Elisa already has dense query and edge pools, compact IDs, a free list, and forward/reverse links, so a second analysis-unit table would mostly duplicate existing structure. The current prototype stores the query node's six key/input/result byte-span fields as checked `u32` values. The 8 MiB and 16 MiB pool caps bound logical payloads; they do not hard-bound retained capacity, because array growth and map overhead are estimated and graph clearing truncates storage without releasing capacity. The session epoch eventually releases its region, but retained high-water memory within that epoch still needs measurement or capacity-aware admission. With current incoming-edge validation fields, the estimated node record is 112 bytes instead of 136 bytes with `usize` spans on a conventional 64-bit layout. This saves 24 bytes (about 1.5 MiB at the 65,536-node cap) before allocator and hash-index effects. Compare actual allocated bytes and graph traversal timings before keeping or crediting the change. Treat Zig's implicit-dependee edge and reusable dummy-head scheme as a separate, higher-invariant experiment; its storage savings do not justify changing Elisa's simpler explicit endpoints without measurements.

   A second bounded candidate is the backend's experimental shard-owner map: the logical shard cap is 16, but function/global owner arrays use `i64` with `-1` for unowned. A `u8` representation with `255` as the sentinel would save seven payload bytes per entry on the repeated bridge-inventory and shard-restriction scans. Preserve LLVM ordinal alignment and sentinel behavior, then compare per-shard snapshot hashes and merged-object parity. The Stage1 CLI cache seam still has no restore/publish caller, so this measures backend preparation locality; Elisa Core's separate Go compile-server uses `IncrementalObjectSession.WriteObject`, but that integration does not establish a source-matched end-to-end cache win. See [`codegen_parallel_emit.elisa`](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/backend/codegen_parallel_emit.elisa:80>) and [`preoptimization_shard_cache.md`](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/docs/preoptimization_shard_cache.md:5>).

   There is a more direct active-path version of that experiment in `part_function_owners`: it builds `darray[i64]` immediately before the worker fork, and each forked worker reads the owner for every LLVM function while restricting its module ([owner assignment](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/backend/codegen_parallel_emit.elisa:657>), [worker scan](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/backend/codegen_parallel_emit.elisa:683>), [allocation before fork](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/backend/codegen_parallel_emit.elisa:925>)). Requested jobs are clamped to 1..64, so owner values are 0..63 or `-1`; `u8` with 255 as the unowned sentinel preserves this domain and saves seven payload bytes per function in a read-only table inherited by every worker. Keep instruction weights as `i64`. Verify ordinal alignment, sentinel handling, owner assignment and per-part definition sets, then compare owner-array allocation and restriction time across 1/8/32/64 jobs. The shared backend file is under active edits, so coordinate before changing it. This is a source-derived layout candidate; no runtime gain is established by the byte reduction alone.

5. **Treat code generation as a later, separate cache layer.** A codegen key must include exact LLVM snapshot contents, target machine, LLVM/compiler/runtime identities, optimization and emission options, shard ownership/restriction versions, and relevant profile inputs. Shard bridge names are module-local ordinals and the caller must localize them after each translation unit's complete hit/miss merge before linking it with other units. Any localization or ticket/attestation failure should discard staged hits and use the clean path.

## Elisa prototype from this study

The study's initial worktree had a private query graph in
`src/semantic/incremental_function_facts.elisa`: session-scoped 32-bit query and
edge handles, exact owned keys and values, contiguous query/edge arrays, a free
list, forward plus reverse adjacency, and reusable invalidation scratch. Opaque
handles carry session and graph/request/context generations. Query evaluation
checks exact inputs, dependency identity, dependency result generations, and
Green status; commit replaces dependencies and propagates `PotentiallyDirty` only
when a canonical result changes. The session collector consults `SourceInput`
and `FunctionBodyFacts` nodes and publishes after the authoritative snapshot is
stored. A body hit still requires the old exact declaration-surface and body
proof, restores bytes from the graph after comparing them with the prior typed
facts, and falls back to the existing typed-fact copy on a graph miss. An Oct 18
update also connects `NameLookup` at `Expr.Ident`: the driver reacquires a request
context after collection, and the serial declaration-resolution walk checks the
cached `(known, module_only)` result before scanning global symbol chains. This
path remains opt-in and has no source-matched parity or retained-edit performance
qualification; graph publication, validation, surface copies, and payload
decoding add work. Other declared query kinds, including `FunctionSummary`,
`VisibleNameSet`, `TypeOf`, and `ConstantValue`, still have no callers. Do not
persist `DeclId`, `BindingId`, AST pointers, or `SymbolTable` rows as query
identity.

The current body-fact edge is still coarse: each `FunctionBodyFacts` query depends
on the request's `SourceInput`, and body reuse requires the entire declaration
surface to match. A change to an unrelated declaration therefore cold-scans
otherwise unchanged bodies. Reaching finer-grained invalidation needs a stable
owner manifest with add/update/remove handling, then body queries that record the
name, type, visibility, and other semantic reads that determined each result.
Dropping `SourceInput` without proving those reads would risk stale facts; first
separate body-local syntax fingerprints from declaration-surface dependencies.

A narrow first implementation can reuse the already committed direct-fact range
as an observed-fact inventory for a previously cacheable body. It is not a full
read manifest: it records emitted observations, but not every condition that
made the body eligible, negative/cold observations, or all owner-local shadowing
decisions. The current scanner emits `GlobalRead`, `GlobalWrite`, `DirectCall`,
and `PanicSite` only for supported nonlocal observations; it truncates staged
facts and marks the body uncacheable when it encounters unsupported syntax.
Recompute the current projections for those facts from a complete current
resolver view, not just the collector's top-level global and function-candidate
indexes. One `FunctionFactContext` query per body is a candidate layout: its
exact value can encode the owner's
header/signature and parameter names plus typed projections for that body's
observed names, keeping one graph edge per body instead of one per spelling.
Include parameter names because a body reading a mutable global can become a
local read after a signature edit even when the body bytes and global table are
unchanged. The current collector marks duplicate top-level function names
uncacheable; preserve that boundary until query and prior-record identities
distinguish overload signatures and duplicate headers. Direct-call projections
must cover global shadowing, imported and
nested visible members, externs, exact-name candidate multiplicity, and the
selected candidate's current eligibility. The current collector indexes omit
several of those resolver inputs, and `NameLookup` returns only `(known,
module_only)`, so neither is sufficient to authorize call-fact reuse by itself.
Until the full call target is represented, keep call-bearing bodies on the broad
gate. A smaller first slice can cover only the closed shape of one bare return
whose expression is a self-contained literal, with no local bindings or other
statements; zero emitted facts alone does not prove that shape. For that
explicit complete-empty observation class, a `FunctionBodyFacts` query can use
an empty dependency list and avoid introducing a separate context node. Keep
every other body on the broad `SourceInput` edge until its complete read
manifest is represented. The implementation must bypass the source-surface
gate in both collection and publication for this one class, and its hit marker
must validate the empty dependency set and exact body input without requiring a
`SourceInput` generation. Continue checking current owner uniqueness, header
eligibility, and token spans; a body becoming ineligible must stay cold. Once
the exact binding projection is proven, read/write-only bodies can follow.
Malformed or unsupported manifests must retain the cold path. Evaluate a
context query against current resolver inputs before the body query when that
context is required, and bypass the whole-surface gate only when the manifest
and header projection are complete. Keep the existing typed-fact fallback gated by exact
declaration-surface equality unless it is also validated against the complete
current projection; otherwise a failed graph refresh could replay stale facts
across an unrelated-looking surface edit. Preserve the current transaction
boundary: evaluate existing contexts during collection, but stage new context
values request-locally and commit them only after `ifc_session_store` succeeds;
then publish body queries against the committed context handles. A cold scan
must rebuild its context from the final current direct facts. Exact-source early
hits can reuse existing context handles only when they validate as current; a
missing or stale context must not authorize body reuse. The first request after
changing the body dependency shape should cold-scan and publish the new context.
The retained-session benchmark already has an unrelated
declaration-surface edit; after this path is implemented, graph-on should reuse
the existing unchanged bodies and scan only the new function. Add separate
controls for parameter shadowing and changes to referenced globals or call
targets before claiming fine-grained invalidation.

The latest isolated context prototype has two rollout blockers from static
review: its publisher returns on an oversized `SourceInput` before selecting
per-body dependencies, so a fitting context-only body cannot be published; and
its generic eligible/restored counters cannot distinguish complete-empty-owner
context restores from snapshot fallbacks. Keep source-cap failure local to
broad-dependency bodies, then add dedicated eligibility, context-restore, and
fallback counts plus a declaration-edit control before evaluating the 5%
semantic-work gate. This is prototype review evidence, not a result from the
shared source tree or a benchmark.

The shared graph publisher has a related retry classification issue: a
permanent `SourceInput` size/span rejection occurs before graph mutation, but
the wrapper treats every `false` as aggregate capacity exhaustion, clears the
entire graph, retries the same preflight, and clears again. Separate permanent
key/value admission misses from retryable graph exhaustion so an oversized
translation unit cannot discard useful retained name queries. This is distinct
from allowing a small context-only body to bypass the broad surface cap.

The collector's current indexes are not yet a complete resolver projection:
they are built from top-level functions, globals, and aliases, while the AST and
resolver also represent imports, modules, scoped declarations, externs, and
visible module members. A per-body context built only from those local indexes
must either prove those other declarations cannot affect each accepted read or
mark that body cold. `NameLookup` can help describe current per-spelling
visibility, but its existing `(known, module_only)` result does not establish
direct-call candidate identity or eligibility by itself.

The current semantic projection visitors also have scope and coverage gaps that
must be resolved before they can serve as dependency-complete manifests. The
Global permission fallback pre-collects local names across function scopes and
statement order; its expression/read/call walkers omit executable AST children,
and match-statement guards are not fully visited with pattern-local scope. The
read and call expression visitors also omit `Expr.If`, so a conditional value
containing a global read or a call can be lost even when statement-level `If`
is handled. Other missing runtime child paths include `Slice`, `DictLit`,
`Construct`/`RecordUpdate` field values, `Match`/`Catch` guards and bodies,
`GetElse` recovery, `Comprehension`, `Block`, and `StaticEffectCall` arguments.
Walk runtime `Stmt.Contract` predicates (`requires`, `require`, `assert`,
`ensure`, `ensures`), but exclude proof/frame-only `decreases`, `invariant`,
`changes`, and `preserves`. Match/catch pattern bindings scope their guards and
bodies; a comprehension variable scopes its condition/body, not its iterable.
The backend documents which contract forms execute at runtime in
[`codegen_stmt_expr.elisa`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/backend/codegen_stmt_expr.elisa:22>).
The direct-call visitor also skips an `Expr.Call` callee and assignment-place
evaluation, so nested calls in those executable children do not enter the
transitive effect graph.
The function-value effect-row walk flattens typed locals across
nested scopes, uses the first same-name entry for assignments, skips some
expression forms, and does not visit contract expressions. These can change cold diagnostics or
transitive effect rows independently of caching. In particular, the resolver
visits a local initializer before binding that local, so pre-collecting a later
same-named local can hide a real global read in an earlier initializer or
outside the local's branch. Replace this census with source-order lexical
environments and scope push/pop. Use `BindingId`/owner and
binding kind to prove which binding a read resolved to inside the current
request, then project that owner to a stable module/name or declaration key
plus the relevant mutability/type/eligibility facts. `DeclId` is explicitly
table-lifetime only, so never serialize its raw ordinal as a cross-request
query key. Do the same for resolved callable declarations, with explicit
type/effect-contract inputs; keep a read cold when it cannot be translated to a
complete stable projection instead of adding another whole-function name
census. The Global.Write fallback also treats every assignment as a store,
although `=` introduces a local binding; it must distinguish binding from
`<-`/compound mutation. The cold call-edge visitor resolves a bare call name
without checking whether a parameter/local function value shadows a top-level
function of the same name, which can add a false transitive effect edge. See
[`check_global_permissions.elisa`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/semantic/check_global_permissions.elisa:45>)
and
[`check_fn_value_effect_row.elisa`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/semantic/check_fn_value_effect_row.elisa:795>).
The binding-ID lifetime is documented in
[`binding_identity_types.elisa`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/semantic/binding_identity_types.elisa:4>).

The zero-fact shortcut in `gp_axis_facts` is guarded by
`incremental_current_body_record_index`, which rejects non-cacheable records
and malformed fact spans. An unsupported body therefore falls back to the cold
visitor rather than being treated as a complete empty manifest. Keep that
cacheability/span guard in place if the projection is refactored; this boundary
was confirmed by source review, not a dedicated runtime control. See
[`incremental_current_body_record_index`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/semantic/check_ungranted_panic.elisa:305>)
and
[`gp_axis_facts`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/semantic/check_global_permissions.elisa:326>).

The resolver context is explicitly reacquired for each semantic request because
query handles are session/request/context-generation bound; handles stay out of
the portable snapshot. The first consumer is intentionally the serial
`Expr.Ident` walk in `resolve_expr_walk`; `name_known` also serves region, flow,
value-block, and where-scope paths, which are not covered. Keep `ga_resolve`
separate because global-authority inference has its own scope/import search and
dependencies.

One future graph-scaling concern is invalidation fan-out. `ifq_mark_reverse_closure`
starts a new visitation generation for each root, so multiple changed roots with
overlapping downstream dependents can revisit that shared closure. Zig's
`markTransitiveDependersPotentiallyOutdated` recurses when a unit first enters
`potentially_outdated`; later roots update its pending-dependency count without
walking its dependents again. Stage1 now has a resolver `NameLookup` consumer in addition to collector queries,
but no current profile establishes this fan-out as a hot-path cost. The paired
runner compares graph-off/on classification-chain visits on retained requests;
the total hit counter can still include same-request duplicate callee
classification. Once additional read-site dependencies are connected and
measured, consider a multi-root invalidation pass or request-wide visitation
set, preserving `Dirty` over `PotentiallyDirty` and dependency-generation checks.

The Core name-selection adapter in `src/semantic/incremental_lookup_query.go`
is separate from the live Stage1 resolver path. Core production expression
analysis still invokes `lookupVisibleGlobal` and `lookupVisibleType` directly,
while the adapter is called from tests. Its `lookupSelectionInputs` builder
also regenerates the candidate list and performs current symbol/visibility
lookups before query evaluation. That can validate the selection recipe, but it
does not yet avoid the Core resolver work it models. The smallest useful
integration point is after declaration collection completes and before body
analysis: publish or diff shared exact facts keyed by lookup domain and
qualified name, then let the production evaluator lazily walk candidates in
existing order and read those facts until it finds the winner. It should return
only the canonical selected name and rebind it through the current symbol, type,
or permission table. Missing names must be recorded as dependencies; publish
visibility and alias facts, and preserve present-but-nil global bindings.
Earlier declaration-phase lookups should retain the cold map path.

Selection alone does not remove every related scan. A successful bare value
lookup is followed by wildcard-`using` ambiguity detection, and a failed type
lookup can scan candidates again to diagnose an inaccessible private name.
Those need compatible query facts/results or explicit cold fallbacks. Preserve
local shadowing and the separate enclosing-member lookup rules. The session
database retains inputs and tombstones until removed, so production integration
also needs active query/input retirement or a bounded reset policy as names and
contexts change. Each root evaluation takes the database gate and encodes its
key; an Analyzer-local memo can avoid repeated same-request evaluations, while
batching adaptive resolver reads would require a prepass. Measure these costs
and verify that hits skip the original map probes before claiming acceleration.
The current Core baseline is already a cheap `Symbols` map probe per candidate
(`globalScope` has no parent) and memoizes candidate lists per Analyzer. A
first-candidate hit is therefore especially unlikely to repay a graph query and
the required current-object rebind; prioritize repeated same-request reads or
long candidate-miss prefixes only if profiles show they are material.

A first resolver-coverage audit also found correctness-sensitive direct reads
that should be reconciled before claiming a unified NameLookup path. User-written
type-name classification has direct-first probes in `analyzer_generics.go`,
`analyzer_type_constructor_calls.go`, `analyzer_surface_types.go`,
`analyzer_resolve_types.go`, `analyzer_func_types.go`,
`analyzer_where_refinements.go`, `analyzer_decl_structs.go`, and
`analyzer_region_polymorphism.go`; these can bypass namespace/`using` precedence
or private visibility and can affect type construction or generated region
signatures. `analyzer_foreign_enum.go` already performs visibility-aware lookup
but retains an exact-name fallback with the same risk. After normal expression
resolution, `function_sink_analysis.go`, `optimization_call_facts.go`,
`analyzer_expr_call_args.go`, `region_store_flow_summary.go`,
`region_store_scan_param_writes.go`, `analyzer_storage_view_origins.go`,
`analyzer_param_retention.go`, `progress_safety.go`, and
`analyzer_ensure_reflexive.go` contain bare-global or bare-name fallback reads;
where possible these should consume the canonical resolved symbol rather than
resolve a second spelling independently. Treat these as staged coverage work,
not as evidence that a generic name-selection query can replace every read.

Some direct reads intentionally answer a different question and should remain
separate: `::`-syntax diagnostics test raw namespace membership,
declaration/exports code checks conflicts for the exact name being defined,
trusted-runtime checks verify exact APIs, and rebinds of an already selected
canonical symbol are correct. `extension_methods.go` enumerates and ranks an
overload set, so a first-visible-name query cannot replace it. Likewise,
permission declaration and include-graph traversals are distinct from user
permission-reference selection. Keep the current specialized semantics and
share a selected binding only where the read truly means ordinary source-name
resolution.

The current body-query evaluator now accepts the snapshot byte span and its
already computed body hash. It checks span bounds, uses the fingerprint only as
a prefilter, and still compares exact bytes before a hit. This removes the
evaluation-time temporary body copy and duplicate body hash on a hit; a miss
still copies owned input bytes before query commit. The collector also performs
an exact comparison against the prior snapshot before query evaluation, so
matching bodies may still incur two exact byte walks after snapshot hashing.
Restored-fact counts alone do not show the saved work; measure the full
retained-edit path before claiming a speedup.
Publication also checks request-local restored-body markers. Collection appends
these in function-record order, and publication now lower-bound searches by
record index instead of scanning all markers for every cacheable body.

The compile-session still runs the canonical semantic pipeline after collecting
these facts: `run_semantic_gate_incremental_with_session` passes the snapshot to
`run_semantic_gate_with_snapshot`, which invokes
`check_full_diagnostics_with_incremental_snapshot` and rebuilds the semantic
table through `check_full_into_pipeline`. That pipeline resolves declarations,
runs its parallel pass batches, and calls whole-file checkers; the snapshot only
lets selected walks and projections skip work. Thus
`function_body_facts_restored` counts restored collector facts, not body
semantic analyses or diagnostics avoided. Existing `sem:*` phase timers can
identify which full-pipeline work dominates a retained edit before query
results are persisted at those read sites.

The dense query-node field sequence is estimated at about 112 bytes with
conventional 64-bit alignment after narrowing its six pool spans to `u32` and
including incoming-chain validation fields; the corresponding `usize`-span
sequence would be about 136 bytes. Admission still budgets 128 bytes per node to
include index overhead. The edge
fields total 28 bytes and likely occupy 32 bytes with
8-byte alignment; admission budgets 48 bytes. These are source-level estimates,
not measured object layouts or speedups. The graph already uses compact handles
and pooled records, so measure the checked-u32 span change and evaluate an
implicit dependee only as separate experiments. Zig's packed `AnalUnit`, stable
tracked instruction IDs, and pooled `DepEntry` provide design references, not
proof that a wider structure-of-arrays rewrite would help Elisa.

### Data-oriented comparison with the checked-out Zig source

This comparison is source-backed against the sparse Zig checkout at commit
`4812a98ce`, not a performance comparison. Its `InternPool.zig` uses typed maps
for distinct dependency classes (including `namespace_deps` and the exact
`namespace_name_deps` key of namespace plus name), then stores edges in a dense
`DepEntry` array with reusable `u32` indices and a free list. Each edge links
both into its dependee's invalidation list and its depender's replacement list.
`AnalUnit` packs a kind tag and a `u32` identity into one `u64`. Zig AIR also
uses `MultiArrayList` for instruction columns plus a separate `extra` payload;
the liveness pass obtains tag and data columns separately. The `InternPool`
mutation arena has compilation lifetime because concurrent readers can retain
old hash-map metadata after growth; it is not merely a short-lived scratch arena.

Elisa already uses graph-local `u32` query and edge IDs, dense node/edge arrays,
edge reuse, pooled key/value bytes, and session/request allocation regions.
Its body facts and resolver name surface are partitioned by record category:
function records, direct facts, grants, per-name counts/flags, and owner/name
pairs live in separate dense arrays. The query node itself remains an
array-of-structs, with its status and adjacency links deliberately placed first
for invalidation walks. These are observed layout choices in source; they do
not establish that any of them improve compile time. Elisa's query IDs are
compact handles within the retained graph; they are not Zig-style tracked IR
identities reconciled from one syntax update to the next. The serialized query
key is what finds a reusable node across requests, so AST pointers or transient
declaration-row IDs still must not escape into retained facts.

Elisa's dependency graph is currently session-local. `IncrementalSemanticSession`
owns query keys, nodes, edges, and canonical values, while the sidecar codec
serializes `IncrementalSemanticSnapshot` facts and omits those graph structures.
A process restart can restore portable fact snapshots but must rebuild the query
graph; report same-process warm reuse separately from process-restart warm
reuse. See [`IncrementalSemanticSession`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/semantic/incremental_function_facts.elisa:284>) and the [snapshot codec](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/semantic/incremental_snapshot_codec.elisa:1>).

Two Zig ideas should remain hypotheses until profiled. First, a hot-state
structure-of-arrays split for query invalidation could reduce cache traffic
because a node stride is much larger than the status/link fields read on common
walks; compare graph-walk time and bytes/counters on the same retained-edit
workload before changing it. Second, Zig-style typed reverse maps by semantic
name become useful only when a checker query records a complete typed binding
fact and name edits must find its dependers. Current `NameLookup` nodes instead
have empty dependency lists and validate an exact per-name input on each read;
their cached pair does not identify a binding, so adding reverse maps now would
state without skipping semantic work. The live driver now keeps parser-owned
source bytes and ASTs in `@source`, while request scratch and semantic-output
regions hold temporary data and collected snapshots. This follows the parser's
current ownership contract: AST nodes borrow source text, and the parser API is
not generic over an arbitrary child request region. R43's attempted child-region
version failed Stage0 type checking at those parser calls; the live driver has
since restored parser-owned data to `@source`. R45 also reported an inferred
region escape when a disabled lookup context was returned and pushed by value.
The live semantic API now pushes that context in place, and R46's captured
revision failed on the helper's effect-syntax typo before semantic checking.
R47 includes the in-place helper and corrected syntax but has not finished, and
the live tree has since changed in multiple source and proof inputs. Treat its
eventual findings as snapshot-specific until a seed captures the final sources.
Thus the latest lifetime boundaries remain unvalidated; do not infer an RSS
reduction yet. The current line map is explicitly published into the
lexer's reusable process-owned buffer. The sidecar snapshot and incremental
query graph have separate longer lifetimes and must own or copy any retained
bytes. See
[`elisac_incremental_server.elisa`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/driver/elisac_incremental_server.elisa:66>),
[`ast_nodes.elisa`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/parser/ast_nodes.elisa:4>),
[`name_store.elisa`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/parser/name_store.elisa:7>), and
[`lexer_line_map_cache.elisa`](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/lexer/lexer_line_map_cache.elisa:18>).

The smallest data-layout change already present in Elisa and worth qualifying is
the `NameLookup` input's six-boolean flags byte: it reduces the exact encoded
input from 22 to 17 logical bytes. Benchmark it against the prior encoding with
identical lookup results and diagnostics, recording committed input bytes,
bytes hashed/compared, retained value-pool capacity, allocations, and both
lookup-loop and full-request time. The expected storage delta is small, so keep
it only with a demonstrated memory or timing benefit. This is separate from
bypassing `NameLookup` graph evaluation on a valid surface, which tests query
overhead rather than layout.

The smallest relevant Elisa experiment is to bypass persistent `NameLookup`
evaluate/commit on valid finalized surfaces and compute its already-reviewed
`(known, module_only)` formula directly from the exact surface row, retaining
the cold fallback for invalid surfaces. The current read-site query only caches
that pair, has no dependers, and on a miss still walks symbol/member chains;
the experiment would test whether the graph's key/input encoding and probes
repay avoided chain scans compared with direct per-name classification. Compare
graph-on and direct-surface modes on separate unique-name and repeated-name
fixtures: unique names expose retained cross-request hits, while repeated names
expose same-request duplicate hits. Include an import-heavy setup arm that varies
import-annotation count independently of symbols, members, and regions. Keep
surface construction in both modes and record wall time, lookup count, chain
rows, query nodes/input bytes, hash/compare work, and graph operations. Parity is
a prerequisite; the result remains unmeasured until that paired run.

Use the source-derived formula stated in recommendation 3, including its exact
built-in and region-name forced cases; it is not yet implemented as the
direct-mode arm. Keep local-binding checks ahead of it, and fall back to the
cold resolver if surface finalization or exact-row lookup is invalid. First
compare the direct arm with the cold result and diagnostic stream on every
listed edge case, then compare its timing with graph evaluation.

Measure the lookup loop, semantic request, and full retained request separately;
also record surface-build time/allocations and retained node/key/value capacities,
since graph clearing can leave pool capacity allocated. Require exact
`(known, module_only)` and diagnostic parity for missing names, declaration
additions/removals, imports, aliases, duplicate names, module-only names, region
names, built-ins, local shadows, invalid surfaces, and session resets. A graph
hit counter alone cannot show that semantic checking was skipped: this query
only classifies names, while `FunctionBodyFacts` still depends on broad
`SourceInput` and does not bypass the checker.

The backend also exposes an owned configured-target descriptor in
`src/backend/codegen_target_machine.elisa`. It captures machine and module
triples, machine and module data layouts, CPU, and feature strings, and reports
unsupported when the module and machine disagree. Native artifact discovery in
`src/driver/elisac_artifact_identity.elisa` can locate the executable and the
image containing `LLVMContextCreate` on Linux and macOS. It intentionally does
not produce mapped-image digests: path hashing alone cannot prove which bytes
the process loaded. The Stage1 CLI's O0 shard cache still has no driver caller.
Elisa Core's separate Go compile-server now calls
`IncrementalObjectSession.WriteObject` for named incremental object requests,
but the saved integration and benchmark evidence is revision-mismatched and
does not establish current-tree end-to-end speedup. These are distinct paths.

The working repository's current status and measured baselines remain in [incremental compilation design](incremental_compilation.md) and [pre-optimization shard cache design](preoptimization_shard_cache.md). This reference study does not qualify the full incremental-compilation objective and did not run the test suite.

## Follow-up findings (2026-10-18)

Elisa Core's native object cache assigns incremental shards by a stable hash of
each function name in [incremental_clone.cpp](</Users/torarinvikbjarko/Documents/Coding%20Projects/Go%20projects/Elisa-core/compiler/src/backend/incremental_clone.cpp>);
the instruction-weight prefix partitioner in
[parallel_emit.c](</Users/torarinvikbjarko/Documents/Coding%20Projects/Go%20projects/Elisa-core/compiler/src/backend/parallel_emit.c>)
is used by ordinary one-shot emission. Therefore a body edit does not move unchanged functions
between incremental shards. A request-local clone-plan prototype was measured
with three alternating before/after pairs. It preserved the expected cache
behavior (8 reused / 0 emitted for unchanged input; 7 reused / 1 emitted after a
body edit). The unchanged median rose from 117.08 ms to 140.61 ms, with noisy
three-pair timing. The previously reported body-edit medians (157.85 ms to
136.75 ms) are withdrawn as performance evidence: the edit fixture grew
`work0` by 16 terms per timed iteration, and separately calibrated runs could
therefore average different module sizes. The raw values remain in the archive
only. Plan preparation itself was about 0.2 ms. The runtime prototype was
discarded; a fixed-size, same-length body-edit rerun is still needed before
comparing edit timings. The
raw [summary](/Users/torarinvikbjarko/Documents/Coding%20Projects/Go%20projects/Elisa-core/build/verification/incremental-native-clone-plan-20261018/summary.json)
and archived harness remain available. This does not establish a native-cache
speedup from hoisting the repeated clone preflight.

The persistent semantic server has an unmeasured request-memory boundary in
[`elisac_incremental_server.elisa`](</Users/torarinvikbjarko/Documents/Coding%20Projects/Elisa%20Projects/Elisa-compiler/src/driver/elisac_incremental_server.elisa:73>).
It opens `request_scratch` around source processing, but the parser and AST
types still use global `@source`; the current Stage1 seed rejects the request
region at parser calls. Only a passing lifetime check can establish that
per-request storage is reclaimed. A repeated-edit memory control must then
measure retained high-water capacity.

The Core parser's
[`functionBodyNeedsAutoRegion`](</Users/torarinvikbjarko/Documents/Coding%20Projects/Go%20projects/Elisa-core/compiler/src/parser/parser_statements_parseforheaderexpr_to_parsebracematchstructpatternarg.go:525>)
has a parent/current synthetic A/B using five 100 ms samples per case. For nested
`ExprBlock`s at depth 12, median time fell from 3.31 ms to 36.2 us, with
allocations from 294,912 B / 12,288 allocs to 1,456 B / 44. Mixed nested blocks
at depth 12 fell from 665 ms to 130 us, with approximate allocations from 51.0
MB / 2,125,765 allocs to 2,320 B / 80. Statement-only depths 16/32/64 instead
became about 2.0x / 1.9x / 1.9x slower, with identical allocation counts and
bytes. The result supports the `ExprBlock` memoization for those synthetic
shapes and exposes a separate statement-only cost; it does not establish a
whole-parser speedup. The current source still repeats full reflective scans
for auto allocations and constructed-struct forwarding on recursive statement
lists, before consulting its `ExprBlock` memo. A postorder list summary or
predicate visit counters are the next useful steps, preserving `RegionStmt` and
`InStoreStmt` boundaries.

These measurements used parent parser source at
`39c7f806f58f2b5a3ba2abd46b59c5b74312f1be` (SHA-256
`b22967b5fd2e102038f91982677b9b2521e507ed77fc01eff6d0d3ddd1c66e67`), current
dirty parser SHA-256
`551ab16b9bb63030eccd7fcb2074bebf88b15c3e272ff3c826512a93ff77f3b9`, and
fixture SHA-256
`0d577dd441fdfd50a2064d9794886eb82efaacf2b84468c1eb5d6961f1138ea9`. The
benchmark command was `go test -run='^$' -bench='^BenchmarkAutoRegion'
-benchmem -benchtime=100ms -count=5 ./src/parser`. Its transcript was
reconstructed from captured command output without a rerun; the approximate
parent allocation figures remain explicitly approximate. See the
[transcript](/tmp/auto_region_parser_ab_20261018.log), SHA-256
`7480ec5d7af186153aac12b8ee9e5037893784851edcebf6510bd0dd12bb5be9`.

The Core parameter-store visitor at
[analyzer_param_store_targets.go](</Users/torarinvikbjarko/Documents/Coding%20Projects/Go%20projects/Elisa-core/compiler/src/semantic/analyzer_param_store_targets.go>)
also needs binding-scoped source and target backing-store provenance; its current
same-spelling shadow fixture can pass without proving renamed-local provenance.
Add renamed-source, global-backed-local-container, and simple-rebind controls
before trusting those summaries.

Gate L's Stage1 seed used the current-Core bootstrap binary but failed before
producing an object. Its complete path/message diagnostic multiset matches Gate
H exactly (25,541 diagnostics: 25,400 warnings and 141 nonwarnings); Gates I and
K each had 25,540, with one fewer `scan_instruction` postcondition failure.
The `easm_compose_span` proof failures remained in L. After the L log completed
at 17:50:25, the live `easm_compose_text.elisa` changed at 17:50:49 from local
`ComposeSpan` temporaries to inline struct literals, so Gate L does not qualify
that newer edit. A fresh gate must use the current frozen source and should
compare full diagnostic multisets, not only the touched function's error count.

Gate N isolated a nullable disabled session in
`incremental_function_facts.elisa` but also failed before producing Stage1. Its
normalized diagnostics improve over K by exactly one nonwarning: the inferred
region store into the disabled session's `output` container disappears. The
arg-14 inferred-region store and aggregate-return-local-reference diagnostics
remain. This is a partial diagnostic improvement, not a lifetime fix or source
qualification. A separate review correction confirmed `anchor.name` is consumed
when replaying self-assignment diagnostics; the collector's `source` input and
returned snapshot are both `@output`. Therefore an unannotated helper parameter
alone does not prove a dangling reference. Any next lifetime change should
establish whether the snapshot can outlive `source` at its callers or give the
anchor owned spelling storage. Gate N log SHA-256:
`f8d407ee99da4ed87958018de9d6d289b0ac3e9084bf1e7732c10d60aad17c30`.

## Source checkout manifest

All checkouts are shallow and sparse to keep the local source study bounded. Revisions were read on 2026-10-18.

| Project | Checkout | Revision |
| --- | --- | --- |
| Zig | `zig`, `src/` and `test/standalone/` | `4812a98ce535e5c3f27c081b94153612cd4817ac` |
| Rust | `rust`, selected compiler crates | `33295d734447c7a2c22c44190f11bce6164a035a` |
| LLVM/Clang | `llvm-project`, Clang/LLVM/LTO/LLD paths | `70a4494e073f57eebb77931a5a2e59f6b5e9e13a` |
| GCC | `gcc`, `gcc/` | `9a00f0797c90485cd70ac86a8751c9565c3979dd` |

## Per-name fact table rollout sketch

A follow-up semantic review proposes indexing exact session-owned spellings as
`(ResolverEnvId:u32, NameId:u32)`, with a compact row of symbol/nonmodule/member
counts plus visibility flags. Keep exact spelling bytes behind `NameId`; do not
use hash-only identity. Keep overload candidates in a separate ordered flat pool
with start/count ranges, because global name classification and overload
selection are different facts. Populate rows alongside existing symbol,
member, alias, region-name, and import registration, then remove the separate
whole-surface finalization pass. Preserve duplicate-member multiplicity and exact
`(owner,name)` visibility; import and alias changes need reverse indexes for
bounded fanout. Missing names need stable empty facts so a later declaration
invalidates that exact key.

For graph reuse, the existing NameLookup helper must expose its query handle and
record per-function read edges; its current dependency list is empty. Evaluate
fact providers before dependers and publish staged rows only with the accepted
snapshot. The main blocker is stable declaration identity: current snapshots
carry whole-surface bytes rather than declaration-level contributions. Until a
safe row-level declaration diff exists, rebuild or fall back on declaration
surface changes. Measure row/candidate bytes, producer probes, finalization time
removed, changed-name count, reverse-closure work, and warm body-only and
unrelated-declaration request time. The current one-pass surface build may still
win for small translation units, so keep this as a measured rollout hypothesis.

## Core owner census on budget exhaustion

The Core owner preflight returns `complete=false` with a candidate prefix when
its work-byte budget is exhausted
([`incremental_owner_candidates.go`](</Users/torarinvikbjarko/Documents/Coding%20Projects/Go%20projects/Elisa-core/compiler/src/semantic/incremental_owner_candidates.go:395>)).
`Analyze` admits only known retained candidates in that partial mode, but its
later retirement loop removes every prior owner missing from the partial
`current` set
([`incremental_analysis_session.go`](</Users/torarinvikbjarko/Documents/Coding%20Projects/Go%20projects/Elisa-core/compiler/src/semantic/incremental_analysis_session.go:549>)).
The unseen suffix has unknown liveness. The Core owner's current working patch
preserves every prior key before retirement when `partialCandidates` is true;
this admits no new suffix owners, and a later complete census can retire keys
that are truly absent. Exact source validation still gates product reuse. This
change has not yet been qualified with a targeted partial-census regression or
build measurement. Add a case with a retained function beyond the budgeted
prefix, then edit it and check warm reuse against cold diagnostics; also track
stale-entry retention until a later complete census.
