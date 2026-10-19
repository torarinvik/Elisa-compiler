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
