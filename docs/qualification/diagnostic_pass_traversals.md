# Diagnostic traversal checkpoints

These isolated source changes reduce repeated candidate traversal without changing
primitive eligibility, overload rules, or diagnostic ordering. They are not a
qualified native product and establish no measured performance gain.

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
Global{Read,Write}. Final exact-checkpoint source and O0/O2 native oracle checks
remain pending.

Earlier parse and old-runtime/grant failures remain in results; no permissive
checker, signature authority, or trusted declaration was used to bypass them.
The retained cold-Pos native compiler211b/runtime d076 pair is pinned separately,
but the old compiler's grouped-grant checker blocks these newer source fixtures.
No native runtime success, parallel eligibility, or timing gain is claimed here.
