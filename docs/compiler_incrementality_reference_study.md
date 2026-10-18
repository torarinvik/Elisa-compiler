# Compiler incrementality reference study

**Research snapshot:** 2026-10-18  
**Purpose:** extract concrete incremental-compilation and data-layout ideas for Elisa from Zig, rustc, Clang/LLVM, and GCC. Source checkouts and generated comparison artifacts are under the ignored `build/research/compiler-sources/` directory.

## What the references do

### Zig: typed dependencies and compact compiler data

The current Zig checkout represents analysis units with compact typed handles (`AnalUnit` is a packed 64-bit value) and stores interned items as a small tag plus a 32-bit payload. The intern pool tracks distinct dependency kinds: source hashes, declaration values and types, inferred error sets, type layout, defaults, files and embeds, namespace contents, name existence, and memoized state. Distinguishing these facts lets an edit invalidate only analyses that depended on the changed fact. Name-existence dependencies matter for negative lookups: adding a declaration can invalidate a prior “not found” result even though no old declaration changed.

Dependency edges are indexed in both directions. A depender owns a compact linked edge chain; reanalysis can remove and replace all of its old outgoing edges. Edge slots are recycled. The update path marks transitive dependents as potentially outdated, waits until their dependencies have been checked, then prioritizes ready functions so useful code generation can proceed early. The frontend snapshots file state before scheduling work and avoids applying dependency invalidations when a failed frontend update makes the new analysis unreliable.

The concrete data layout is worth comparing with Elisa. Zig's `AnalUnit` is a packed 64-bit value containing a 32-bit kind and 32-bit ID. `TrackedInst` uses stable 32-bit IDs across an update and maps them to current ZIR locations; a lost mapping has an explicit sentinel. A `DepEntry` stores a depender handle and three 32-bit adjacency links. Its dependency key is implicit in the per-kind dependee-head maps, so it does not duplicate that endpoint in every edge. Zig also gives namespace-name existence its own dependency key, so an earlier missing-name result can be invalidated when that name is added. See [`AnalUnit` and tracked instruction IDs](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L137), [`AnalUnit`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L422), [`namespace_name` dependency heads](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L75), [`Dependee.namespace_name`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L746), [`NamespaceNameKey`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L918), Zig's [namespace name lookup dependency](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Sema.zig#L6026-L6045), [`DepEntry` plus edge insertion/removal](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig#L925), and [name-change invalidation](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig#L978-L992).

Elisa already uses compact 32-bit query and edge IDs, dense node/edge pools, recycled edge slots, forward and reverse adjacency, and a reusable invalidation worklist. Its current edge has two 32-bit endpoints, three 32-bit links, and a 64-bit observed result generation: 28 bytes of fields, likely 32 bytes with conventional 8-byte alignment. Zig's `DepEntry` omits the dependee endpoint because typed dependee-head maps retain that identity, and uses dummy heads when removing a list head. That pattern could reduce Elisa's edge payload, but it would need to preserve the current result-generation check and be evaluated against additional indexing and update costs. Zig's `potentially_outdated` and `outdated` maps also track unresolved dependency counts and prioritize ready functions after upstream dependencies settle; Elisa has `PotentiallyDirty` status but no ready-unit queue.

The useful data-oriented transfer is stable integer handles, typed dependency identities, dense pooled records, and hot fields placed for the traversal that consumes them. Zig also uses maps where dynamic dependency keys and scheduling need them; its source does not imply that every compiler table should become structure-of-arrays. Elisa's graph now has a private `SourceInput`/`FunctionBodyFacts` evaluate-and-commit caller, but the body-query hit overlaps the prior exact-body/surface reuse path and still validates the canonical payload against the previous typed facts. Its graph integration is experimental groundwork, not measured acceleration. The query node now stores its six key/input/result byte-span fields as checked `u32` values. With the current incoming-edge validation fields, the source-level estimate is 112 bytes per node instead of 136 bytes with `usize` spans on a conventional 64-bit layout. That saves 24 bytes (about 1.5 MiB at the 65,536-node cap) before allocator and index effects. This remains an unmeasured layout estimate; measure query-node allocation and retained-edit traversal before attributing a memory or speed improvement.

Zig's incremental persistence is not a complete template to copy. The current source still has save-state TODOs for errors, namespaces, declarations, and linker state. The source study supports borrowing its in-memory dependency model and compact data layout selectively, not adopting its whole cache format.

Sources: [Zig `InternPool.zig` at the inspected commit](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/InternPool.zig), [Zig `Zcu.zig`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu.zig), [frontend update path in `PerThread.zig`](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Zcu/PerThread.zig), [cache save-state path](https://codeberg.org/ziglang/zig/src/commit/4812a98ce535e5c3f27c081b94153612cd4817ac/src/Compilation.zig).

### Rust: red-green query evaluation

rustc records query dependencies and fingerprints. When an input changes, dependent queries are reconsidered. A recomputed query can still be marked green if its result fingerprint matches the prior result, preventing unchanged downstream work from being invalidated. The recorded dependency order matters because control flow can change which queries are read. Persistent data is selected by query/result policy rather than serializing every in-memory compiler object indiscriminately. Code-generation work products are tracked as a separate artifact layer.

For Elisa, the useful rule is: propagate change from semantic result fingerprints, not merely from changed source text or a changed dependency. Recompute at the right boundary, compare the canonical result, and stop invalidation when that result is unchanged. Query dependencies must capture the reads that determined the result, including resolution candidate sets and failed lookups.

Sources: [Rust incremental compilation guide](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation.html), [detailed red-green explanation](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation-in-detail.html), [rustc incremental implementation at the inspected commit](https://github.com/rust-lang/rust/tree/33295d734447c7a2c22c44190f11bce6164a035a/compiler/rustc_incremental).

### Clang/LLVM: front-end reuse and artifact boundaries

Clang precompiled headers and modules serialize AST state and lazily load declarations and types. A precompiled preamble can let an editor reparse the edited portion of a source file while reusing the unchanged prefix and includes. These mechanisms target front-end work and are separate from object reuse.

ThinLTO separates a summary index from per-module backends. The thin link can reason over summaries instead of loading every full module. Backend results use a cache key derived from module/import-export decisions and code-generation configuration; a hit is checked before parsing and optimizing the full module. This is a useful boundary lesson for Elisa: key artifacts by the exact canonical input snapshot and all target/backend settings that affect the object. A path, source timestamp, or LLVM version string alone is not enough.

Sources: [Clang precompiled-header internals](https://clang.llvm.org/docs/PCHInternals.html), [ThinLTO design](https://clang.llvm.org/docs/ThinLTO.html), [`ThinLTOCodeGenerator.cpp` cache implementation at the inspected LLVM commit](https://github.com/llvm/llvm-project/blob/70a4494e073f57eebb77931a5a2e59f6b5e9e13a/llvm/lib/LTO/ThinLTOCodeGenerator.cpp#L369).

### GCC: multiple reusable representations

GCC's pipeline provides another useful comparison point: its GIMPLE pass hierarchy operates on a language-independent high-level representation, while RTL passes lower toward machine instructions. Its LTO code has explicit streaming and partitioning paths for cross-file optimization. That reinforces the same architectural separation seen in LLVM: semantic-analysis reuse, IR/work-product reuse, and final machine-code reuse are different cache layers with different inputs and correctness boundaries. See GCC's [GIMPLE pass interfaces](https://github.com/gcc-mirror/gcc/blob/9a00f0797c90485cd70ac86a8751c9565c3979dd/gcc/tree-pass.h), [LTO partitioning](https://github.com/gcc-mirror/gcc/blob/9a00f0797c90485cd70ac86a8751c9565c3979dd/gcc/lto/lto-partition.cc), and [LTO streaming](https://github.com/gcc-mirror/gcc/blob/9a00f0797c90485cd70ac86a8751c9565c3979dd/gcc/lto-streamer-out.cc).

The GCC checkout is source-only and sparse; we did not build it or make an equivalent runtime comparison. `/usr/bin/gcc` on this machine resolves to Apple Clang, so it is not a usable GCC toolchain. The assembly experiment below uses Clang as the C frontend because it emits LLVM IR directly.

## Equivalent generated-code comparison

A small wrapping-`u64` loop was written in Zig, Rust, and C. It updates an accumulator with the same recurrence and uses a loop-carried dependency so the inner loop remains visible. We emitted optimized LLVM IR and assembly with Zig's LLVM backend, rustc, and Clang for Apple arm64 / `apple-m5`, with frame pointers omitted and optimization enabled.

The optimized LLVM text was not identical. Zig's LLVM output had already expressed the multiply-by-constant recurrence as an incrementing induction value; the Rust and Clang LLVM text still showed the multiply in the loop. After machine-code optimization, all three produced the same loop body:

```asm
add  x10, x1, x8
eor  x1, x10, x1, lsr #13
add  x8, x8, x9
subs x0, x0, #1
b.ne loop
```

The constant setup, empty-loop check, and return sequence also matched. This is a code-shape comparison, not a timing benchmark; it establishes no runtime speedup. It is a concrete warning against ranking compiler output by LLVM-IR instruction count alone. Compare final assembly and benchmark representative programs before adopting an optimization.

The installed rustc target used macOS deployment version 11.0 while Zig and Clang used 27.0.1, so the target triples were not byte-for-byte identical; the CPU/ISA and optimization intent were aligned. The comparison used Zig 0.17.0, rustc 1.99.0 / LLVM 23.1.2, and Homebrew Clang 23.1.3. It exercised Zig's LLVM backend (`-fllvm`), not Zig's native backend. Reproduction inputs and outputs are retained in `build/research/compiler-sources/ir-compare/`.

## Recommendations for Elisa

1. **Connect the existing O0 shard artifact cache as a narrow production milestone.** The backend already has APIs for preparing verified logical shards and emitting a cache miss from the exact snapshot; the Stage1 helper already provides content-addressed tickets and atomic object bundles. The driver does not connect them yet. Start with plain native `-O0` object output, exact loaded-toolchain and target recipe validation, deterministic logical merge order, and a cold fallback for unsupported inputs. Keep it opt-in until clean/warm parity, one-shard invalidation, corruption recovery, and end-to-end measurements pass. This is the smallest existing boundary that can avoid native object generation without trusting persisted semantic results.

2. **Give semantic sessions a real owner across requests.** The private session API can retain safe, supported function facts, but the ordinary driver currently constructs a disabled session and the disk sidecar recollects facts from current source. A long-lived compile server can own one session per translation unit. Keep current diagnostics/checker behavior authoritative and measure overhead against fresh analysis; recent synthetic results do not establish a reliable full-pipeline win.

3. **Add a real dependency at a semantic read site.** A narrow first slice is the translation-unit global suffix of `name_known` for `Expr.Ident`: keep special-name, local-binding, and region-name checks ahead of it, then cache only the exact global membership result, including both `Known` and `Missing`. Key by source identity, current module, and exact name, and depend on the current `SourceInput` so declaration and import edits reconsider prior results. Never retain `DeclId`, `BindingId`, or symbol-table rows. The current global lookup already uses an expected-O(1) name index, so this is a dependency-correctness prototype until counters and retained-edit timings show that graph overhead is repaid. For broader body reuse, add typed dependencies only for the external facts that the body collector actually reads.

4. **Make one bounded data-layout change at a time.** Elisa already has dense query and edge pools, compact IDs, a free list, and forward/reverse links, so a second analysis-unit table would mostly duplicate existing structure. The current prototype stores the query node's six key/input/result byte-span fields as checked `u32` values. The 8 MiB and 16 MiB pool caps bound every admitted span; with current incoming-edge validation fields, the estimated node record is 112 bytes instead of 136 bytes with `usize` spans on a conventional 64-bit layout. This saves 24 bytes (about 1.5 MiB at the 65,536-node cap) before allocator and hash-index effects. Compare actual allocated bytes and graph traversal timings before keeping or crediting the change. Treat Zig's implicit-dependee edge and reusable dummy-head scheme as a separate, higher-invariant experiment; its storage savings do not justify changing Elisa's simpler explicit endpoints without measurements.

5. **Treat code generation as a later, separate cache layer.** A codegen key must include exact LLVM snapshot contents, target machine, LLVM/compiler/runtime identities, optimization and emission options, shard ownership/restriction versions, and relevant profile inputs. Shard bridge names are module-local ordinals and the caller must localize them after each translation unit's complete hit/miss merge before linking it with other units. Any localization or ticket/attestation failure should discard staged hits and use the clean path.

## Elisa prototype from this study

The current worktree has a private query graph in
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
facts, and falls back to the existing typed-fact copy on a graph miss. This is
not yet a net performance result; graph publication, validation, and payload
decoding add work, and no parity or retained-edit benchmark qualifies the path.
Other declared query kinds, including `FunctionSummary`, `VisibleNameSet`,
`NameLookup`, `TypeOf`, and `ConstantValue`, have no callers. The next semantic step is a real typed
dependency at a read site, such as a complete scope/name lookup that records
both found and missing outcomes. Do not persist `DeclId`, `BindingId`, AST
pointers, or `SymbolTable` rows as query identity.

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
