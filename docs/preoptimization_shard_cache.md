# Preoptimization shard cache interface

The independent Python helper prepares an exact input ticket and restores/publishes atomic object and diagnostic bundles. It does **not** implement compiler shard scheduling or prove optimizer/emitter avoidance. Its native-independent controls use synthetic artifact bytes; backend integration must qualify actual LLVM objects separately.

The current compiler still optimizes the whole module before `emit_object_parallel` in `src/driver/elisac.elisa`. The smallest coherent integration is an opt-in plain-object branch before that optimization, with fixed logical shards and a separately qualified cold per-shard pipeline. The existing default whole-module optimization path remains unchanged. O0 caching can first avoid emission; O2 requires moving optimization onto misses, and changes cross-shard inlining/code quality.

## Native/backend boundary

1. Verify parent IR once. Resolve full-symbol stable owners once at fixed logical shard count (independent worker count). Strict initial admission rejects unnamed/generated/traversal-order identities, unsupported aliases/ifuncs/COMDAT and uncertain linkage.
2. Prepare a verified restricted **unoptimized** snapshot with foreign bodies stripped. Hash actual serialized bytes, not source-body fingerprints. Keep those exact bytes for miss emission; parse them once on a miss rather than rebuilding/restricting again.
3. Derive producer identity from the actual running executable and LLVM identity from the actual loaded `LLVMContextCreate` mapping (`dladdr` or a qualified platform bridge), and pin actual runtime/profile artifacts. A requested path or caller-supplied digest is insufficient. The helper hashes those files itself but cannot prove a given path is loaded. Native discovery versions in the recipe identify this caller contract; they are not attestations by the helper. Detect artifact changes relative to load/admission; path lookup after replacing a loaded library must not fingerprint new on-disk bytes as old mapped code.
4. Invoke prepare/restore. Only status 1 is a recoverable cache miss. Status 2 is fatal (invalid recipe, changed compiled tuple or I/O failure), never silently authorize a hit or duplicate partial diagnostic publication. On status 0 restore, skip optimization **and** object emission. Aggregate diagnostics exactly once.
5. On a miss run the resolved per-shard pipeline on the retained snapshot, verify optimized IR, emit object, then publish with the unchanged ticket. Schedule only miss ids; combine hits and misses in logical shard order for relocatable linking. Failed worker/link means no successful final output.

## Recipe and invalidation

The recipe includes target triple/data layout, CPU/features, exact optimization pipeline and target-machine optimization, relocation/code model, debug/contracts, explicit coverage/PGO policy, profiles' actual contents, full resolved normalized codegen arguments and output-affecting environment, ownership/restriction/discovery versions and shard id/count. Unknown top-level fields and incomplete policy maps are rejected. The native caller must supply the complete resolved output policy; the helper cannot discover unreported compiler switches. Worker concurrency belongs outside the logical recipe.

Producer/LLVM/runtime/profile files and the snapshot are SHA256-fingerprinted from their actual bytes. Ticket validation rehashes inputs at restoration and publication, including a second check before output publication. Relocated identical artifact paths retain the same key. Changed compiler, LLVM, runtime, profile, ABI, policy or snapshot misses under a newly prepared key; changing artifacts after compilation admission is fatal under the old ticket.

Do not add the whole parent-module content hash to per-shard keys: it would defeat body-edit reuse. Exact restricted bytes already conservatively include declaration ABI/attributes, retained globals/constants, flags and metadata. Foreign callee bodies must be removed before optimization; otherwise changing a callee can alter cached caller inlining. Unsupported dependency models take the normal cold path.

## CLI

`prepare --request request.json --ticket ticket.json` accepts exactly `snapshot`, `producer`, `loaded_llvm`, `runtime`, `options`, and `profiles`. `options` uses the fields checked in `validate_options`; `resolved_output_policy` contains exactly `normalized_codegen_args` (string array) and `output_environment` (string map). Producer discovery is `running-executable-v1`; LLVM discovery is `dladdr-LLVMContextCreate-v1`.

`restore --ticket ticket.json --cache cache-dir --object shard.o --stdout shard.out --stderr shard.err` returns 0 on hit, 1 on miss, 2 on failure. It validates both originals and copied bytes before publication; diagnostics publish first, object last. I/O failure after partial diagnostics is fatal and leaves prior object intact.

`publish` accepts the same arguments, using already emitted object/log paths. Per-key OS locks coordinate actual processes. A full fsynced object/log/manifest directory is atomically renamed into the entry. Existing valid publication is immutable; corrupt generations are retired under the lock. Readers verify bounded manifest and exact object/log bytes; empty logs are valid, empty objects are not.

## Qualification

Run `python3 scripts/test_stage1_shard_cache.py`. Controls cover actual artifact/option/profile invalidation, path-independent identity, supplied-digest rejection, cached output/log restore, corrupt and oversized bundles, staged-copy mutation, atomic commit failure, changed input after compile admission, thread and cross-process publication/readers, and fatal diagnostic publication failure.

Backend acceptance still requires real cold/warm O0/O2 objects and behavior, zero optimizer/emitter calls on hits, one owner-body edit with only that shard missing, callee ABI edits invalidating affected declaration snapshots, globals and target changes, generated identity cold fallback, corrupted cache recovery, mixed-hit/miss worker failure and native64/wasm32 execution. Warm opt-in and cold opt-in must match behavior and diagnostic streams; separately compare runtime performance/size against current whole-module O2 before considering defaults. No compiler build, benchmark or speedup is established by helper tests.
