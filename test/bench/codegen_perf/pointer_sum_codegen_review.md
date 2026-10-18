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

Elisa here was built by the pinned Core Stage0 compiler, not the current Stage1
product. This result says nothing about current Stage1 or `darray_counted_fill`.
For that benchmark, the acceptance check remains the actual O3 IR/assembly: one
pre-loop reserve, no hot-loop capacity/grow edge, direct indexed store, and one
final count commit.

## Latest pinned Stage1 seed

The newest completed seed used isolated source hash `eeaa71e3e2edcf89cda402bf74b1a187d3b5df396e1315e93a084fce7b64e711` and pinned Stage0 SHA `c8010a364e5b075a234b6f0e2e085053e3de2d4cad4322b5190569f20d513d04`. It exited before object generation. A targeted diagnostic filter found 110 lines: `ownership_binding_lookup.elisa` had 30 postcondition failures, `incremental_function_facts.elisa` 16, and the largest backend cluster was 8 in `codegen_declare.elisa`. The log is `/private/tmp/elisa-seed-eeaa71e3-20261019.log`.

Snapshot `89c882cfd6e2fa0bd3a1ac003adc91851cab9745c9005c21ce1a5ffd98db079e` produced 113 filtered lines (16 incremental-facts lifetime errors, 30 ownership lookup, plus driver generic/type errors); log `/private/tmp/elisa-seed-89c882cf-20261019.log`. Snapshot `a73c34bf8a456796fdbac1dd3f2ce43b17acb0196cb6de3a0ac878c8d31380a7` produced 121 filtered lines (26 in incremental facts, 30 ownership lookup); log `/private/tmp/elisa-seed-a73c34bf-20261019.log`. Snapshot `15daf62eb5c63adbfc0813ec599c908a848c09aebddfaa2f82ad5fa019374fba` produced 108 filtered lines (31 in `incremental_function_facts.elisa`) and no object; log `/private/tmp/elisa-seed-15daf62e-20261019.log`. Snapshot `38b66a8b140c2f6320940dc12cd85c8517015551b5adc31ca567709ebbd35989` had the same count; log `/private/tmp/elisa-seed-38b66a8b-20261019.log`. Snapshot `4258617f1e8f619f5b786bc0eac88b93cac54c9b0ea7e7bc2b2f2801ccb35d7a` produced 119 filtered lines (36 in the facts file); log `/private/tmp/elisa-seed-fb55cb24-20261019.log`. Earlier `c14b0cd5` and `ec8eae2e` snapshots had 133 lines; logs `/private/tmp/elisa-goal-current-c14b0cd5-seed.log` and `/private/tmp/elisa-goal-ec8eae2e-seed.log`.

The filtered count fell from 133 to 108, then rose to 121, 113, and 110. Ownership lookup still contributes 30 proof failures, while incremental-facts lifetime errors have fallen to 16. No Stage1 object has been produced. The query graph changes add an early miss for already-Dirty nodes before input hashing and build source query values directly from a byte span, avoiding an intermediate surface copy. These are plausible incremental-compiler time and allocation savings, but no Stage1 artifact or timings verify them. The live source advanced again after the `eeaa71e3` snapshot; at the latest check it was `4c3c1691…`. Pin a fresh exact tree after edits settle. Current `FastPushCursor` O3 IR/assembly remains unverified.

For comparison only, the counted-fill fixture was compiled to O3 LLVM IR by the pinned Core Stage0 binary. That older compiler emitted a loop capacity check and grow path (`/private/tmp/elisa-stage0-counted-fill.ll`, SHA-256 `67991d7b90d80ef0e23bbd13d2cd00cb3bbc2a3817577e8076d7d6907e9ab35f`). Two additional prebuilt compilers (Stage0 SHA `fe96f432eeb205c9ed883b594fb7144cd9aaa9084f6435a83f199f39ba530cd2` and `2f619df2610dd5de145ec47795ee74e9f6b821da5a4a4d294a87d4dbf69d1240`) emitted the same O3 IR SHA `ab10a37f0bcf38943ac54f8be406167ecea544679ba9509b084b3a32661e6868`, also retaining the hot-loop capacity branch and grow path. These binaries predate or omit the current fast-cursor implementation and do not characterize current source code generation.
An earlier isolated source snapshot (`2e03e4a94c187dcd992910f4c7a59387425c7edc190ccc498180c96ba03cee18`) also failed before object generation; its historical log is `/private/tmp/elisa-stage1-snapshot-r30.log`.
