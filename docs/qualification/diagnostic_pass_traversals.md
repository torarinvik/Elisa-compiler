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
qualification or installation. Matched 256/1024/4096 scaling remains pending.
