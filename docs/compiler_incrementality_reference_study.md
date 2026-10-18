# Compiler incrementality reference study

**Research snapshot:** 2026-10-18  
**Purpose:** extract concrete incremental-compilation and data-layout ideas for Elisa from Zig, rustc, Clang/LLVM, and GCC. Source checkouts and generated comparison artifacts are under the ignored `build/research/compiler-sources/` directory.

## What the references do

### Zig: typed dependencies and compact compiler data

The current Zig checkout represents analysis units with compact typed handles (`AnalUnit` is a packed 64-bit value) and stores interned items as a small tag plus a 32-bit payload. The intern pool tracks distinct dependency kinds: source hashes, declaration values and types, inferred error sets, type layout, defaults, files and embeds, namespace contents, name existence, and memoized state. Distinguishing these facts lets an edit invalidate only analyses that depended on the changed fact. Name-existence dependencies matter for negative lookups: adding a declaration can invalidate a prior “not found” result even though no old declaration changed.

Dependency edges are indexed in both directions. A depender owns a compact linked edge chain; reanalysis can remove and replace all of its old outgoing edges. Edge slots are recycled. The update path marks transitive dependents as potentially outdated, waits until their dependencies have been checked, then prioritizes ready functions so useful code generation can proceed early. The frontend snapshots file state before scheduling work and avoids applying dependency invalidations when a failed frontend update makes the new analysis unreliable.

This is the most relevant data-oriented transfer: stable integer handles, pooled edges, dense tables, and only the hot fields in hot data structures. Zig uses columnar list storage where it helps. These choices reduce pointer chasing and make graph updates predictable, but they do not replace correct dependency semantics. A large storage rewrite should follow profiling; Elisa can first prototype typed IDs and pooled reverse edges around its existing facts.

Zig's incremental persistence is not a complete template to copy. The current source still has save-state TODOs for errors, namespaces, declarations, and linker state. The source study supports borrowing its in-memory dependency model and compact data layout selectively, not adopting its whole cache format.

Sources: [Zig `InternPool.zig` at the inspected commit](https://github.com/ziglang/zig/blob/738d2be9d6b6ef3ff3559130c05159ef53336224/src/InternPool.zig), [Zig `Zcu.zig`](https://github.com/ziglang/zig/blob/738d2be9d6b6ef3ff3559130c05159ef53336224/src/Zcu.zig), [frontend update path in `PerThread.zig`](https://github.com/ziglang/zig/blob/738d2be9d6b6ef3ff3559130c05159ef53336224/src/Zcu/PerThread.zig), [cache save-state path](https://github.com/ziglang/zig/blob/738d2be9d6b6ef3ff3559130c05159ef53336224/src/Compilation.zig).

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

3. **Build the semantic dependency model before broadening result reuse.** Introduce stable typed analysis-unit handles and dependencies for body, callable surface/contracts, inferred effects, constants, layouts, namespace membership, overload candidate sets, failed name lookups, includes/generated inputs, and configuration. Store both forward and reverse edges, replace outgoing edges after reanalysis, and propagate invalidation using canonical result fingerprints (a red-green rule). Keep source locations and diagnostics rebound to the current source revision.

4. **Use Zig-style data layout where measurements justify it.** A practical graph prototype is an `AnalysisUnitID` table, an interned typed `DependencyID` table, and one contiguous `DepEdge` pool. Each edge stores its unit and dependency IDs plus links in both adjacency directions; head arrays make it cheap to visit all dependents of a changed fact or remove all old dependencies after reanalysis. Recycle removed edge slots with a free list. Keep unit state and hot counters in dense indexed arrays; split frequently scanned fields into columnar arrays only when allocation and cache profiles show the layout helps. This avoids one heap object or map entry per dependency while retaining precise graph semantics. Keep persistence schemas versioned and avoid storing mutable AST, symbol-table, or LLVM objects.

5. **Treat code generation as a later, separate cache layer.** A codegen key must include exact LLVM snapshot contents, target machine, LLVM/compiler/runtime identities, optimization and emission options, shard ownership/restriction versions, and relevant profile inputs. Shard bridge names are module-local ordinals and the caller must localize them after each translation unit's complete hit/miss merge before linking it with other units. Any localization or ticket/attestation failure should discard staged hits and use the clean path.

## Elisa prototype from this study

The current worktree now has the first data-oriented query-graph foundation in
`src/semantic/incremental_function_facts.elisa`: session-scoped 32-bit query and
edge handles, exact owned query-key bytes, contiguous query/edge arrays, a free
list, and forward plus reverse adjacency. Reanalysis can replace one query's
dependencies, and a changed query can mark its reverse dependers dirty. The
edge pool retains both endpoints and four adjacency links to support constant-
time unlinking in either direction; the live/freed state uses endpoint
sentinels instead of a separate boolean. Dependency deduplication currently
uses a nested scan; optimize it only if recorded fan-in shows the update path
matters. These APIs are not yet called by the
semantic checker, so current checker behavior and performance are unchanged.
The next step is to record dependencies at real semantic read sites and then
add result fingerprints and red-green reuse. Do not persist `DeclId`,
`BindingId`, AST pointers, or `SymbolTable` rows as query identity.

A follow-up layout pass groups query status and adjacency handles before the
wide key spans and fingerprints. Under conventional 64-bit struct alignment,
this field order is expected to use 56 bytes per query node, compared with 72
bytes for the earlier order. That is a source-level layout estimate, not a
measured Elisa object layout or a compile-time speedup. Zig's packed `AnalUnit`
and pooled `DepEntry` show the same general payoff from compact handles and
keeping dependency traversal data in dense arrays; Elisa should measure the
graph once it has real callers before considering a broader structure-of-arrays
rewrite.

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
| Zig | `zig`, `src/` and `test/standalone/` | `738d2be9d6b6ef3ff3559130c05159ef53336224` |
| Rust | `rust`, selected compiler crates | `33295d734447c7a2c22c44190f11bce6164a035a` |
| LLVM/Clang | `llvm-project`, Clang/LLVM/LTO/LLD paths | `70a4494e073f57eebb77931a5a2e59f6b5e9e13a` |
| GCC | `gcc`, `gcc/` | `9a00f0797c90485cd70ac86a8751c9565c3979dd` |
