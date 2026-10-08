# Diagnostic traversal checkpoints

These isolated source changes reduce repeated candidate traversal without changing
primitive eligibility, overload rules, or diagnostic ordering. They are qualified as isolated Core3a native differential oracles. They are not a
qualified Stage1 product and establish no measured performance gain.

Base source: `2694b1dc6163d657b8653d88085aaee5cb760506`.

The IEEE parameter helper replaces a full symbol scan with the existing f32/f64
name-hash chains. All source symbol insertions maintain those chains; source names
and lines are not later rewritten. Actual-name checks ignore hash collisions.
The existing conservative unit-wide primitive shadowing policy is retained,
including source declarations in other modules and aliases. The test oracle
retains the previous full scan and checks direct floats, aliases, qualified types,
non-plain bodies, and a manufactured hash-chain collision.

Per-scope duplicate checks build name-hash chains in declaration order. Only prior
rows are visited, and both namespace comparison paths still compare actual names.
Signature, alias, builtin-carrier, and protocol rules are unchanged. The test oracle
retains the previous full scan and compares all Diagnostic fields, all six Pos
fields, array order, and duplicate counts for twenty source cases.

## Source admission evidence

Private Vast experiment root: `/root/work/codex-diagnostic-pass-traversals`.
Both baseline and candidate use the same coherent eighteen runtime source files,
recorded in `results/common-runtime-source.json`, and the same operation-grant
migration patch SHA256
`4f5e4b8166bbf6378b566c53ae90da0a2bae259174d17d7f21ecf93312a8cfe7`.
That migration is external to this optimization checkpoint; its commits are
`fa54f4820881cd4de997083c538aab276031cf84` and
`e431fc0598158ee7eb5c16101b6fdf8d7b3d2998` on compiler71d.

Source-admission producer: private `core-source-admission-3a`, SHA256
`96e1e079d306828170e3ea35479d9c234cb2c5526e9eb5ae6f10a4233215baed`.
Command from candidate, substituting each probe path:

```
ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1 GOMAXPROCS=2 \
  ../core-source-admission-3a -emit semantic test/repro/PROBE.elisa
```

Both `ieee-core3a-fullgrant-v5.status` and
`duplicate-core3a-fullgrant-v5.status` recorded exit0. Their `.stdout` and `.stderr`
files preserve full results. These checks used equivalent dotted Global.Read and
Global.Write probe grants; the checkpoint spells them as grouped
Global{Read,Write}. Both exact grouped-spelling probes also admitted successfully in the
`*-core3a-checkpoint-v6` source checks.

Earlier parse and old-runtime/grant failures remain in results; no permissive
checker, signature authority, or trusted declaration was used to bypass them.
The retained cold-Pos native compiler211b/runtime d076 pair is pinned separately,
but the old compiler's grouped-grant checker blocks these newer source fixtures.
No Stage1 product, parallel eligibility, or timing gain is claimed here.


## Native differential qualification

`results/native-oracles-v8.final.json` records eight successful compile/link/run
controls: both probes, both baseline/candidate sources, both O0/O2. All eight
executables also passed with `ELISA_SEMANTIC_SERIAL=1`. The source-before/after
manifests matched exactly; the final JSON records each object/executable SHA and
observed compiler RSS. Maximum observed RSS was 5,823,156 KiB, below the 12 GiB cap.

The test-only manufactured AST has an explicit local Ast::Node.Store, and scoped
helpers use explicit returns inside their local can blocks. Neither correction
changes production behavior or relaxes ownership/grant checks. Earlier rejected
operator spelling, missing store scope, implicit scoped return, and link failures
remain recorded rather than overwritten.

Core3a explicitly produced both programs and a fresh coherent runtime object:
`runtime-core3a-coherent.o`, SHA256
`2c52be1c76a0b53922f4f423b91627f85e90de1851d37f372c6dc947a306e90b`.
Runtime source before/after manifests are `results/runtime-core3a-source.*.json`;
raw/composite product hashes and external symbol list are in
`results/runtime-core3a-coherent.products.sha256` and `.defined-symbols`.
Build recipe: `codex-diagnostic-core3a-runtime.sh` in the private root, one LLVM
worker (`ELISACORE_CODEGEN_JOBS=1`, parallel opt disabled), GOMAXPROCS2, explicit
Linux/x86-64 target, O2 plus forced contracts, standard atomic host lock, 12 GiB
RSS/600-second guard. Native_runtime_support exports remain external; no
runtime-identity environment exemption was used. Host/profile fallbacks came from
`write_profiler_hook_fallbacks.sh --host-callbacks`, compiled with `-fno-builtin`.

The AST geometry probe passed O0 and O2 with 400 nodes across chunk boundaries,
96-byte PackedAoSStore, 24-byte Pos, 4-byte Expr, every Pos field and child payload.
Its source provides its runtime, so the canonical link uses only the weak hook
object. A separate packed-enum geometry probe without a source runtime links the
complete fresh runtime object and also passed both levels. Strict clang21 links
use `-no-pie`, `--no-undefined`, LLVM21 plus libm/pthread/dl, and a 512 MiB stack.
No duplicate-definition or unresolved-symbol suppression was used.

This route is a native oracle qualification, not a self-hosted Stage1 compiler
qualification or installation. Matched scaling below qualifies the targeted traversal changes; full Stage1 qualification remains pending.


## Matched traversal scaling

`test/repro/diagnostic_pass_scaling_probe.elisa` constructs 256, 1024, or 4096
unique float-parameter functions in an explicit local AST store. Construction and
builtin seeding precede the measured phases. `collect_range` exercises the unique
scope duplicate path; each of the three comparison passes exercises primitive
shadowing lookup. The workload emits every diagnostic text byte with a length
prefix, including embedded NUL, then every scalar and all six Pos fields.

Both source trees received the identical coherent runtime and operation-grant
overlays recorded above. Core3a admitted the fixture (v3 exit0); inherited
nonfatal Unsafe warnings remain in its stderr. All four native O0/O2 products
compiled, linked, and ran successfully with one LLVM worker and the 12 GiB guard.
Observed compiler RSS peaks were 5345996/5594840 KiB for baseline/candidate O0,
and 5150100/5525800 KiB for O2.

All twelve scaling executions passed. At every count and optimization level,
baseline and candidate diagnostic streams were byte-identical. The harness also
required exactly N+86 symbols, zero duplicates, and 2N diagnostics, and decoded
every record to the stream end. Thus equality cannot pass on empty ASTs or empty
checker output. All source digests remained unchanged through these controls.

Exploratory **process CPU milliseconds**, one sample per product/count on the
shared box:

| Optimization | Functions | Product | collect_range | self_comparison | float_equality | negated_comparison |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| O0 | 256 | baseline | 1.1 | 2.2 | 1.9 | 1.7 |
| O0 | 256 | candidate | 0.7 | 0.4 | 0.5 | 0.3 |
| O0 | 1024 | baseline | 11.7 | 20.6 | 21.1 | 20.1 |
| O0 | 1024 | candidate | 2.6 | 1.7 | 2.2 | 1.3 |
| O0 | 4096 | baseline | 142.7 | 256.4 | 253.1 | 247.6 |
| O0 | 4096 | candidate | 10.9 | 7.4 | 8.9 | 5.2 |
| O2 | 256 | baseline | 0.6 | 0.4 | 0.5 | 0.3 |
| O2 | 256 | candidate | 0.3 | 0.2 | 0.3 | 0.1 |
| O2 | 1024 | baseline | 7.5 | 3.2 | 3.5 | 2.9 |
| O2 | 1024 | candidate | 1.4 | 1.0 | 1.3 | 0.6 |
| O2 | 4096 | baseline | 88.7 | 69.5 | 70.6 | 68.0 |
| O2 | 4096 | candidate | 5.9 | 4.4 | 5.3 | 2.5 |

At 4096 functions, total process user+system CPU was 0.99/0.12 seconds at O0
and 0.38/0.10 seconds at O2 (baseline/candidate); GNU time's 0.01-second
resolution limits small-count totals. Runtime maximum RSS was 140752/141348 KiB
at O0 and 137660/138576 KiB at O2. The measured traversal scaling supports the
quadratic-work diagnosis and its removal. It does not establish quiet wall-time
improvement or end-to-end self-hosted Stage1/compiler-vs-Zig performance.

Private reproducibility records under `/root/work/codex-diagnostic-pass-traversals`:

- `codex-diagnostic-core3a-scaling.sh`, `codex-diagnostic-scaling-controller.sh`,
  and `diagnostic_scaling_measure.py` contain exact commands and validation.
- `results/scaling-core3a-source-v3.*` retain source admission.
- `results/scaling-native-v1.controller.log` and per-product compile/link/run
  statuses retain terminal outcomes and guard peaks.
- `results/scaling-source-v1.{before,after}.json` are equal source manifests;
  `results/scaling-native-v1.products.json` records all eight object/executable
  hashes, and `results/scaling-fixture-v1.sha256` records the identical fixture.
- `results/scaling-measure-v1/results.json`, `status`, binary streams, phase
  stderr, and GNU time resource files retain all twelve execution controls.

No source was integrated into main or installed by this lane.
