# Preoptimization shard cache interface

The independent Python helper prepares an exact input ticket and restores/publishes atomic object and diagnostic bundles. It does **not** implement compiler shard scheduling or prove optimizer/emitter avoidance. Its native-independent controls use synthetic artifact bytes; backend integration must qualify actual LLVM objects separately.

The backend now has a preparation seam in `src/backend/codegen_parallel_emit.elisa`: it chooses the largest dense FNV bucket count up to 16 from full function symbols, rejects unsupported linkage/inventory forms, function-level inline assembly and block-address constants, `alwaysinline` definitions, aliases, ifuncs, COMDAT members, debug compile units, and unstable generated function names, clones the verified module one shard at a time, and strips foreign function bodies. Inputs are fresh source-generated modules; this backend has no module-level assembly setter or bitcode-import path. Mutable/external globals and readonly internal/private constants have one definition in shard zero, preserving address identity across shards. It verifies silently, writes exact bitcode snapshots to a caller-provided unique prefix in a private directory, and disposes each clone immediately. Its result distinguishes unsupported input from a restricted-clone verifier or write failure; the latter must be fatal to cache admission. The backend also exposes `emit_part_cache_snapshot_o0`, which parses and verifies one retained snapshot before object emission without repartitioning the parent module. Its caller must provide a matching O0 target machine and remove a private staging object if emission fails; the function does not check those conditions. Neither API is connected to the driver or cache helper yet. The selected count is independent of `ELISA_STAGE1_JOBS`; changes to the function inventory can select a new count and conservatively miss the full shard set. A local-constant edit changes shard zero's snapshot. The current compiler still optimizes the whole module before `emit_object_parallel` in `src/driver/elisac.elisa`. The next integration is an opt-in plain-object O0 branch before that optimization, using each exact snapshot for cache identity and parsing only misses for emission. The existing default whole-module path remains unchanged. O2 caching requires moving optimization onto misses and changes cross-shard inlining/code quality.

Both live parallel emission and cache snapshots name externalized local values
`elisa.part.<module-ordinal>`. The ordinal follows the module's globals and
functions, so the same module gives every shard the same bridge names. Source
and output paths do not affect bridge names; other module metadata such as debug
source paths can still affect snapshot/object bytes. After all shards for
one translation unit are merged, `localize_part_bridges` checks the complete
expected name set with `llvm-nm`, localizes those definitions with
`llvm-objcopy --localize-symbols`, then checks that no bridge-prefixed global
definitions remain. It handles the leading underscore used by Mach-O symbol
tables. Live emission falls back to serial codegen if a tool is missing or any
check fails. `localize_part_cache_output` applies the captured bridge list from
the prepared set for a cache merge. No cache miss merge/publish callsite exists
yet, so its caller must fail closed and must merge all hit and miss shard
objects in logical order before localization; shard
artifacts stay external so cross-shard references can resolve during that
merge. The complete per-translation-unit object is localized before it is
linked with another unit or published as a reusable merged object.

`elisa.part.` remains reserved in the source module: a declaration, definition,
alias, or ifunc already using that prefix makes live emission serial and shard
preparation unsupported. This prevents source values from being mistaken for
generated bridges. If a module has generated bridges, live emission also falls
back to serial when function-level inline assembly is present, because raw
assembly references can bypass LLVM's symbol inventory. Shard preparation already
rejects function-level inline assembly. Prebuilt objects must not reference
compiler-private bridge names. A two-unit link-parity control with equal private
function/global names remains required before enabling cache reuse.

## Native/backend boundary

1. Verify parent IR once. Resolve full-symbol function owners once using the deterministic largest-dense-bucket rule (independent of worker count). Strict initial admission rejects unnamed/generated/traversal-order function identities, function-level inline assembly, block-address constants, `alwaysinline` definitions, debug compile units, unsupported aliases/ifuncs/COMDAT, and uncertain linkage. The input is a fresh source-generated module, with no module-level assembly setter or bitcode-import path. Mutable/external globals and readonly internal/private constants have one owner in shard zero to preserve address identity. These rules are part of `ownership_version`.
2. Prepare a verified restricted **unoptimized** snapshot with foreign function bodies and non-owner shard-zero-owned global initializers removed, including readonly internal/private constants. Hash actual serialized bytes, not source-body fingerprints. The current seam writes each snapshot and disposes its clone; retain the exact snapshot path/bytes for the key and parse only a selected miss snapshot once for emission, without rebuilding or restricting the parent module.
3. Discover producer and LLVM image paths for diagnostics, but keep cache admission disabled until a native bridge attests the bytes actually mapped into the process. `ArtifactIdentity::discover` currently reports paths only. Opening `/proc/self/exe`, a `/proc/self/maps` pathname, or `/proc/self/map_files` after load would pin or hash the backing file's current contents; it cannot prove those contents match LLVM's earlier mapped bytes. ELF executable mappings use `MAP_PRIVATE`, whose visible pages can diverge from a later read of the inode after copy-on-write or external file modification. The helper can rehash file descriptors between admission and finalization, but that only detects later changes to the file and still does not attest the mapped pages. Path lookup, inode identity, and a caller-supplied digest of the current file are insufficient to attest loaded code. Native discovery versions identify the required caller contract; they are not attestations by the helper. A qualified implementation must attest mapped image contents at admission and detect changes through finalization.
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

## Batched invocation

`BatchInvocation` and `batch-restore` / `batch-publish` avoid rehashing large shared artifacts per shard. Each helper process fingerprints producer, loaded LLVM, runtime and each profile once at admission and once at finalization. It retains an internally observed shared identity; no caller-supplied hash or stat-only shortcut replaces actual byte reads. Snapshot hashing remains per shard.

A bounded batch request has exactly `cache`, `producer`, `loaded_llvm`, `runtime`, `profiles`, and `shards`. Restore shard records have `snapshot`, `options`, `object`, `stdout`, `stderr`; publish records have `ticket`, `object`, `stdout`, `stderr`. Invoke `batch-restore --request request.json --result result.json`, then optimize/emit only the records marked `hit: false`, then invoke `batch-publish` on their unchanged tickets. Return 0 means all restore hits/publication success, 1 means at least one restore miss (the result still supplies every exact ticket), and 2 means fatal failure. The helper only commits the result JSON after successful final attestation.

Batch hits are restored directly into uniquely named hidden files beside their destinations, avoiding a second full object copy across filesystems. The helper hashes cache bytes while restoring and retains each manifest identity. Finalization rechecks every staged hit before cache publication and again immediately before same-filesystem rename to its destination. Publication bundles are prepared privately and committed only after shared identities are revalidated. Changed shared inputs discard staged hits and publication bundles. A batch cannot prepare, restore or publish after finish/close. Misses and abandoned contexts remove their hidden files and any newly created empty destination directories.

Controls prove shared artifact read count is exactly eight with one profile (four artifacts read twice) for both one shard and 64 shards, including batch publication and restoration. CLI mixed-miss/publication/hit/fatal statuses, post-restore private hit corruption, changed identity, constructor cleanup and lifecycle rejection are covered. These counters establish helper I/O scaling only; actual backend scheduler and compiler throughput remain unqualified.

## Compact native consumer protocol

For an Elisa caller that does not parse generic JSON, `batch-restore --request original.json --result restore-result.json --status status.txt` writes a bounded ASCII manifest only after full input and copied-output attestation:

```text
ELISA_PREOPT_SHARD_STATUS_V1
2
HM
```

The logical count is 1..64. Rows must cover exact contiguous ordered logical shard ids `0..count-1` with one common output recipe, distinct output/log paths and an H/M string of exactly that count. Missing, duplicate, reordered, boolean-index and inconsistent-recipe records are rejected; status results cannot claim guessed hits. The native caller must strictly check header/count/bit length and accept status 0/1 only after the helper terminates. Use fresh unique invocation files, not stale status/output paths.

After emitting only M shards, invoke `batch-publish-result --request original.json --restore-result restore-result.json --result publish-receipt.json`. The helper reads full original immutable tickets itself and compares snapshot paths and exact options to original admission. It rehashes actual artifacts and publishes only recorded misses. The native caller never reconstructs supplied hashes or tickets from compact status. Admission JSON, restore JSON, status and receipt paths must be distinct; publication cannot overwrite admission. The producer/LLVM discovery contract remains mandatory.

Include catalog `identity_policy` in the pinned restriction-version domain (for example distinct strict-manifest versus exact-generated-symbol recipe versions); do not reuse keys across admission/restriction policy changes. The existing `ownership_version` pins fixed full-symbol FNV ownership for functions, owner-zero mutable/external globals and readonly internal/private constants, alwaysinline rejection, logical shard count, and the module-ordinal bridge naming/localization contract; the restriction version must also pin foreign-body stripping and global declaration rewriting. Actual snapshot bytes remain the primary content identity.

Batch requests may include `mapped_image_digests`, an exact map with `producer`
and `loaded_llvm` keys and lowercase 64-character SHA256 values. These values
must come from native verification of the actual mapped images (on Darwin:
mapped CodeDirectory signed pages, entire mapped signature tail, and mapped
vnode identity), rather than hashes of requested paths. The helper still hashes
the actual files itself, compares both digests at admission, and repeats both
comparisons during final shared-artifact reattestation. Supplied digests never
replace file reads or populate the content identity directly. The helper accepts
omission when the native caller independently attests mapped-image contents by a
qualified mechanism; omission does not waive that requirement. Inherited Linux
file descriptors pin an inode and support admission-to-finalization rehashing, but
do not alone prove that the bytes match the already loaded image. Explicit null,
partial maps, and malformed hex are rejected.

Restore tickets retain this optional attestation map. Publication from a restore
result requires the original request's exact map, including rejecting removal of
pins. A mismatch before finalization discards private staged hits/publications
and does not replace final object or diagnostic outputs. Controls cover malformed
pins, admission mismatch, mapped files replaced after hit/miss staging, mixed
hit/miss publication, all-hit publication, and dropping original pins.

Within a batch, each canonical restricted snapshot path is independently hashed
once at admission and once at final attestation before any cache or output
publication. Repeated validators still check the complete ticket, key, recipe,
shared pins, mapped image pins, and admitted snapshot identity. An admitted key
cannot be reused with a differing ticket or snapshot path, even if identical
bytes produce the same content key. The invocation stores exact canonical ticket
bytes independently of caller-owned dictionaries. Final snapshot hashing uses
actual bytes rather than stat metadata. Instrumented cold publication and warm
restore controls assert two snapshot reads per snapshot despite repeated
validators; changed snapshots still abort before final output publication.
