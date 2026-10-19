# Pointer sum codegen review

This comparison compiles the same `sum64(values, count)` pointer kernel for Elisa,
Clang C, Rust, and Zig. It is a small optimizer/codegen probe, not a language-wide
benchmark and not the `darray_counted_fill` workload.

## Generated loop

Elisa, Clang, and Rust emit the same essential AArch64 loop on Apple M5: four
independent `<2 x i64>` accumulators, paired 128-bit loads, four NEON vector adds,
and a loop backedge every eight values. Each then horizontally reduces the vector
accumulators and handles a scalar tail. Elisa and Clang have the same 39-instruction
function body in the frozen objects. Zig emits a four-value scalar-unrolled loop with
paired integer loads and four scalar adds, then handles its tail.

This is useful evidence that the current LLVM path can match Clang and Rust's
vectorizer for a simple reduction and select a faster-looking loop shape than Zig on
this target. It does not establish that vectorization alone caused a runtime speedup.

## Exploratory timing

The four frozen dylibs were called on the same 16,777,216-element input (128 MiB),
with one warmup and eleven randomized-order trials of six calls each. Every call
returned the same checksum. Median time per element was:

| Compiler | ns/element | Ratio to Zig |
| --- | ---: | ---: |
| Elisa | 0.1593 | 0.868 |
| Clang | 0.1683 | 0.917 |
| Rust | 0.1566 | 0.853 |
| Zig | 0.1835 | 1.000 |

These are exploratory timings from one host run; the sample spread is nontrivial,
so treat the medians as a lead rather than a stable performance claim. The detailed
sample list and artifact hashes are in `/tmp/elisa-array-sum-codegen-review/frozen-current/timing-20261019.json`.

A separate 31-trial repeat reports different medians (Elisa 0.3166, Clang 0.3271,
Rust 0.3048, Zig 0.3466 ns/element), but contains no source, binary, compiler, or
invocation provenance and includes large outliers. Keep it exploratory and do not
combine it with the hash-pinned 11-trial run until the setup discrepancy is explained.
The hash-pinned run's listed source, object, and library hashes match the adjacent
frozen artifacts; the repeat's missing provenance prevents the same check.

Elisa here was built by the pinned Core Stage0 compiler, not the current Stage1
product. This result says nothing about current Stage1 or `darray_counted_fill`.
For that benchmark, the acceptance check remains the actual O3 IR/assembly: one
pre-loop reserve, no hot-loop capacity/grow edge, direct indexed store, and one
final count commit.

## Current Stage1 build status

The `956f1eb4…` run described below is no longer the newest trustworthy
Stage1 check; later source edits invalidate its claim that it represents the
current tree. The latest isolated snapshot seed available in this review used
source hash `886713fd…` and exited before object generation with 110
diagnostics. Its remaining blockers include 48 errors in
`incremental_function_facts` (temporary-region borrows passed to
`ifc_scan_candidate` and returned values backed by a local request region),
two ownership lookup ensure failures, three ownership-index invariant
warnings, and additional EASM/codegen diagnostics. It produced no Stage1
object, so the current `FastPushCursor` IR/assembly remains unverified.

An earlier full seed used the clean Core Stage0 bootstrap at
`/private/tmp/elisa-core-stage0-clean-20261019/compiler/bin/elisac` (SHA-256
`c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`) and
exited 1 before producing an object. Its after-run tree hash was reported as
`956f1eb4…`, but later audits found source edits crossing the compile; do not
attribute its diagnostics to an exact tree. The Stage1 script removed the
failed temporary object. Older Stage0 counted-fill IR does not verify the
current `FastPushCursor` output.

R78 tested `/private/tmp/elisa-stage1-clean-core-current-20261019-r78` with source-tree SHA-256 `ba6a37778f44d1a907d58e037df616c0ad2e2ebccff77f6e4b2bb7ffbea9b317`, build-recipe SHA-256 `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`, and Core Stage0 SHA-256 `191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b`; before/after provenance matched. It exited 1 without an object. The split ownership witness clauses cleared the three candidate-helper postcondition errors from R77; three ownership lookup invariant warnings remain. New hard errors came from the `@pool` region generic (cannot infer at three pipeline calls), missing mutable-reference arguments to `incremental_semantic_name_lookup_context_disabled_push`, and a snapshot borrow mismatch. The two StoreThrough findings at semantic API lines 856/976 remain and need separate handling; R84’s source-only audit indicates the pool-related ones are false positives from name-based analysis that does not model the nursery join. Exact log: `/private/tmp/elisa-seed-r78-clean-core-20261019.log`. Current Stage1 `FastPushCursor` IR/assembly remains unavailable.

R77 tested frozen snapshot `/private/tmp/elisa-stage1-clean-core-current-20261019-r77` with source-tree SHA-256 `caca73552fd1bb0dc9db67da77938a30a627605e791d6a7ecaa652bea08ebc75`, build-recipe SHA-256 `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`, and Core Stage0 SHA-256 `191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b`; before/after source and recipe hashes matched. It exited 1 without an object. The ownership lookup proof failures fell from 19 in R76 to three remaining candidate-helper ensures at lines 77, 170, and 284, plus three invariant warnings. This snapshot had `Decl& @source` emitter parameters in `codegen_declare.elisa`, which caused enum pattern names to be undefined and mismatched downstream APIs; the current shared source has since restored the by-value `Decl` parameters, but that newer tree still needs a pinned seed. Semantic API lifetime escapes and other semantic/backend proof blockers remain, so current Stage1 `FastPushCursor` IR/assembly is unavailable. Exact log: `/private/tmp/elisa-seed-r77-clean-core-20261019.log`.

R76 tested the frozen snapshot `/private/tmp/elisa-stage1-clean-core-current-20261019-r76` with source-tree SHA-256 `a4f2072db0f3678195187f7c3ccea227e5f61759ac8bb0f22a5f7a36456cced7`, build-recipe SHA-256 `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`, and clean Core Stage0 SHA-256 `191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b`. Before/after provenance matched. It exited 1 without an object. The named-result `OwnershipBindingLookupResult` API still has 19 failed `ownership_binding_at_position` ensure proofs; `semantic_api.elisa` reports several region escapes, and other ownership-flow, EASM, and codegen proofs remain. Exact log: `/private/tmp/elisa-seed-r76-clean-core-20261019.log`. Current Stage1 `FastPushCursor` IR/assembly remains unverified.

R74 used isolated snapshot `/private/tmp/elisa-stage1-clean-core-current-20261019-r74`, source-tree SHA-256 `9a2c4cd7b592babf072526becdab86f2c0fb7d5e19bbc088ff3924f2dc43163b`, and clean Core Stage0 SHA-256 `191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b`. Before/after source hashes and stat fingerprints matched. It exited 1 without an object. This snapshot had the output-parameter lookup, the five representation-specific ensures removed, and explicit assertions after writes; it still had 40 lookup postcondition proof failures. A read-only audit found these were type errors in the proof expressions (`mutable bool&` used as a bool and `mutable BindingId&` passed as a value), not missing runtime-path assertions. The same seed reports remaining `semantic_api` lifetime/type issues, `incremental_function_facts` lifetime escapes, EASM/codegen postconditions, and ownership-flow loop invariants. Exact log: `/private/tmp/elisa-seed-r74-clean-core-20261019.log`.

R73 used clean Core Stage0 SHA `191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b` on source-tree SHA `a0ad8ba8565c42f201eb5d50cb95e9ca160f13cd7b6460efb9aef6a18c666166`; before/after provenance matched. It exited 1 without an object. Its lookup source removed the representation-specific postconditions, but had not yet added the post-write assertions or direct-vacuous-forall ownership-flow change included in R74. Log: `/private/tmp/elisa-seed-r73-clean-core-20261019.log`.

R72 used pinned StoreFlow Stage0 SHA `fe96f432eeb205c9ed883b594fb7144cd9aaa9084f6435a83f199f39ba530cd2` on source-tree SHA `3918a3b4217b18052cc4b055062e3bd1b1ef70df99473b30d41fde0960cc5b13`; source hashes matched before/after, though stat fingerprints differed. It exited 1 without an object and reported 78 ownership lookup postcondition failures while the output-parameter migration still retained representation-specific shape contracts. Log: `/private/tmp/elisa-seed-r72-20261019.log`.

R71 compiled the isolated snapshot `/private/tmp/elisa-stage1-snapshot-current-20261019-r71` with source-tree SHA-256 `5fd5dd07bc5a8715dcbc2c96009243090bd0966bb4b4e0b54a8244c70501a35e` and pinned StoreFlow Stage0 SHA-256 `fe96f432eeb205c9ed883b594fb7144cd9aaa9084f6435a83f199f39ba530cd2`. Before/after provenance JSON matched. It exited 1 without producing `build/elisac_stage1.o`. Audit of the pinned snapshot corrected the earlier assumption: its ownership lookup still returned a tuple, so the three reported failures are direct tuple-literal success returns (fallback, indexed singleton, and general selected row), while the five representation-specific ensures were still present. Later R72–R74 seeds tested output-parameter variants and are recorded above. Other R71 blockers include the `ownership_bindings_unknown` postcondition, `semantic_api.elisa` region/type errors, lifetime escapes in `incremental_function_facts.elisa`, and EASM/semantic postconditions. Exact log: `/private/tmp/elisa-seed-r71-20261019.log`. Current `FastPushCursor` IR/assembly remains unverified.

After R74, the worktree began another API experiment using a named `OwnershipBindingLookupResult` carrying a witness index. Its caller migration and proof gate were not complete at the latest inspection, and it has not been compiled; treat it as in-progress source only.

R70 used the isolated snapshot `/private/tmp/elisa-stage1-snapshot-current-20261019-r70`, source-tree SHA-256 `d841bb4f542d30635e5d68a5c9d5fd1c7519002d8f80ccc8fa10aeb70b1fff21`, and the older StoreFlow Stage0 bootstrap. Before/after provenance matched. It exited 1 without an object. The ownership lookup still has 30 failed postcondition records: two groups of success paths fail to prove result identity/sentinel contracts, even after narrowing the table-shape ensures. `semantic_api` still reports two region escape errors at its lookup-context calls. This run does not include the isolated output-parameter ownership prototype. Log: `/private/tmp/elisa-seed-r70-20261019.log`.

R68 used the isolated snapshot `/private/tmp/elisa-stage1-snapshot-current-20261019-r68`, source-tree SHA-256 `21322cc7640561d7337abec603e253cf437975431cda17b4655f12bc8942ce8c`, and the older StoreFlow Stage0 bootstrap. Before/after provenance matched (stat fingerprint `5037a021cfaf1b36e26162b76d02f8f41e6bad39d6c81cad67b8fa3ab5181e34`). It exited 1 without an object. Narrowing the ownership API from 16 to 11 ensures did not yet clear the remaining positive-result proof: the verifier still projects `.known` from tuple-literal returns such as `(true, binding_id).known`. `semantic_api` also has local-region and new signature/type errors after its diagnostic-export refactor. The source-bound checker passed before this seed, but it does not validate compiler acceptance. An isolated output-parameter API prototype now passes the source-bound checker with the same 11 contracts and 4 loop invariants; it updates 10 production call sites plus probes, but has not been compiled or proof-checked. Log: `/private/tmp/elisa-seed-r68-20261019.log`.

R67 used isolated snapshot `/private/tmp/elisa-stage1-snapshot-current-20261019-r67`, source-tree SHA-256 `a8177eb0ef0f71676a2bd7a91f59aa3217822cb3b52ad1797590b7ce1d669e11`, and the older StoreFlow Stage0 bootstrap. Before/after source hashes and stat fingerprints matched. It exited 1 without an object. The return-literal rewrite did not discharge ownership postconditions: the prover reports tuple-literal projections such as `(true, binding_id).known`, while the named-tuple local form also failed in R65. `semantic_api` has two lookup-context lifetime errors and a pair of `diagnostic_export` argument mismatches caused by an in-flight API signature change. Exact log: `/private/tmp/elisa-seed-r67-20261019.log`.

R65 used isolated snapshot `/private/tmp/elisa-stage1-snapshot-current-20261019-r65`, source-tree SHA-256 `52e755a96102549f053aaf4033e8c60aa0181198b86b420e10be25750ab8ad92`, and the same older StoreFlow Stage0 bootstrap. Before/after provenance matched (stat fingerprint `66616dddfe325d30d4bb0bc1f8549578bd1e080fad73abf8722a91c0e4e67412`). It exited 1 before object creation. This snapshot removes the R64 `diagnostic_export_text` inference errors; remaining semantic API diagnostics include two lifetime escapes through lookup-context calls and an effect grant issue. The earlier 36 explicit type mismatches in `check_fn_value_effect_row.elisa` no longer appear, but value-block mutation diagnostics remain. The ownership lookup postconditions and 10 incremental-facts lifetime errors remain. Log: `/private/tmp/elisa-seed-r65-20261019.log`.

R64 used isolated snapshot `/private/tmp/elisa-stage1-snapshot-current-20261019-r64`, source-tree SHA-256 `73f5f091311bd3cca1f42940a4194959e902752d113d780136831d64282ad2d1`, and the older StoreFlow Stage0 bootstrap SHA above. Before/after provenance matched (stat fingerprint `3251d314446697a96061425420c6ae3f0217fd63784339d0693716ec388eb81e`). It exited 1 without an object. The same 14 `diagnostic_export_text` region-inference failures and three output-to-source lifetime errors remain in `semantic_api.elisa`; the explicit-region-argument experiment happened after this snapshot was taken and was not part of R64. Exact log: `/private/tmp/elisa-seed-r64-20261019.log`.

R63 used the isolated snapshot `/private/tmp/elisa-stage1-snapshot-current-20261019-r63-fixassert`, source-tree SHA-256 `0302f7c33dd7735fb83cd6f7cfefe88beba549ee5bd63f3aa21a71f4d15b8d29`, and the older StoreFlow Stage0 bootstrap SHA-256 `fe96f432eeb205c9ed883b594fb7144cd9aaa9084f6435a83f199f39ba530cd2` (not the pinned clean-Core Stage0 binary). Parsed before/after provenance is identical (tree stat fingerprint `5477d5e742b9d2b647c7413a37b58f4baa6f4d704ddf2afd3903fcf68c2ba5e9`). It exited 1 before producing an object; the seed summary reports 140 diagnostics. The direct log audit found 31 ownership lookup ensure failures plus three loop-invariant notices, 10 incremental-function-facts region/lifetime errors, 22 semantic API region/type errors, and 36 call-argument mismatches in `check_fn_value_effect_row.elisa`. The compiler entered the `-emit obj` build command, but Stage0 failed before creating the object. Exact log: `/private/tmp/elisa-seed-r63-20261019.log`. This is an older-StoreFlow diagnostic run only, not clean-Core qualification; current `FastPushCursor` output remains unverified.

The latest exact-tree seed used source hash `df3462604d94defde4785e6b1e3c32769a56bc52ef184b02e5d3cec9613d06f7` and pinned Stage0 SHA `c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`; before/after fingerprints matched. It parsed past the r60 indentation issue but exited before object generation with 76 filtered diagnostics. Ownership lookup still has 11 lines, including a helper existential ensure that the prover cannot establish and caller postconditions that do not propagate the helper’s owner/sentinel facts. `semantic_api.elisa` rose to 19 diagnostics, mainly region inference and lifetime reports. Log: `/private/tmp/elisa-seed-r61-20261019.log`; snapshot: `/private/tmp/elisa-stage1-snapshot-current-20261019-r61`.

The latest exact-tree seed used source hash `6312a37f852c15f6582aeb33c96bb63400aa90bb4d00dfefe4a09484590d6ba0` and pinned Stage0 SHA `c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`. Before/after source hashes and stat fingerprints matched. It exited before object generation with 68 filtered diagnostic lines, including 13 in `ownership_binding_lookup.elisa`. The strengthened success helper’s `requires ownership_lookup_candidate_matches(...)` was not decomposed by the prover into owner, identity, span and bounds facts, so three helper ensures failed and propagated into both return paths. Log: `/private/tmp/elisa-seed-r58-20261019.log`; snapshot: `/private/tmp/elisa-stage1-snapshot-current-20261019-r58`.

The latest exact-tree seed used source hash `be53a222efe9c4581b02343bc43d6836ce1e4592a5f6f60740f6d362807ca0ce` and pinned Stage0 SHA `c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`. Its before/after source hashes and stat fingerprints matched. It still exited before object generation with 48 filtered diagnostic lines, including two unresolved ownership lookup postconditions at the singleton success returns. Log: `/private/tmp/elisa-seed-r57-20261019.log`; snapshot: `/private/tmp/elisa-stage1-snapshot-current-20261019-r57`.

The latest exact-tree seed used source hash `5d8d405855294618394a6fb72f975b5eb2833f1bcc5e0343b4211d04ce4666e9` and pinned Stage0 SHA `c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`. Before/after source fingerprints matched. It reached semantic analysis and failed before object generation. The targeted filter found 48 lines: 2 ownership lookup postconditions, 5 incremental function-facts lifetime/provenance diagnostics, and 8 codegen declaration diagnostics; other codegen, EASM and semantic diagnostics remain. The ownership lookup failures dropped from 30 after the API return refactor, but were not eliminated. Log: `/private/tmp/elisa-seed-r56-20261019.log`; snapshot: `/private/tmp/elisa-stage1-snapshot-current-20261019-r56`.

The latest exact-tree seed used source hash `3e26fc060bdd52aec49abeb14b4d8b018490a37266841f38ff8b86039e67c315` and pinned Stage0 SHA `fe96f432eeb205c9ed883b594fb7144cd9aaa9084f6435a83f199f39ba530cd2`. Before/after source fingerprints matched. The earlier parser cascade in `incremental_function_facts.elisa` was cleared by changing the effect annotation to bracketed syntax; compilation reached semantic analysis and then exited without an object. The targeted diagnostic filter found 77 lines: 30 in `ownership_binding_lookup.elisa`, 5 in `incremental_function_facts.elisa`, 8 in `codegen_declare.elisa`, and 5 in `easm_compose_text.elisa`. Log: `/private/tmp/elisa-seed-fe96-20261019.log`; isolated snapshot: `/private/tmp/elisa-stage1-snapshot-fe96-20261019`.

The newest completed seed used isolated source hash `ca940d76…` and pinned Stage0 SHA `c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`. It exited before object generation. The same targeted filter found 75 diagnostic lines: `ownership_binding_lookup.elisa` had 30 postcondition failures, `incremental_function_facts.elisa` 5, and codegen declaration/cleanup/call files contributed 16. The log is `/private/tmp/elisa-seed-ca940d76-20261019.log`; the isolated snapshot is `/private/tmp/elisa-stage1-snapshot-ca940d76-20261019`.

The preceding seed used isolated source hash `16de8819…` and the same pinned Stage0 SHA. It also exited before object generation. Its targeted filter found 81 diagnostic lines: 31 in `ownership_binding_lookup.elisa`, 10 in `incremental_function_facts.elisa`, and 16 across codegen declaration/cleanup/call files. The log is `/private/tmp/elisa-seed-16de8819-20261019.log`; snapshot `/private/tmp/elisa-stage1-snapshot-16de8819-20261019`.

The preceding completed seed used source hash `be7fb417cfc1216cec65a452c929f4092927bd140d59ec5f32097d288a6e5fdf` and the same pinned Stage0 SHA. It also exited before object generation. A targeted diagnostic filter found 105 lines: `ownership_binding_lookup.elisa` had 31 postcondition failures, `incremental_function_facts.elisa` 11, and `semantic_api.elisa` 9, including an invalid local region annotation and lifetime failures. The log is `/private/tmp/elisa-seed-be7fb417-20261019.log`.

Snapshot `4c3c169156716395fda2b97a813268cee9275c70b45ba7da89c2d5ff991ad27b` produced 111 filtered lines (11 incremental-facts, 30 ownership, 9 semantic API); log `/private/tmp/elisa-seed-4c3c1691-20261019.log`. Snapshot `eeaa71e3e2edcf89cda402bf74b1a187d3b5df396e1315e93a084fce7b64e711` produced 110 filtered lines (16 incremental-facts, 30 ownership lookup); log `/private/tmp/elisa-seed-eeaa71e3-20261019.log`. Snapshot `89c882cfd6e2fa0bd3a1ac003adc91851cab9745c9005c21ce1a5ffd98db079e` produced 113 filtered lines (16 incremental-facts, 30 ownership lookup, plus driver generic/type errors); log `/private/tmp/elisa-seed-89c882cf-20261019.log`. Snapshot `a73c34bf8a456796fdbac1dd3f2ce43b17acb0196cb6de3a0ac878c8d31380a7` produced 121 filtered lines (26 in incremental facts, 30 ownership lookup); log `/private/tmp/elisa-seed-a73c34bf-20261019.log`. Snapshot `15daf62eb5c63adbfc0813ec599c908a848c09aebddfaa2f82ad5fa019374fba` produced 108 filtered lines (31 in `incremental_function_facts.elisa`) and no object; log `/private/tmp/elisa-seed-15daf62e-20261019.log`. Snapshot `38b66a8b140c2f6320940dc12cd85c8517015551b5adc31ca567709ebbd35989` had the same count; log `/private/tmp/elisa-seed-38b66a8b-20261019.log`. Snapshot `4258617f1e8f619f5b786bc0eac88b93cac54c9b0ea7e7bc2b2f2801ccb35d7a` produced 119 filtered lines (36 in the facts file); log `/private/tmp/elisa-seed-fb55cb24-20261019.log`. Earlier `c14b0cd5` and `ec8eae2e` snapshots had 133 lines; logs `/private/tmp/elisa-goal-current-c14b0cd5-seed.log` and `/private/tmp/elisa-goal-ec8eae2e-seed.log`.

The filtered count fell from 133 to 108, then rose through 121, 113, 110, 111, 105, 81, 75, 77, 48, 48, 68 and 76. The ownership helper’s explicit row facts fixed its three opaque-requires failures, but its existential witness and outer postconditions still do not prove; current semantic API lifetime/inference diagnostics also rose. No Stage1 object has been produced. The query graph changes add an early miss for already-Dirty nodes before input hashing and build source query values directly from a byte span, avoiding an intermediate surface copy. These are plausible incremental-compiler time and allocation savings, but no Stage1 artifact or timings verify them. Current `FastPushCursor` O3 IR/assembly remains unverified.

For comparison only, the counted-fill fixture was compiled to O3 LLVM IR by the pinned Core Stage0 binary. That older compiler emitted a loop capacity check and grow path (`/private/tmp/elisa-stage0-counted-fill.ll`, SHA-256 `67991d7b90d80ef0e23bbd13d2cd00cb3bbc2a3817577e8076d7d6907e9ab35f`). Two additional prebuilt compilers (Stage0 SHA `fe96f432eeb205c9ed883b594fb7144cd9aaa9084f6435a83f199f39ba530cd2` and `2f619df2610dd5de145ec47795ee74e9f6b821da5a4a4d294a87d4dbf69d1240`) emitted the same O3 IR SHA `ab10a37f0bcf38943ac54f8be406167ecea544679ba9509b084b3a32661e6868`, also retaining the hot-loop capacity branch and grow path. These binaries predate or omit the current fast-cursor implementation and do not characterize current source code generation.

## Current counted-fill source audit

### Alias metadata safety

The runtime declaration intentionally leaves `arena_alloc` without an LLVM
return `noalias` attribute. `Arena.end` and `Region.count` are public mutable
state, so a caller can rewind an arena while keeping an earlier pointer and
then allocate overlapping storage. A malloc-style return `noalias` promise
would let LLVM assume those pointers cannot alias and could miscompile valid
source programs. Keep the attribute disabled unless the allocator state and
user overrides enforce disjoint lifetimes; optimize with narrower, locally
proven alias facts where available. This is a correctness constraint on any
alias-driven speedup, not a performance regression measurement.

### Cross-language fixture semantics and Clang control

`darray_counted_fill.elisa` intentionally starts with an empty DArray and does
not call reserve; the optimization under review is whether `FastPushCursor`
inserts one reservation and lowers the push loop efficiently. The comparison
Zig, Rust, and C fixtures explicitly reserve capacity for the same element
count. Therefore this workload measures both the Elisa reserve transformation
and the generated loop, while their fixtures start from reserved storage. For
loop-only parity, compare the emitted loops after reservation (or add a
reserved Elisa control); keep the existing unreserved fixture as the
transformation test.

The Clang 23.1.3 O3 control (`-mcpu=apple-m5`) for the C fixture emits a
vectorized fill and sum. Its fill loop writes eight `i64` values per backedge
using four `<2 x i64>` stores and has no per-element capacity check; its sum
uses four `<2 x i64>` accumulators and a scalar tail. Assembly uses NEON vector
stores for fill and paired vector loads/adds for sum. This is a stronger fill
loop code shape than Zig's saved scalar indexed-store loop, so the target
comparison should distinguish scalar-loop parity from LLVM vectorization.
Artifacts: `/private/tmp/darray-counted-fill-clang.ll` (SHA-256
`a67b43e0a91af3ed49c349a420ad582b7ba4e891d9f2ef56460866ab1476e368`) and
`/private/tmp/darray-counted-fill-clang.s` (SHA-256
`070a7b4a8cb44ec21047c80abd190f9513aa083a1cf7088b3ad0fc931959f78f`).
These are static compiler outputs, not timing evidence. Rust retains its
capacity/grow check and length store in the push loop; its sum is vectorized.

Static review of `FastPushCursor` found no concrete soundness hole for this fixture. The fast path is gated on a fresh unaliased local DArray, scalar elements, exactly one direct push, a literal positive bound within the reserve cap, a zero-based ascending `..<` range, and a loop body limited to the proven straight-line forms. Count reads disable deferred cursor mode. The lowering caches the post-reserve items pointer, biases it by the existing count, indexes stores with this loop’s induction value, and publishes the final count once at loop exit. The narrow contract still depends on the body whitelist and eligibility checks staying fail-closed.

The expected optimized output must still be verified in a current Stage1 O3 build. In LLVM IR, confirm one reserve before the loop, no hot-loop capacity/count header loads, grow edge or per-push count store, a store indexed by the range induction value, and one final count publication. In target-native assembly, compare that loop with Zig’s indexed store, increment, compare and branch at `build/perf-ir-comparison/current-darray-counted-fill/zig.s:153–163`; Rust’s matched loop at `rust.s:83–95` retains the capacity check, grow call and length store. Check that LLVM promotes the emitter’s counter allocas and canonicalizes the cached pointer/index operations. These are acceptance criteria, not observed Elisa machine code; the current Stage1 seed still fails before object emission.
An earlier isolated source snapshot (`2e03e4a94c187dcd992910f4c7a59387425c7edc190ccc498180c96ba03cee18`) also failed before object generation; its historical log is `/private/tmp/elisa-stage1-snapshot-r30.log`.

### Frozen-source gate after the byte-cap and reserve-policy changes

I copied `src/`, `elisacore_std/`, and `manifest.json` to
`/private/var/folders/k7/71kp36qd5_q9_tfp77s2vqzc0000gn/T/elisa-src-pin-20261019-p3i_a4ej`.
The content hash before and after the copy, and before and after the semantic
gate, was `a73ea156621e3d4a6342ac1c89a5df61f07431ca60f7ab795933f411fec043ef`.
The clean Core Stage0 compiler SHA was
`c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`.
`elisac -emit semantic src/driver/elisac.elisa` exited 1 before backend
emission; the log is `/private/tmp/elisa-semantic-frozen-a73ea.log`. This
snapshot includes the 64 MiB logical appended-payload cap, the ABI-stride-aware
trip cap, and the reserve helper selection that uses
`darray_grow_callee(true, ...)` for compiler-inserted geometric reserves.
The three shared-pool region inference diagnostics and the old dotted
`LoopPrereserveLimits` namespace diagnostics were absent. Remaining findings
include 52 StoreThrough reports, 11 failed ensure postconditions and 23
unproven invariant notices. No Stage1 object, LLVM IR or assembly was emitted.

The 64 MiB cap bounds the requested appended payload, not necessarily the
rounded backing-allocation delta when an already-large DArray crosses a growth
boundary. The geometric reserve now matches repeated-push capacity rounding;
that can allocate more than the logical payload before the loop begins. Treat
this cap as a payload bound unless the pre-reserve path also checks the rounded
capacity delta.

### Isolated EASM-label Stage1 seed

The R3-label snapshot (`/private/tmp/elisa-stage1-generic-294e5f91-20261019-r3-label`)
used source-capture map SHA-256
`ab40a7fd9dd4d0af6be705f115080271321c2ee8e625c9599349d8ceb66ff7ac`, with
matching before/after inputs, and pinned Stage0 SHA-256
`191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b`. It
exited 1 after 286 seconds with 73 diagnostics and no object or product. The
captured-source diff against R2-EASM is limited to `src/backend/easm_model.elisa`,
so this isolates that EASM label/proof change; the semantic table/context
lifetime reports and ownership-flow/lookup proof failures remain. The full log
and diagnostics are in that snapshot's `seed.log` and `diagnostics.json`.

The checksum-pinned exploratory Core Stage0 counted-fill artifact
(`/private/tmp/elisa-incremental-goal-ir-20261019/count-elisa-stage0.ll`,
SHA-256 `ceb58f20bd9ba67706604a87abc838d68fced0b9ab314b64358e8062c66627ed`)
still has a capacity comparison and grow edge on each push, and stores the
count-derived index in the loop. It therefore does not meet the FastPushCursor
acceptance criteria. This binary predates the current lowering and cannot
validate it; current Stage1 O3 IR and assembly remain unavailable. The same
fixture's Clang control vectorizes its fill, while the saved Zig fill is scalar
and Rust retains its grow/check path. These are code-shape observations only,
not timing results.

### Current live-source Stage1 seed

Snapshot `/private/tmp/elisa-stage1-live-6c4f8d7c-20261019` used source SHA-256
`6c4f8d7cf7a50e4b2f53ef26aa1ab759b2f8cdbb6cdb7e3f6cb6228b4ec06b9d`, matching
before and after the build, with pinned Stage0 SHA-256
`191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b`. It
exited 1 after 287 seconds with no object or product. Its log reports 72
diagnostic lines, including the remaining `semantic_api` table/context lifetime
errors, ownership-flow/lookup proof failures, and unrelated declaration and
codegen lifetime errors. The live tree received proof-ensure additions in
`assoc_index_impl_scope.elisa` and `assoc_index_membership.elisa` after this
snapshot; these are a narrow semantic-only delta. `src/backend` matches the
snapshot byte-for-byte (directory SHA-256
`2cd8ee55ba0035c699dd78ba3a01214a4d2467000ee0a5e9c2ceb865dfdd84a8`). Thus
the seed provides no Stage1 IR/assembly, but its backend provenance would be
usable for a fixture compile if it produced a Stage1 executable. The failed
gate leaves the current `FastPushCursor` O3 code shape unverified.

### Newer exact-source Stage1 attempt

Snapshot `/private/tmp/elisa-stage1-current-6d906732-20261019` used source
SHA-256 `6d9067324cc90ef566ec2bbde95a4dc3098edc649f39c306c89ba53bc0abf65f`
and source stat fingerprint `d483056cf0f37cdd33417bbfcc9c092484093dfe520f586a95bda421003c6500`;
both matched before and after. Its build recipe hash and stat fingerprint also
matched. It used the pinned Stage0 SHA-256
`191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b`, exited 1,
and produced no object or product. The seed log contains 69 matching
`call may store`, unproven-ensure, or invariant diagnostic lines; those include
22 backend lifetime notices matching R3's backend sources. The log does not
establish that those notices caused the exit. Fourteen unproven ensures are
reported as errors by the semantic severity mapping. The current live source
subsequently simplified `declaration_name_position_lookup.elisa`, so its five
unproven ensures from this seed no longer describe the live file. The log is
`/private/tmp/elisa-stage1-current-6d906732-20261019/seed.log`; IR and assembly
are still unavailable. The full input manifests differed in the external
linker probe cache and seed-configuration fields, so this is source/recipe
stable evidence, not full-manifest-equal evidence.

### Stage0 assembly loop comparison

The Stage0 assembly at `/private/tmp/elisa-incremental-goal-ir-20261019/count-elisa-stage0.s`
shows the same hot capacity-check branch as its IR: `cmp x8, x26` / `b.hi`
skips the grow path only when capacity is available; the loop body then performs
`str x26, [x19, x26, lsl #3]`, updates the count register, and checks the loop
bound. Its cold grow path expands into many arena/reallocation checks. Zig's
saved fill loop is the compact scalar sequence `str [base, index, lsl #3]`,
`add index, #1`, `cmp`, `b.ne`, with no push-capacity branch. Rust's scalar fill
body stores the element and updated length each iteration, compares capacity,
and branches to `RawVec::grow_one` on exhaustion. Clang's control uses NEON
vector stores for eight elements per backedge. Stage0 therefore retains a
per-push capacity branch that Zig's saved loop does not, and misses Clang's
vectorized fill shape. On the successful path, Stage0 keeps the count in a
register, while Rust stores the updated length each iteration; both retain the
capacity check and grow path. These are structural comparisons of the saved
artifacts, not runtime measurements, and they do not describe the current
FastPushCursor lowering.

### Frozen current-source candidate after EASM proof edits

The snapshot `/private/tmp/elisa-stage1-current-db78e7aa-20261019` used source
hash `b5f8d3476f293556ce47e673b28c28462748048f96a5c6d473ff37eeeeefc257`.
Source hash and stat fingerprint, and build-recipe hash and stat fingerprint,
matched before and after the seed. It used pinned Stage0
`191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b`, returned
1 after about 12 minutes, and produced no object or product. Its log contains
12 failed Ensure postconditions, including EASM label/compose and iterator
alias proofs, plus semantic API region-annotation, type, and lifetime
diagnostics. The live tree later changed `easm_compose_text.elisa`, so these
results apply only to the frozen snapshot. Full output is in its `seed.log`;
this run provides no Stage1 IR or assembly.

### LLVM loop-interleave factor probe

The isolated sweep at `/private/tmp/elisa-interleave-sweep-20261019/` extracts
`repeated_sum` from Stage0 O0 IR (input SHA-256
`2ca157a0…`, extracted IR `16f7a0d5…`) and runs LLVM 23.1.3 O3 plus `llc`
for `arm64-apple-macosx27.0.0`, CPU `apple-m5`, `+neon,-sve`. With vector width
2, forced interleave counts 1, 2, 4, and 8 process 2, 4, 8, and 16 `i64`
values per vector-body backedge. Unhinted O3 selects count 4. The count-8
assembly has eight vector accumulators and no stack spill traffic in this small
loop; its 16-value trip matches the saved Zig sum loop, while saved Clang and
Rust loops process 8 values per trip. The probe has no runtime measurements and
uses extracted Stage0 IR, so it does not establish a current-Stage1 speedup.

The setting `LLVMPassBuilderOptionsSetLoopInterleaving(options, 1)` at
`src/backend/codegen_target_machine.elisa:580` enables loop interleaving; it
does not select factor 1. The current Stage1 source has `by interleave(8)` and
`by interleave(16)` metadata paths, but the Go Stage0 bootstrap rejects this
syntax, and no current Stage1 product has emitted the fixture. The factor-8
result is therefore an A/B candidate, not a justification to change LLVM's
default cost model.

The Stage1 metadata path is present in source: the parser accepts only factors
8 or 16, `codegen_stmt_loops` admits plain ranges or named DArray iteration with
one binder, and `tag_loop_interleave_count` attaches
`!{!"llvm.loop.interleave.count", i32 N}` to the loop latch. This confirms the
intended mechanism at source level, but not that a saved compiler product emits
the hint for the benchmark fixture.

### Latest exact-source seed attempt

The 2026-10-19 seed in `/private/tmp/elisa-stage1-goal-20261019/` used the
resolver-patched Core bootstrap SHA-256
`94dfe67385084b5ca2c3667687cefd129a5e014b583b985317ada964d4193378` and the
current source-tree SHA-256
`682da72efe1978c6c65757208c5008cb294bf1705c465d655ca77a1dd97e5469`
(stat fingerprint `e02d81e376d2eb2cc1bc26cb4ee334a6566fa6f1a511fbd97f78dac9ec599168`).
It exited 1 before object generation. Remaining errors include `semantic_api`
region/type mismatches and lifetime escapes, an AST file-region mismatch in
`elisac_source_probes`, an `input_source` escape in `incremental_function_facts`,
ownership-flow proof obligations, and EASM/codegen lifetime and proof findings.
The log is `/private/tmp/elisa-stage1-goal-20261019/seed.log`; it emitted no
Stage1 IR or assembly, so the current FastPushCursor output remains unverified.

The counted-fill fixture's accumulator header does not bypass the ordinary
`Stmt.For` lowering: `for_bind` is the loop modifier (`mutable`/`parallel`),
while the accumulator is represented by the loop-header wrapper. The loop
therefore reaches `emit_loop_prereserve`; for this fixture its literal
`0..<4,000,000` range and single scalar `push` satisfy the direct-index
candidate checks. The current emitter is intended to bind that range counter,
store through the once-biased items pointer without the hot capacity branch,
and commit `final_count` after the loop. This is a source-path audit only.
The older Go Stage0 artifacts retain the capacity branch because they predate
this FastPushCursor lowering; they do not establish whether current Stage1 emits
the intended loop.

### Clang interleave-count timing probe

The isolated C benchmark in `/private/tmp/elisa-interleave-timing-20261019/`
compares the saved Clang, Rust, and Zig sum kernels against the same C kernel
compiled by Clang 23.1.3 with
`#pragma clang loop vectorize(enable) interleave_count(8)`. The generated
factor-8 assembly processes 16 `i64` values per vector-body trip using eight
NEON accumulators, without stack spills. In 15 randomized-order trials over a
shared 64 MiB input, median time was 0.0191 ns/byte for the factor-8 C kernel,
0.0205 for Clang default, 0.0215 for Rust, and 0.0230 for Zig. The ranges
overlap substantially, so this is suggestive evidence only; it is one process,
one machine, and a C pragma experiment, not a measurement of Elisa or proof
that factor 8 is generally better. Checksums matched across all four kernels.
The exact samples are in `timing.json`; `factor8.ll` and `factor8.s` record the
compiler output. A larger 21-trial run in `timing-large.json` used a 256 MiB
array: median ns/byte was 0.012865 for default Clang, 0.012808 for Rust,
0.012838 for factor-8 C, and 0.014081 for Zig. The factor-8 median is effectively
tied with Clang and Rust; its individual range overlaps all three. This does
not support selecting factor 8 as a general speed win, though it does show no
large regression on this sum kernel. The result still uses the saved native
libraries and a single machine/process, not Elisa Stage1.

A further control compiled the same C loop with only `interleave_count(8)` and
no `vectorize(enable)`. Its optimized AArch64 assembly was byte-for-byte equal
to the `vectorize(enable) interleave_count(8)` assembly. The loop still has
vector width 2, eight accumulators, and 16 `i64` values per backedge. Thus the
interleave-count hint alone is sufficient for LLVM to vectorize this sum loop;
that matches the advisory metadata form in Elisa source. Files are
`factor8_hint_only.{c,ll,s,o}` and `factor8_hint_only.dylib`.

### FastPush lowering source audit correction

A prior audit incorrectly treated the right-hand names in optional `is` tests in
`codegen_container_ops.elisa` as undeclared variables. Elisa binds those names
when the optional has a value; the source-shape checks in
`test/proofs/check_backend_fast_push_cursor.py` also expect these guarded paths.
The direct push uses a zero-based range index with `direct_items`, which was
biased once by the pre-loop count in `codegen_stmt_for_shapes.elisa`. It omits
per-push count publication by design; after the matched loop shape returns
`Open`, `codegen_stmt_loops.elisa` writes `FastPushCursor.final_count` to the
array header. This resolves the suspected source-level count bug. It does not
replace inspection of current Stage1 IR/assembly or runtime comparison, which
are still unavailable.

### 2026-10-19 exact-backend Stage1 seed attempt

The isolated run at `/private/tmp/elisa-semantic-fixes-current/` used source
SHA-256 `4ca5153db650dae57c0dbf866e0bf361afd02bc12436eb50952b2cbc7b5b6474`,
stat fingerprint `d93fc65fb98cc3fe7a03fa46525946ef86d659bfa4e6a916bb27f539893c8860`,
and build recipe SHA-256
`f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`; preserved
before/after input records match. The run exited 1 before producing a compiler
product or usable object/IR/assembly. Its log reports the known `semantic_api`
region/type/lifetime errors, the source-probe region mismatch, plus ownership,
EASM, and codegen proof/lifetime findings. The log is `seed.log`. The five
relevant FastPush backend files (`codegen_container_ops`,
`codegen_stmt_for_shapes`, `codegen_stmt_loops`, `codegen_loop_prereserve`, and
`codegen_struct_table`) are byte-identical between that snapshot and the live
checkout at review time. A directory diff also found no other backend source
differences in that snapshot.
This qualifies the failed analysis only for source snapshot `4ca5153`; the live
tree has newer semantic edits. Generated machine code remains unverified.

The canonical `bin/elisac-stage1` and `build/elisac_stage1.o` also exist, but
are dated 2026-10-11. The binary SHA-256 is
`26aa2625f28cc2f0adabe9a6f6255376f3198313fb55480e1ea49f8261b3e946`; it predates
the current source and is not used as current codegen evidence.

### 2026-10-19 e54 exact-backend Stage1 attempt

The frozen run at `/private/tmp/elisa-semantic-fixes-current/` captured source
SHA-256 `e54bc0f60647b991bdf56db33411b751907c12be5d16b188daaeaab52007952c`,
stat fingerprint
`1e051c5781f09b1533429048f9eae0cd608d7054b434e9e2e38f90ce28d4b5b0`, and
build recipe SHA-256
`f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`. Before
and after source, stat, and recipe provenance match. It used the pinned Core
Stage0 binary SHA-256
`191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b` and
exited 1 without a Stage1 object or product. The gate record is
`/private/tmp/elisa-semantic-fixes-current/gate-e54-result.json`; the log is
`seed-e54.log` in that directory.

The captured `src/backend` tree is byte-identical to the live checkout. Across
the full `src` tree, only `semantic/check_firm_arg_type_mismatch.elisa` and
`semantic/check_uninitialized_zeroed.elisa` differ. The seed therefore
confirms that the current FastPush backend sources were accepted far enough to
reach semantic and backend lifetime/proof diagnostics, but it provides no
current LLVM IR or assembly. Remaining diagnostics include the
`semantic_api` session/table region mismatch and local-storage escapes, the
`elisac_source_probes` AST region mismatch, an `incremental_function_facts`
input-region escape, ownership proof obligations, and EASM/codegen lifetime
findings. This evidence applies to the captured snapshot only; current
FastPushCursor machine code remains unverified.

### 2026-10-19 forward-bool bootstrap Stage1 attempt

The later frozen run at
`/private/tmp/elisa-stage1-forward-bool-66a1cf93-20261019-r1/` used source
SHA-256 `358ee26e7a354ddb192d4e37a26664c1a0a6a2fb48c2937f0fd0169e7faabf73`,
stat fingerprint
`84d68076cca97e618bcef5ace3bcc7624442af5bd7750073d1049922a695a3ba`, and
the same build recipe SHA-256
`f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`. Before
and after provenance match. It used Core Stage0 SHA-256
`0b720222d99686cd8244f7cbceccb5d0ace3516ff5890c2379d2f9ed68acbe6f` and
exited 1 after 188.7 seconds with 87 diagnostic records and no Stage1 object
or product. The gate is `gate-result.json`; full diagnostics and log are
`diagnostics.json` and `seed.log` in that directory.

Its backend differs from the live checkout only in `easm_compose_text.elisa`
and `easm_model.elisa`; the FastPush lowering files match. This is still not a
whole-tree current-source build: the captured `src` differs from live in 15
files, including semantic API and source-probe inputs. The diagnostics include
ownership lookup proof failures, semantic API session/table lifetime escapes,
the source-probe region escape, and EASM/codegen proof and lifetime findings.
No LLVM IR, assembly, or Elisa runtime result was produced, so this seed does
not change the performance comparison.

An adjacent legacy pair exists at
`/private/tmp/elisa-stage1-current-6d906732-20261019/darray_counted_fill.ll`
and `darray_counted_fill.llvm23-m5.s` (SHA-256
`e09f31ac5d0a34e2883208e75fd2e153337b63bd6a4026d3a08fba4e06bd2397` and
`635b7aae3481e235baaf031d4519a63808289e732c1af8592933801b56874122`). The IR
contains a per-push `darray.push.capacity.ok.not.not` branch and grow path.
There is no adjacent command or artifact manifest tying these files to the
failed Stage1 seed; its `build/` and `bin/` directories are empty. The block
names also predate the current `push.cap.ok` lowering. Treat this pair as an
unqualified older-codegen baseline, not current FastPush evidence.

### Counted-fill Clang interleave control

To test whether a larger loop hint helps the fill specifically, I compiled the
tracked C fixture (`darray_counted_fill.c`, SHA-256
`8ad2952a2ed84b7c91990dea93f88b03470eb7e946b59a261c84a74f1f006718`) with
Clang 23.1.3, `-O3 -mcpu=native`, adding only
`#pragma clang loop interleave_count(N)` before the push loop for N = 2, 4, 8,
and 16. The baseline is the same C source with no pragma. All generated loops
vectorize at width 2: the default and N=4 assembly are byte-identical and
process 8 `i64` values per backedge; N=2 processes 4, N=8 processes 16, and
N=16 processes 32. The larger factors increase static loop-body size; N=16
also adds callee-saved vector-register traffic. Assembly and IR are saved in
`/private/tmp/elisa-fill-factor-sweep-20261019/`; `timing-fill-processes-31.json`
contains each binary hash and randomized trial order.

In 31 randomized whole-process runs, median times were 6.029 ms (default),
6.442 (N=2), 6.245 (N=4), 6.069 (N=8), and 6.283 (N=16); Zig ReleaseFast was
7.548 ms and Rust opt-level 3 was 8.107 ms. Checksums matched. The middle 50%
of all C runs fell below Zig's middle 50%, but the samples include process
startup, allocation, fill, sum, and printing, and full ranges overlap. The
default and N=8 medians are nearly tied, and N=16 has no measured advantage.
This makes the existing N=8 Elisa metadata path a reasonable A/B candidate for
the counted fill, but does not justify forcing it or N=16. The C loop is a
control only; no current Elisa Stage1 IR or timing exists to show that Elisa's
direct-index path vectorizes the same way.

### 2026-10-19 record-view Core bootstrap attempt

The record-view run at
`/private/tmp/elisa-stage1-record-view-ea4e03e6-20261019-r1/` captured source
SHA-256 `358ee26e7a354ddb192d4e37a26664c1a0a6a2fb48c2937f0fd0169e7faabf73`,
stat fingerprint
`ca48e6bbbfed34c9ce7599dfa7fd769c7fa82ed53185131cdd5fc85a4c43f5d6`, and
recipe SHA-256
`f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`. It used
Core bootstrap SHA-256
`8d7f0b902e5cfec40145a265d9a02ff75e14f0aea0f431a944ae2526a15e6d4b`; the
before/after inputs matched. The attempt exited 1 after 212.6 seconds with 69
diagnostic records and no Stage1 object or product. The gate is
`gate-result.json`, with full diagnostics and log beside it.

This is the same frozen source baseline as the forward-bool attempt above,
with a different Core bootstrap. Its FastPush lowering files match the live
checkout; only the two EASM files differ within `src/backend`. The source tree
still differs from live in 15 files, so the run cannot qualify current-tree
codegen. Remaining diagnostics include `codegen_declare` (8), `codegen_call`
(4), EASM compose (7), EASM parse and `semantic_api` (6 each), and one
`incremental_function_facts` input-region escape. Ownership proofs and other
cleanup/block lifetime errors also remain. It produced no LLVM IR or assembly;
current FastPush machine code remains unverified.

### 2026-10-19 direct Stage0 counted-fill baseline

I compiled the tracked Elisa counted-fill fixture directly with the pinned Core
Stage0 binary from the record-view seed (binary SHA-256
`8d7f0b902e5cfec40145a265d9a02ff75e14f0aea0f431a944ae2526a15e6d4b`):
`elisac -emit llvm -O3`. The emitted IR is
`/private/tmp/darray_counted_fill-stage0.ll` (SHA-256
`ab10a37f0bcf38943ac54f8be406167ecea544679ba9509b084b3a32661e6868`); lowering
with LLVM 23 `llc -O3 -mcpu=apple-m5` produced
`/private/tmp/darray_counted_fill-stage0.s` (SHA-256
`48e54e03ec4ee692535045175ac58b7a0d7c6aa77487305b0e629dfc685712f3`).

This is a fresh, reproducible Stage0 baseline, not output from the current Stage1
source. LLVM vectorizes the checksum to four `<2 x i64>` accumulators and eight
values per backedge, but the fill loop still has a capacity compare/branch every
push and enters the shared growth CFG on the false edge. Its hot path stores via
`[items, count, lsl #3]`, increments count, and checks the loop bound after that
capacity branch. Zig ReleaseFast emits the fill as the simpler four-instruction
loop `str; add; cmp; b.ne`, with no per-push capacity check. Rust O3 keeps a
`Vec` capacity test and count publication in its loop, with a growth call on the
slow path. The checksum vectorization matches the earlier C/Clang and Rust
shapes; the fill loop does not match Zig's shape yet.

This is the concrete target for the current FastPush work: eliminate the repeated
capacity/growth branch while preserving the final count and nonzero-base semantics.
The current Stage1 build attempt (snapshot `c62599a`) was stopped by the 6 GiB
memory guard before producing diagnostics or an object, so these observations
cannot confirm whether current FastPush emits that target shape. The Core
Stage0-generated assembly is useful as a baseline only; it must not be reported
as current Stage1 output.

### 2026-10-19 current-backend Stage1 bootstrap attempt

I captured a frozen tree at source SHA-256
`e57cc38b7e3b192a6c209029f7cb9e11798535e48f14e8fd5321462018ee4430` and recipe
SHA-256 `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e` in
`/private/tmp/elisa-stage1-snapshot-current-20261019-r73-fastpush/`. The pinned
Core Stage0 bootstrap was `fe96f432eeb205c9ed883b594fb7144cd9aaa9084f6435a83f199f39ba530cd2`.
I set the compiler-self-build optimization to `-O2` and the RSS cap to 8 GiB;
the build ran about 230 seconds and exited 1 on semantic region/lifetime
diagnostics, not the memory guard. The source/stat/recipe fingerprints recomputed
after the attempt exactly match the pre-build values. No Stage1 object, product,
or workload IR was produced.

The tail diagnostics include `elisac_source_probes.elisa:285` argument 22/23
region escapes and `semantic_api.elisa` argument-2 escapes at lines 107, 871,
889, and 994. Since the capture, live source advanced to SHA
`3ecd69adcd391e909b2c60826552e442a771f76fe5b15dfd630f295ac839065f`; the
attempt includes the same `src/backend` and counted-fill fixture bytes, but is
not a full-current-tree result. Reducing bootstrap optimization avoided the
previous RSS guard stop, but current FastPush IR remains unavailable until the
semantic gates pass in a newer pinned tree.

### 2026-10-19 latest-tree Stage1 bootstrap attempt

I repeated the bootstrap from a fresh frozen snapshot at source SHA-256
`3ecd69adcd391e909b2c60826552e442a771f76fe5b15dfd630f295ac839065f` and recipe
SHA-256 `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e` in
`/private/tmp/elisa-stage1-snapshot-current-20261019-r74-fastpush/`. It used the
same pinned Core Stage0 binary (`fe96f432…`), `-O2` for the compiler
self-build, and an 8 GiB memory cap. It exited 1 after roughly four minutes on
source diagnostics; the guard did not stop it. The source/stat/recipe fingerprints
recomputed after the attempt exactly match the pre-build inputs. The temporary
build and product directories are empty.

The last diagnostics again include the `elisac_source_probes.elisa:285`
argument-22/23 region escapes and `semantic_api.elisa` argument-2 escapes at
lines 107, 871, 889, and 994. This confirms those wrapper lifetime diagnostics
remain in the latest captured tree, even though the `resolve_scope` and
`semantic_types` resolver-surface edits are included. No Stage1 product or
counted-fill IR/assembly was produced. The next useful build should wait for the
source-probe/API region fixes, then recapture the tree and retry; another
optimization-level change alone is not supported by this failure.

The remaining wrapper error has a source-level signature mismatch: the snapshot-aware
diagnostic API ties `Ast::File&` to the diagnostics output region (`@output`), and
its collector sibling ties the read-only `Ast::File&` to the mutable `SymbolTable`
region (`@destination`). The parser owns AST side tables in the longer-lived source
region, while the diagnostics/table are intentionally reclaimed in nested regions.
The API/compiler-fix thread has been given this decoupling target (`@file` for the
AST input, independent from table/diagnostic output regions); it must also preserve
the synchronous lifetime of lookup session/context captures. This is the current
bootstrap prerequisite before a Stage1 counted-fill comparison can be produced.

### 2026-10-19 FastPush source audit (no emitted output)

A follow-up audit corrected an initial misread of Elisa's optional pattern
syntax: `optional is name` binds the unwrapped value, so identifiers such as
`direct_counter_slot`, `initial_count`, `push_cursor_slot`, `biased_items`,
`cached_items`, and `updated_cursor_slot` are valid bindings, not missing locals.
The direct counted-fill path biases the reserved items pointer by the existing
count, uses the zero-based range induction value for indexing, and publishes the
precomputed checked final count (`base_count + trip count`) once at loop exit.
Its fail-closed eligibility checks keep unsupported bodies on the normal push
path. No source repair is indicated by this audit.

This confirms the intended code shape statically, but current Stage1 LLVM IR and
assembly are still unavailable: recent full-tree bootstraps exit on semantic
region/proof diagnostics before emitting the fixture. The Zig-like hot loop
therefore remains a design target until a current Stage1 build produces it.

### 2026-10-19 current-tree Stage1 retry after API region split

I froze the shared source tree at SHA-256
`6459ca9ae48f5357d00ba32e263e7a1570ce8abec03b3244c6c51f7933892d86` in
`/private/tmp/elisa-stage1-current-fastpush-20261019-r1/` and confirmed the
FastPush backend files and semantic API/source-probe inputs match that snapshot.
The seed used the Core Stage0 binary `c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`,
`-O2`, and an 8 GiB RSS ceiling. It ran about four minutes, then exited 1 with no
Stage1 object or product. `inputs.json` records the tree and build recipe hashes.

The API region split changed but did not clear the relevant diagnostics:
`semantic_api.elisa:895` expects `mutable SymbolTable& @semantic_table` but gets
`SymbolTable`, then reports region escapes through arguments 22/23;
`elisac_source_probes.elisa:285` still reports arguments 22/23 escaping
`semantic_gate`. Other visible diagnostics include an inferred-region value
stored into a longer-lived table at `semantic_api.elisa:866` and function-local
storage escapes through argument 2 at lines 107, 871, 889, and 994. These exact
findings were sent to the API and incremental-compilation owners. The retry
produced no counted-fill IR or assembly; once those gates are fixed, the next
comparison should inspect the FastPush loop before running Zig/Rust timing.

### Excluding the older 6d906 counted-fill IR

I found `/private/tmp/elisa-stage1-current-6d906732-20261019/darray_counted_fill.ll`
and its Apple M5 assembly, which retain a capacity test and per-trip count stores
despite a 32,000,000-byte pre-reserve. This is not evidence about the newer
FastPush source. The Stage1 binary copies in the nearby snapshots all hash to
`26aa2625…`; their embedded provenance records source tree `ca7db887…`, revision
`f7b6c4a…`, and a 2025-10-11 build. That product predates FastPush, and no manifest
ties the 2026-10-19 IR file to a newer compiler binary. Keep it out of current
Stage1 comparisons; it is only a stale-product reference shape.

### 2026-10-19 current-tree retry after explicit table-region edit

The next frozen snapshot is `/private/tmp/elisa-stage1-current-fastpush-20261019-r2/`;
its source tree SHA-256 is `512a170234421bfdfa76e587a7d5f55bb5731cd51d7556623647494eb6bfd8f0`
and its recipe SHA-256 is `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`.
The run used Core Stage0 binary `775bd21841993d247b1c6c87153b2f5f987a5f572fed3286f2ee82481f7cfc13`,
`-O2`, and an 8 GiB RSS ceiling. The frozen input check passed after the run, but
Stage0 exited 1 and produced no object or product. This bootstrap is marked
regressed by its own qualification manifest (+20 ownership proof diagnostics),
so this attempt is diagnostic only.

It exposed an invalid annotation in the table-region edit:
`semantic_api.elisa:894` reports that `@semantic_table` is valid only on a
function return type, not on a named value. At line 895, the callee still expects
`mutable SymbolTable& @semantic_table` and receives a `SymbolTable` value. The
call also reports region escapes through arguments 22/23; the source-probe call
at `elisac_source_probes.elisa:285` still reports the same argument pair escaping
`semantic_gate`. Other visible diagnostics include the inferred-region-to-table
escape at `semantic_api.elisa:866` and argument-2 local-storage escapes at
107, 871, 889, and 994. The exact messages were sent to the API and
incremental-compilation owners. No counted-fill IR or assembly was emitted.

### 2026-10-19 source-stable semantic recheck and Stage0 artifact exclusion

I ran the current driver through the qualified Core Stage0 compiler's semantic
emit using live source tree SHA-256
`1aa2424c41e20e4124c7b1dc3b14fd65c9376bb5fc40202ed350e007d3ae30a1` and recipe
`f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`. The
semantic-only compile exited 1; its 9.1 MiB log is
`/private/tmp/elisa-semantic-live-20261019.log` (SHA-256
`7d521d33f3e5a894f31846c889b664619fa356bd71fc63895afa958ca7828665`). The
wrong mutable-reference diagnostic at `semantic_api.elisa:895` from the older
snapshot is gone, but argument-22/23 lifetime escapes remain there and at
`elisac_source_probes.elisa:285`; other API lifetime findings remain at lines
866, 871, 889, and 994. No Stage1 product or counted-fill IR/assembly was
produced.

A standalone `-emit llvm -O3` compile of the fixture produced
`/private/tmp/elisa-counted-fill-go-stage0-baseline.ll`, SHA-256
`ab10a37f0bcf38943ac54f8be406167ecea544679ba9509b084b3a32661e6868`. This
artifact came from the Go Core Stage0 compiler, which does not implement the
Elisa-source `FastPushCursor` emitter. It repeats the old Stage0 shape with a
capacity branch per push and is not evidence about FastPush. Current Stage1 IR
and assembly remain unverified; the next valid comparison requires a Stage1
product built from one frozen source tree.

### 2026-10-19 semantic recheck after proof-gate edits

The follow-up semantic-only compile used the next stable tree SHA-256
`dced0b50cb64ce489fa4815bb3c00362bb733e4b586380ebbee96a5fa8f2cc4c` with
unchanged recipe `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`.
It ran with qualified Core Stage0 `3bf03a3b901060890935e4c664adfa96a4ff8b71cb1b8884315a23b95de37f1e`,
exited 1, and emitted no Stage1 object. The 9.1 MiB log is
`/private/tmp/elisa-semantic-live-dced0b50.log` (SHA-256
`4def9e1b0083f5c9725560a481c33c6a705e0fc1253f9552a30a14a81a0523c6`). The
filtered diagnostic tally fell from 69 on tree `1aa2424c…` to 65; the EASM
entry-invariant and two iterator-alias failures were reduced, while three
`easm_compose_span` postconditions and two iterator postconditions remain.
The semantic API lifetime errors are unchanged at lines 866, 895 (arguments
22/23), 107, 871, 889, and 994; source probes still reports arguments 22/23 at
line 285. No counted-fill IR or assembly was produced, so the FastPush machine
code comparison remains pending. The interactive shell had no
`ELISA_DISABLE_MEMORY_*` variables set, so the default memory speed and reserve
policies were enabled for the attempted source build; the wrapper does not record
this environment in its manifest, so future counted-fill artifacts should record
these toggles explicitly.

### Cached Stage1 binary inventory

I checked every `bin/elisac-stage1.provenance.json` under `build/`. The most
recent cached product is SHA-256 `5888942e…`, built from source tree `e6a3906e…`;
its saved `codegen_container_ops.elisa` does not contain `FastPushCursor`. Several
other snapshots do contain the FastPush source, but their provenance records all
point to product SHA-256 `26aa2625…` and source revision `f7b6c4a…` from the older
compiler. The remaining cached products also have non-FastPush emitter source.
No cached product is built from the live FastPush implementation, so none can
generate authoritative current FastPush IR in place of a successful seed.

### LLVM C API probe for cheap machine-instruction hoisting

I tested whether the historical `llc --hoist-cheap-insts` improvement can be
requested through the C API used by Elisa. A standalone LLVM 23.1.3 driver calls
`LLVMParseCommandLineOptions` with `--hoist-cheap-insts` before creating the
target machine and emitting the exact same optimized `.extend` IR to Apple M5
assembly. The default assembly keeps `dup.2d v4, x20` in the fill-loop block;
with the option, the equivalent `dup.2d v1, x20` is emitted in the preheader
and disappears from the loop body. This confirms the option is reachable through
the C API as an experiment, but it does not test adding this option to Elisa's
existing parser call, current Stage1, or the FastPush fixture. The live
`codegen_target_machine.elisa` already parses `-unroll-threshold-aggressive=600`
once in its O3 path, so the C API mechanism is present; adding the hoist option
to that invocation would not require a new binding. The C API header explicitly
warns that option interpretation is not stable across LLVM versions, and this
process-global flag needs broader spill and runtime checks before use. The
installed `llvm-c/TargetMachine.h` exposes target-machine settings such as CPU,
features, optimization level, ISel, and outlining, but no per-machine LICM
setting; the tested route is therefore a global LLVM command-line option rather
than a stable per-module control. Parsing the option after
`LLVMCreateTargetMachine` but before `LLVMTargetMachineEmitToFile` produced the
same hoisted assembly byte-for-byte, so target-machine construction does not
need to change for an A/B hook in Elisa's optimization/emission path.
Because the flag is process-global, installing it only on the first O3 module
would make later O1/O2 output depend on module order. The live backend now parses
the options once before the first optimized module instead, making the opt-in
consistent across mixed-level module order: set
`ELISA_LLVM_HOIST_CHEAP_INSTS=1` before starting the compiler. It remains
disabled by default. The integration still needs same-process O1→O3→O1 and
O2→O3→O2 IR/assembly, spill, and retired-instruction checks; no current Stage1
build was available to validate the changed call path. The existing
`cross_language.sh` runner preserves this variable in its compiler child
environment and includes it in environment provenance hashes, so it can be used
for a recorded future A/B without changing the runner's environment filtering.

Probe source: `/private/tmp/llvm_c_api_hoist_probe.c` (SHA-256
`9dc3266952e9fcc3d888147d4eb1a21ddea67b8076575b6106a7f18daaae6cc6`). Input
IR: `build/ir-probes/current-stage0-vs-zig-rust-counted-fill-20261013/current-stage0-extend-fill.O3.ll`
(SHA-256 `af08bc17042bdeda645e0819132fbf23a44c0a492218cb974c3c9736eeb50d11`).
Default and hoisted outputs are `/private/tmp/llvm_c_api_default.s` (SHA-256
`4537fd8ac5a2a3a49050b6fade3130457d53840d005437f1c3dd4d7622842242`) and
`/private/tmp/llvm_c_api_hoist.s` (SHA-256
`7dfeab393b9048dc37e6f30a8af701f9f560ae45032100908ee473a2a0cbadb8`). The
late-parse variant is `/private/tmp/llvm_c_api_hoist_probe_late.c` (SHA-256
`feb786c971c8c7cdf4b70b6ed46985bf9e5d8fc0a9d26cb1d5016e59762e7340`); its
default and hoisted output hashes match those above.

### Stage1 hook validation attempt

I ran `scripts/elisac_stage1.sh --seed` with the qualified Core Stage0 bootstrap
`c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04` at `-O2`
against source tree `fbf86f4e705060b46955d0e89fecaa28ab00753015524c885d48f1b7481a724b`
(stat fingerprint `846a278595c856ffd531c4c8a69d734b25c4e07aae188c59b677a7fc32ae5576`,
recipe `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`).
Before and after source fingerprints matched. The bootstrap exited 1 without
producing an object or Stage1 product; the remaining visible blockers included
`semantic_api.elisa:895` region/type mismatches and the source-probe call at
`elisac_source_probes.elisa:285` with an incorrect generic-argument count and
region escapes. This means the `ELISA_LLVM_HOIST_CHEAP_INSTS` backend hook has
not yet been compiled or exercised through Elisa. A small subsequent edit
replaced a `usize` to `i32` count conversion in that hook with an explicit
argument count, so the live tree now needs a fresh source-pinned validation.

### 2026-10-19 stable semantic gate after resolver-region edits

I ran the qualified Core Stage0 compiler (`c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`)
with `-emit semantic -O2 src/driver/elisac.elisa` against frozen input map
source tree `bc0303e7d33196376df739e0416472d74762cc77e089e379943deb61520ea4b9`
and recipe `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`.
The before/after provenance manifests match. It exited 1 after 205 seconds with
123 non-warning diagnostic records; 58 are in `semantic_api.elisa`, 12 in
`easm_compose_text.elisa`, eight in `codegen_declare.elisa`, and six in
`easm_parse.elisa`. The API diagnostics include the destination-table and
session/context borrow-region mismatch at line 895, plus source-backed values
being passed through function-local storage. The backend still reports
`StructTable`/`GenericTable` lifetime escapes through emission helpers. The
mutable `argv_count` correction in `codegen_target_machine.elisa` is included in
this snapshot and no longer appears as a diagnostic. This was a semantic-only
check: it emitted no Stage1 object, LLVM IR, or assembly, so current FastPush
performance remains unverified. Exact log and manifests are under
`/private/tmp/elisa-semantic-live-bc0303e7/`.

### 2026-10-19 semantic gate after the lookup-borrow mapping correction

The next source-pinned semantic-only run used tree SHA-256
`8eeeaeef8eb983e8e61d18ebd9e5d7daaae220bed8297a70e6325645066fd3b3` and the
same recipe hash. Before/after manifests match. It exited 1 with 122
non-warning diagnostic records and no object or product; exact log and manifests
are under `/private/tmp/elisa-semantic-live-8eeeaeef/`. The `session_borrow` /
`request_borrow` generic mapping removed the argument-22/23 borrow-region errors
at `semantic_api.elisa:895`. The remaining argument-2 error says the local is
stack-backed even with an explicit `@semantic_table` annotation and `&table`,
so the next fix likely needs a region-owned slot for the `SymbolTable`. The run
briefly overlapped a parser race compile at startup; do not use its wall time as
a benchmark. No current Stage1 LLVM IR or assembly was emitted.

The 122 records classify as 53 function-local reference escapes, 29 call-based
region-value escapes plus one fresh-container region escape, two session-region
conflicts, one mutable-table argument mismatch, one invalid named-region
annotation, 26 loop-invariant failures, eight ensure failures, and one
unproved decreases measure. The EASM loop and ensure obligations are separate
from the backend `StructTable`/`GenericTable` lifetime group; fixing one category
will not by itself qualify an object build.
