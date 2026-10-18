# Compiler incrementality reference study

**Research snapshot:** 2026-10-18  
**Purpose:** extract concrete incremental-compilation and data-layout ideas for Elisa from Zig, rustc, Clang/LLVM, and GCC. Source checkouts and generated comparison artifacts are under the ignored `build/research/compiler-sources/` directory.

## What the references do

### Zig: typed dependencies and compact compiler data

The current Zig checkout represents analysis units with compact typed handles (`AnalUnit` is a packed 64-bit value) and stores interned items as a small tag plus a 32-bit payload. The intern pool tracks distinct dependency kinds: source hashes, declaration values and types, inferred error sets, type layout, defaults, files and embeds, namespace contents, name existence, and memoized state. Distinguishing these facts lets an edit invalidate only analyses that depended on the changed fact. Name-existence dependencies matter for negative lookups: adding a declaration can invalidate a prior “not found” result even though no old declaration changed.

Dependency edges are indexed in both directions. A depender owns a compact linked edge chain; reanalysis can remove and replace all of its old outgoing edges. Edge slots are recycled. The update path marks transitive dependents as potentially outdated, waits until their dependencies have been checked, then prioritizes ready functions so useful code generation can proceed early. The frontend snapshots file state before scheduling work and avoids applying dependency invalidations when a failed frontend update makes the new analysis unreliable.

Zig also separates syntax tracking from semantic invalidation. During an update it maps old ZIR instructions to new locations; when an instruction cannot be tracked, it marks that instruction's source-hash dependency outdated. Semantic dependers move through a potentially-outdated state with a count of unresolved dependencies. As dependencies are confirmed current or outdated, the count falls and ready analysis units are queued. This lets the compiler wait for upstream results before reanalyzing dependers, while prioritizing ready functions for code generation. See [old-to-new ZIR tracking and failed mappings](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L807-L875), [dependency-count invalidation and ready-unit scheduling](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu.zig#L3212-L3420), and [tracked namespace-name invalidation](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L936-L992).

The concrete data layout is worth comparing with Elisa. Zig's `AnalUnit` is a packed 64-bit value containing a 32-bit kind and 32-bit ID. `TrackedInst` uses stable 32-bit IDs across an update and maps them to current ZIR locations; a lost mapping has an explicit sentinel. A `DepEntry` stores a depender handle and three 32-bit adjacency links. Its dependency key is implicit in the per-kind dependee-head maps, so it does not duplicate that endpoint in every edge. Zig also gives namespace-name existence its own dependency key, so an earlier missing-name result can be invalidated when that name is added. See [`AnalUnit` and tracked instruction IDs](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L137), [`AnalUnit`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L422), [`namespace_name` dependency heads](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L75), [`Dependee.namespace_name`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L746), [`NamespaceNameKey`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L918), Zig's [namespace name lookup dependency](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Sema.zig#L6026-L6045), [`DepEntry` plus edge insertion/removal](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L925), and [name-change invalidation](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L978-L992).

Elisa already uses compact 32-bit query and edge IDs, dense node/edge pools, recycled edge slots, forward and reverse adjacency, and a reusable invalidation worklist. Its current edge has two 32-bit endpoints, three 32-bit links, and a 64-bit observed result generation: 28 bytes of fields, likely 32 bytes with conventional 8-byte alignment. Zig's `DepEntry` omits the dependee endpoint because typed dependee-head maps retain that identity, and uses dummy heads when removing a list head. That pattern could reduce Elisa's edge payload, but it would need to preserve the current result-generation check and be evaluated against additional indexing and update costs. Zig's `potentially_outdated` and `outdated` maps also track unresolved dependency counts and prioritize ready functions after upstream dependencies settle; Elisa has `PotentiallyDirty` status but no ready-unit queue.

The useful data-oriented transfer is stable integer handles, typed dependency identities, dense pooled records, and hot fields placed for the traversal that consumes them. Zig also uses maps where dynamic dependency keys and scheduling need them; its source does not imply that every compiler table should become structure-of-arrays. Elisa's graph now has a private `SourceInput`/`FunctionBodyFacts` evaluate-and-commit caller, but the body-query hit overlaps the prior exact-body/surface reuse path and still validates the canonical payload against the previous typed facts. Its graph integration is experimental groundwork, not measured acceleration. The query node now stores its six key/input/result byte-span fields as checked `u32` values. With the current incoming-edge validation fields, the source-level estimate is 112 bytes per node instead of 136 bytes with `usize` spans on a conventional 64-bit layout. That saves 24 bytes (about 1.5 MiB at the 65,536-node cap) before allocator and index effects. This remains an unmeasured layout estimate; measure query-node allocation and retained-edit traversal before attributing a memory or speed improvement.

Zig's data-oriented choices extend beyond the dependency graph. `InternPool.Local` partitions mutable interned storage by thread, and its `List(Elem)` wrapper uses `std.MultiArrayList(Elem)` so each field occupies a contiguous array; typed integer handles keep references stable as those arrays grow. Mutation metadata is separate from the reader-visible state, cache-line aligned, and growth publishes the new backing storage atomically. The compact `Nav.Repr` is documented as 30 bytes, with flags packed into 16 bits; its representation is deliberately optimized for the common analysis-backed case, which the source reports as about 74% of navs. These choices support parallel access and selective field scans in large compiler tables. Elisa's current invalidation walk reads query status plus reverse-edge endpoints/links, while dependency validation reads edge endpoints and observed generations together, so a blanket SoA rewrite has no established advantage. Prefer measuring bytes and field-access patterns first; a narrower, bounded field such as the edge's observed result generation is a simpler experiment than splitting the whole graph.

Zig's incremental persistence is not a complete template to copy. The current source still has save-state TODOs for errors, namespaces, declarations, and linker state. The source study supports borrowing its in-memory dependency model and compact data layout selectively, not adopting its whole cache format.

Sources: [Zig `InternPool.zig` at the inspected commit](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig), [Zig `Zcu.zig`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu.zig), [frontend update path in `PerThread.zig`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig), [cache save-state path](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Compilation.zig).

### Rust: red-green query evaluation

rustc records query dependencies and fingerprints. When an input changes, dependent queries are reconsidered. A recomputed query can still be marked green if its result fingerprint matches the prior result, preventing unchanged downstream work from being invalidated. At the inspected revision, `try_mark_green` recursively checks an old node's dependencies; if a dependency is still unknown, it tries to force that query from its stable dep-node key. If the key cannot be forced, rustc returns `None` so the caller recomputes. The recorded dependency order matters because control flow can change which queries are read. Persistent data is selected by query/result policy rather than serializing every in-memory compiler object indiscriminately. Code-generation work products are tracked as a separate artifact layer.

The serialized graph stores node keys, value fingerprints, and dependency edges, then builds its node-to-index reverse map lazily per query kind on the first lookup. A successful green check promotes the old node and its edges into the current graph; disk-backed query values needed in the new cache can be loaded in a later promotion pass. These steps trade eager indexing and eager value loading for incremental maintenance, but they still have a cost on no-change builds. Measure reverse-index construction, green-node promotion, and cache promotion alongside queries skipped before treating a high green count as a speedup. See [`LazyNodeIndex` and its profiled per-kind map](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/serialized.rs#L115-L185), [serialized graph lookup](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/serialized.rs#L234-L248), [`try_mark_previous_green` edge promotion](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/graph.rs#L947-L1034), and [cache promotions](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/graph.rs#L1065-L1089).

For Elisa, the useful rule is: propagate change from semantic result fingerprints, not merely from changed source text or a changed dependency. Recompute at the right boundary, compare the canonical result, and stop invalidation when that result is unchanged. Query dependencies must capture the reads that determined the result, including resolution candidate sets and failed lookups. Elisa now has a request-scoped `NameLookup` query at the serial `Expr.Ident` read site, alongside collector `SourceInput` and `FunctionBodyFacts` queries. It caches only `(known, module_only)` from exact surface facts rebuilt from the current symbol table; it does not skip body checking or derive persistent per-name inputs from declaration deltas. Elisa also lacks rustc's generalized force-from-dep-node scheduling path, so this resolver query remains a narrow read-site prototype rather than reuse of semantic analysis units.

Sources: [Rust incremental compilation guide](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation.html), [detailed red-green explanation](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation-in-detail.html), [`try_mark_green` implementation at the inspected commit](https://github.com/rust-lang/rust/blob/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_middle/src/dep_graph/graph.rs#L909-L1000), [rustc incremental implementation](https://github.com/rust-lang/rust/tree/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_incremental).

### Clang/LLVM: front-end reuse and artifact boundaries

Clang precompiled headers and modules serialize AST state and lazily load declarations and types. A precompiled preamble can let an editor reparse the edited portion of a source file while reusing the unchanged prefix and includes. These mechanisms target front-end work and are separate from object reuse.

ThinLTO separates a summary index from per-module backends. The thin link can reason over summaries instead of loading every full module. Backend results use a cache key derived from module/import-export decisions and code-generation configuration; a hit is checked before parsing and optimizing the full module. This is a useful boundary lesson for Elisa: key artifacts by the exact canonical input snapshot and all target/backend settings that affect the object. A path, source timestamp, or LLVM version string alone is not enough.

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

1. **Connect the existing O0 shard artifact cache as a narrow production milestone.** The backend already has APIs for preparing verified logical shards and emitting a cache miss from the exact snapshot; the Stage1 helper already provides content-addressed tickets and atomic object bundles. The driver does not connect them yet. Start with plain native `-O0` object output, exact loaded-toolchain and target recipe validation, deterministic logical merge order, and a cold fallback for unsupported inputs. Keep it opt-in until clean/warm parity, one-shard invalidation, corruption recovery, and end-to-end measurements pass. This is the smallest existing boundary that can avoid native object generation without trusting persisted semantic results.

2. **Move reuse into real semantic read sites and qualify the existing host.** One-shot CLI compilation still uses a disabled session, while the opt-in `compile-session` and `semantic-session` hosts keep an enabled session across requests. Query-graph evaluation within those hosts is separately opt-in with `ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH=1` because retained arena capacity is not yet bounded. `compile-session` still rereads and reparses the current source, reruns semantic checking, and rebuilds and emits LLVM state. The graph serves `SourceInput`, `FunctionBodyFacts`, and an opt-in `NameLookup` query at serial `Expr.Ident` classification. The body-fact route still requires exact old-surface/body proof. NameLookup uses finalized exact per-name surface facts rather than a whole-file `SourceInput` edge, so unrelated declaration changes can leave it green while changes to the matching symbol, member, visibility, or region facts change its input. The next step is to qualify the read-site path on retained edits through object emission while keeping current diagnostics authoritative; the surface-index changes have no build, parity, or benchmark qualification.

3. **Refine the first real dependency at a semantic read site.** The initial translation-unit `Expr.Ident` slice is wired into the serial resolver walk: it queries and caches the composite `(known, module_only)` classification before global symbol/member-chain scans, while preserving local binding and region-name behavior. The full-check pipeline finalizes a collision-safe exact-spelling surface after declarations, aliases, imports, and region annotations are collected, before `resolve_declarations`; that serial walk precedes the parallel pass batches and remains the safest first consumer of the mutable session graph. The surface stores the explicit `name_indexed` gate, total and non-module symbol counts, module presence, member-row multiplicity, imported visibility, and region membership, plus an exact `(module owner, member)` index for current-module visibility. Empty spellings get stable negative inputs. The versioned query key contains only the current module and exact name; its input carries the current resolver facts. Session identity/options mismatches clear the graph, so those bytes do not need to be repeated in each name key. A changed unrelated declaration can therefore leave a NameLookup green, while changes to that spelling's declarations, alias rows, imported/current-module visibility, or region membership change its input. `SourceInput` remains a request-generation guard, not a NameLookup dependency. If index construction is invalid, the resolver skips the query and uses the fused cold classifier. The graph remains a dependency-correctness prototype until counters and retained-edit timings show that graph overhead is repaid. Never retain `DeclId`, `BindingId`, AST pointers, or symbol-table rows.

   `SourceInput` still contains options and declaration-surface bytes for collector/body queries, but NameLookup validates the current resolver facts directly. Its per-name input includes empty-name results, so adding a previously missing symbol or member changes that negative input; removals, alias multiplicity, import visibility, current-module membership, and region-name edits update the same input. `current_module` is part of the stable key, while exact current-module member presence is an input fact. Imported module and selective imported-member visibility are finalized before resolution. The full-check pipeline performs this finalization; the ordinary `resolve_declarations` wrapper uses a disabled context, and nonstandard callers without a finalized surface stay cold. The key copies exact name bytes and retains no request-owned view or binding row. This query covers only global `(known, module_only)` classification. It does not cache overload selection, call resolution, or the checker result, so a green NameLookup does not skip the body checker. NameLookup nodes have empty dependency lists, so add/remove controls exercise exact-input mismatch, recomputation, and diagnostic parity rather than reverse-edge dependency invalidation. The unindexed missing-name case exits at the O(1) `name_indexed` gate; the separate indexed hidden-member case exercises a chain miss followed by retained hits on body edits.

   Keep this boolean global-name-existence query separate from call/overload resolution: adding an overload can change the selected call while the name remains `Known`. Cache candidate selection only through a query that records its candidate-set and visibility reads. Zig's `Sema.lookupInNamespace` records `(namespace owner, interned identifier)` before probing pub/private maps, so missing results are dependencies too; its update path invalidates that exact name on add/remove/publicity changes and reserves whole-namespace invalidation for broader member-set changes. For Elisa's later `VisibleNameSet`, use a stable namespace/module ID plus session-owned `NameId` even on misses, and fingerprint the exact visible candidate set so unrelated declarations stay green. Likewise, local binder lookup currently uses a table-local `BindingId` tied to `DeclId`; keep it within the current table or reanalyze the body until a stable scope/binder identity exists.

   `resolver_name_classification` stores the composite `(known, module_only)` result for a graph hit, and its fused cold classifier walks the global symbol and member chains once on a miss. The opt-in full-check path eagerly builds an exact per-spelling surface over symbols, members, imports, and regions on every graph-active request, even when the file has no NameLookup reads; this scans O(symbols + members + regions) and builds both the spelling and `(module, member)` indexes. That setup is included in whole-request timing but not the chain counter. Valid finalized facts provide region membership before the query, so hits no longer scan `region_names`; invalid or missing facts skip the query and use the cold classifier's region scan. Lexical `bound` scans still run before every lookup, including hits. `value_chain_is_module` routes bare identifiers used as field or namespace-call objects through that same classifier. The qualified `Expr.Scope` path still probes module prefixes and members directly through `name_is_module`, `ancestor_names_module`, `two_part_names_module`, and `module_declares_member`; those reads are outside both `NameLookup` and the counter, which counts only chain rows visited by the fused classifier. Metrics-enabled chain walks still test the tracking flag per row. The current source replaces the prior full-identity/path NameLookup key with a versioned `(module,name)` key, removing the former O(unique names × identity/path bytes) duplication. Every active lookup encodes its exact key and input into request-scoped scratch buffers for evaluation; a miss reuses those bytes at commit rather than rebuilding them. The graph copies committed bytes into session-owned storage, so it does not retain request-buffer references. Encoding, hashing, graph probes, and scratch-buffer growth are outside the chain-visit counter and may outweigh saved chain walks for short names. This key reduction has no build or performance qualification. It is safe only while the graph remains session-local and the collision-safe surface input captures every changing resolver fact; identity/options mismatches currently clear the graph. Lazy surface construction on first global lookup is a candidate if measurements show eager setup erases lookup savings, with failed construction memoized so unsupported surfaces do not trigger a repeated prepass. Lexical `bound` scans and surface construction need separate workloads because neither is represented by the chain counter. The surface-index changes have no build, parity, or retained-edit timing qualification, so treat the current counters as path-specific evidence rather than a compile-time result. Keep `bound_last_index`, `record_reference`, and unique-function reference selection on the current table.

4. **Make one bounded data-layout change at a time.** Elisa already has dense query and edge pools, compact IDs, a free list, and forward/reverse links, so a second analysis-unit table would mostly duplicate existing structure. The current prototype stores the query node's six key/input/result byte-span fields as checked `u32` values. The 8 MiB and 16 MiB pool caps bound logical payloads; they do not hard-bound retained capacity, because array growth and map overhead are estimated and graph clearing truncates storage without releasing capacity. The session epoch eventually releases its region, but retained high-water memory within that epoch still needs measurement or capacity-aware admission. With current incoming-edge validation fields, the estimated node record is 112 bytes instead of 136 bytes with `usize` spans on a conventional 64-bit layout. This saves 24 bytes (about 1.5 MiB at the 65,536-node cap) before allocator and hash-index effects. Compare actual allocated bytes and graph traversal timings before keeping or crediting the change. Treat Zig's implicit-dependee edge and reusable dummy-head scheme as a separate, higher-invariant experiment; its storage savings do not justify changing Elisa's simpler explicit endpoints without measurements.

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

The current body-query path also copies each body span into a temporary byte
array before graph evaluation and publication (`ifq_snapshot_span_copy`), then
hashes it and performs exact byte comparison against the retained input. The
collector has already established exact old-body equality before this step, and
publication repeats the copy path. This adds allocation and several O(body
bytes) passes to a cache hit, so restored-fact counts alone do not show saved
work. A future span-based evaluate/commit path can hash and compare directly
against the snapshot's owned bytes while retaining exact equality as the
collision check; measure the end-to-end retained-edit path before adopting it.
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

The backend also exposes an owned configured-target descriptor in
`src/backend/codegen_target_machine.elisa`. It captures machine and module
triples, machine and module data layouts, CPU, and feature strings, and reports
unsupported when the module and machine disagree. Native artifact discovery in
`src/driver/elisac_artifact_identity.elisa` can locate the executable and the
image containing `LLVMContextCreate` on Linux and macOS. It intentionally does
not produce mapped-image digests: path hashing alone cannot prove which bytes
the process loaded. The O0 shard cache still has no driver caller, so no object
reuse or end-to-end speedup is established by these foundations.

The working repository's current status and measured baselines remain in [incremental compilation design](incremental_compilation.md) and [pre-optimization shard cache design](preoptimization_shard_cache.md). This reference study does not qualify the full incremental-compilation objective and did not run the test suite.

## Source checkout manifest

All checkouts are shallow and sparse to keep the local source study bounded. Revisions were read on 2026-10-18.

| Project | Checkout | Revision |
| --- | --- | --- |
| Zig | `zig`, `src/` and `test/standalone/` | `4812a98ce535e5c3f27c081b94153612cd4817ac` |
| Rust | `rust`, selected compiler crates | `33295d734447c7a2c22c44190f11bce6164a035a` |
| LLVM/Clang | `llvm-project`, Clang/LLVM/LTO/LLD paths | `70a4494e073f57eebb77931a5a2e59f6b5e9e13a` |
| GCC | `gcc`, `gcc/` | `9a00f0797c90485cd70ac86a8751c9565c3979dd` |
