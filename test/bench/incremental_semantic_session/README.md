# Retained semantic-session graph benchmark

This runner compares the experimental semantic query graph inside one long-lived
`semantic-session` host. It is separate from
[`../incremental_fact_lookup/README.md`](../incremental_fact_lookup/README.md),
which measures disk-sidecar reuse with fresh compiler processes.

The graph remains opt-in and is not qualified for production use by this
benchmark alone. The runner measures function-body fact reuse and resolver
NameLookup hits separately. Each `call-facts` body calls a distinct leaf, with
an alternate leaf for the edited body. A call's callee is still classified
twice within one request, so the runner compares warm hit totals with the
same-request duplicate baseline. Ordinary `call-facts` warm totals must exceed
the prime baseline. For the post-surface edit, which turns one caller into a
literal, the runner requires more than `N-1` hits for `call-facts` and more than
`2N-3` for `shared-calls`; remaining duplicate reads alone can produce those
baseline counts. Other pre-transition `shared-calls` warm requests must exceed
their duplicate-only baseline: `2N-2` with both callees or `2N-1` when all N
callers use the shared callee. The graph-off and graph-on modes report the chain
rows visited by the NameLookup classification probe. The runner requires cold
graph-on visits at prime and fewer graph-on visits than graph-off on exact-repeat,
body-edit, declaration-surface, and post-surface requests. Those reductions can still
include same-request duplicate checks. The counter covers only global symbol and
module-member hash-chain rows visited by the fused classifier. An active graph
request builds its exact resolver surface lazily when it reaches its first
unbound name; requests with no eligible NameLookup reads skip that build. The
first eligible read still pays the full surface scan, and every query scans lexical
bindings before checking the cache. Each active read also probes the per-name resolver
surface and the `(current_module, name)` member-pair index, including warm cache hits;
those probes are not represented in the chain counter. The cold fallback scans
`region_names`, while active queries read the precomputed region bit. Surface
construction, per-read surface probes, and local scans are outside the chain counter,
though surface construction and probes are included in graph-on whole-request timing.
This fixture
has no local or region names, so it does not measure those costs. Bare module
identifiers used as `Expr.Field` or namespace-call objects now also use
NameLookup; qualified `Expr.Scope` module-prefix and member
probes still resolve directly through `name_is_module`, `ancestor_names_module`,
`two_part_names_module`, and `module_declares_member`. Those probes are outside both
the cache and this counter. This fixture uses only bare same-module callees and
contains no module-field or qualified-path expressions, so it does not measure
those paths.
Other direct `name_known` checks also remain outside `classification_chain_visits`,
including `Expr.RegionNew`, value-block captures, and flow checks. Treat the metric
as fused NameLookup-classifier rows only, not total resolver name-chain work.
The semantic checker still walks function bodies, so these routing checks do not
establish a compiler speedup. Production use requires a fresh source-matched paired
run with repeatable end-to-end gains.

The cache report also records reverse-closure fast skips, full walks, visited
nodes, and visited edges. Routing checks require no closure work on exact-repeat
and a full walk followed by at least one repeated-mark skip on
`declaration-surface-edit`. These counters validate that the shortcut is being
exercised; they are not a speed result. Timed arms disable counter increments,
but graph traversal still checks the runtime metrics flag per visited node and
edge, so graph-on/off timings include that small asymmetric branch overhead.

Run on macOS after the source-matched Stage1 product is available:

```sh
python3 test/bench/incremental_semantic_session/paired.py \
  --stage1 "$PWD/bin/elisac-stage1" \
  --output /absolute/path/to/empty/results \
  --pairs 5 --functions 128 --body-edits 3
```

The default run compares two routing modes:

- `graph-off` disables the semantic query graph.
- `graph-on` enables the graph, including cached `NameLookup` queries.

Add `--include-direct-surface` to include a third routing mode and an additional
workload:

```sh
python3 test/bench/incremental_semantic_session/paired.py \
  --stage1 "$PWD/bin/elisac-stage1" \
  --output /absolute/path/to/empty/results \
  --pairs 5 --functions 128 --body-edits 3 --include-direct-surface
```

`direct-surface` keeps the query graph enabled for body-fact reuse, but bypasses
the per-name `NameLookup` graph evaluate/commit when the resolver has a valid,
finalized name surface. It computes the same `(known, module_only)` classification
from that surface. If the context is inactive or the surface is invalid, the
resolver uses its cold classifier. The runner records explicit environment
switches for all three modes so an inherited setting cannot select a different
route.

With `--include-direct-surface`, each workload first runs three routing arms
with cache reports, then three counter-disabled timing arms in a rotated order.
Before timing is summarized, the runner checks graph-on against direct-surface
for equal request counts, statuses, diagnostic transcripts, and body-cache
fields. It also checks that graph-on did not use direct classification, that
direct-surface did not hit the `NameLookup` graph, and that call workloads
recorded direct-surface classifications. Each timing arm must match the
corresponding routing arm's environment, status, and diagnostics. The report
keeps the routing evidence separate from timing summaries.

The extra `shared-calls` workload gives many bodies the same callee spelling,
then changes one caller to an alternate callee. This complements `call-facts`,
which gives each body a distinct callee, and exposes repeated-name query costs.
`zero-fact` remains the literal-return control and does not exercise eligible
`NameLookup` reads. Direct-surface versus graph-on therefore measures the cost
of the NameLookup route on these generated sources, not the cost of all semantic
queries or a whole-compiler speedup.

The direct-surface parity check covers the generated `zero-fact`, `call-facts`,
and `shared-calls` sequences. Those fixtures contain no imports or import
annotations, no local or region names, and no qualified `Expr.Scope` paths.
They do not establish parity for import visibility, region-name classification,
absent names, or the full range of module/member collisions. The separate
`test/parity/incremental_semantic_session_control.sh` exercises negative-name
invalidation on the ordinary graph route; it does not select `direct-surface`.
Use targeted parity cases before broadening the experiment or making claims about
those resolver inputs.

A useful next workload is a local-binding sweep: give each call body 0, 32, or
128 unused scalar parameters while keeping its queried global callee unshadowed.
`resolver_name_classification` checks every active `bound` name before it reaches
NameLookup, so this reveals whether the cached global classification still pays
off after that linear prefix. Include a separate parameter-shadowing control in
which a local name matches a global identifier and must bypass NameLookup. If
adding a binding-comparison counter, keep it in routing arms and leave timed arms
counter-disabled. This coverage is proposed; the current generated workloads do
not measure local-scope scan cost.

By default, the runner checks exact Stage1 provenance before and after the run,
holds the shared compiler-benchmark lock, and uses the same load gate as the
other paired benchmarks. Pass `--concurrent-instruction-counts` to skip that
lock and load gate when several compiler agents need to measure at once. That
mode still compares exact Stage1 process instruction counts and runs the same
status/diagnostic checks; its host qualification stays false, and wall-time and
cycle measurements are exploratory because concurrent work affects them. Each
invocation needs its own empty `--output` directory. The runner alternates
graph-off/graph-on order across pairs by default; with the direct-surface option,
it rotates the three routing modes across pairs. Each mode starts a fresh
persistent semantic host and uses the same absolute source path within a
workload; each workload uses a separate path. The sequence includes a
prime request, an exact-source repeat, several one-body edits with unchanged
declarations, a declaration-surface edit, and a body-only edit after that
surface has been published.
The runner clears `ELISA_SEMANTIC_SERIAL` so all modes use the default parallel
semantic pass mode regardless of the invoking shell environment.

The default run includes two workloads. With `--include-direct-surface`, it also
runs `shared-calls`. `zero-fact` uses literal-return function bodies,
which exercise body reuse while serializing empty direct-fact payloads.
`call-facts` uses zero-argument direct calls in the function bodies, so restored
bodies carry direct-call facts as well as their body records. The edited body
calls a distinct leaf per function; the edited body switches to a separate
alternate leaf. Before the post-surface transition, the report exposes
`direct_fact_count` and the runner asserts one direct-call fact per `bench_*`
body in `call-facts`; the post-surface transition removes one. `zero-fact`
expects no direct facts. Results and source hashes are grouped by workload so
the empty-payload control cannot hide the cost of copying actual facts.

The runner also checks the closed complete-empty query class: exactly one
`return` of an integer, float, string, character, or boolean literal. Those
`FunctionBodyFacts` nodes have an empty dependency set because this AST shape
cannot read declarations. On the declaration-surface edit, graph-on must restore
the unchanged members of this class and skip their duplicate publication even
though `SourceInput` changed; graph-off must report no restores or skips. The
separate `complete_empty_body_*` counters describe only direct-fact query work;
the compiler still parses the source and runs its full semantic pipeline.

The `post-surface-body-edit` control retains the added declaration and changes
only `bench_0000`, after first confirming that its prior body is a direct call.
For the call workloads, that edit changes its body to a literal, so the report
must show one fewer direct fact and one new complete-empty query commit. These
body-query assertions check reuse after publishing a new declaration surface:
for `call-facts` and `shared-calls`, graph-off must use typed-snapshot fallback
while graph-on admits the now-current `SourceInput`. The separate NameLookup
assertion requires post-surface hit counts above the same-request duplicate
baselines described above. The all-complete-empty
`zero-fact` workload expects neither admission nor typed-snapshot fallback; its
closed body shape proves the empty fact result directly. Every workload must
restore and skip publication for each unchanged eligible body. The changed body
remains cold, while unchanged complete-empty bodies are restored. This request
is reported as its own control and is not folded into the pre-surface body-edit
aggregate.

These NameLookup thresholds prove that a warm request gets at least one hit
from an earlier request after subtracting hits from duplicate spellings within
the same request. They do not prove reuse for every unchanged spelling; the
counters are aggregate rather than per-key.

For `call-facts` and `shared-calls` body edits, graph-off must report
typed-snapshot fallback reuse and graph-on must report collector-side
`source_input_admitted`. For `zero-fact`, both paths skip these broad body-fact
reuse paths because every body is complete-empty. That report field covers
collector/body-fact admission only: graph publication has a separate
`SourceInput` phase when it has cacheable nonempty bodies, and the graph-on
driver refreshes the resolver `SourceInput` context before semantic resolution.
Neither phase is represented by `source_input_admitted`. Graph-on must still
restore every unchanged eligible body in all workloads. The declaration-surface
control must invalidate `SourceInput`-dependent body-fact reuse while the
separately counted complete-empty queries remain reusable.
The runner compares the complete per-request compiler transcript after removing
only cache/timing instrumentation, so status and diagnostics must match between
modes. Prime, exact-repeat, body-edit, and invalidation timings remain separate
in `paired.json`, with timing summaries grouped by workload. Body edits remain
the primary paired timing summary; prime, exact-repeat, declaration-surface,
and post-surface body-edit controls also receive separate paired ratios,
geometric means, and win counts. Control ratios are descriptive and are not
folded into the body-edit aggregate.
The primary performance measure is the exact Stage1 process's retired
instructions, sampled with macOS `proc_pid_rusage` immediately around each
request. Cycles, per-request phase wall/CPU times, request wall times, and outer
process wall times are recorded as supporting measurements. The runner finds
the Stage1 child of the guarded launcher and fails if it cannot identify that
process, so shell-launcher work is excluded from compiler instruction counts.
These are Stage1-process counters, not process-tree totals: child tools such as
Z3 are excluded. If a workload invokes a solver, report its cost separately or
aggregate child-process counters before making a total-work claim.
Each counter sample also records physical footprint and lifetime peak physical
footprint in bytes. Requests retain both snapshots and a signed footprint change;
these gauges are separate from cumulative instruction/CPU counters. Physical
footprint is not RSS, and the lifetime peak covers the entire process rather than
an individual request. These observations expose retained-memory growth but do
not establish a memory bound or attribute allocations to a compiler phase.
The normal host load gate still applies to keep cache and scheduling conditions
comparable; instruction counts are the primary comparison because they are less
sensitive to scheduling delay than wall time.

Each workload/pair runs graph-off and graph-on routing arms with
`ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1` and two separate timing arms with
that setting explicitly `0`. When `--include-direct-surface` is enabled, each
set also runs a direct-surface arm. Routing arms enforce reuse, invalidation,
and NameLookup-counter assertions. Timing arms require no cache report, preserve
status/diagnostic parity with the corresponding routing arm, and retain phase
timing. Only timing arms enter performance summaries; routing evidence is stored
separately in `routing_arms` in `paired.json`. The default two-mode runner
counterbalances routing-first and timing-first pairs and alternates graph-on/off
order within each kind. The three-mode runner runs all routing arms before all
timing arms and rotates the mode order across pairs.

Earlier results that enabled chain counting inside timed arms include asymmetric
telemetry overhead: graph-off traverses and counts more rows. Do not combine
those results with the separate counter-disabled timing results. The updated
runner still requires a fresh source-matched Stage1 execution before it can
establish performance; protocol checks against a fake host are harness validation
only.

Warm exact-repeat timings are kept separate because SourceInput admission
currently copies the declaration surface for validation. Compare separate
`--functions` runs to inspect how that warm cost scales with surface size.
The current call-facts fixture uses positive same-module names only. The separate
`test/parity/incremental_semantic_session_control.sh` now checks a missing name,
declaration addition, removal, and exact-repeat negative lookup. That control still
needs a fresh source-matched Stage1 run before NameLookup invalidation is
correctness-qualified. This sequence is invalidation/reuse correctness coverage,
not avoided-chain-work evidence: a fresh missing name exits at the O(1)
`name_indexed` gate before symbol or member chains are walked.

Results from a shared Mac are exploratory. Graph-on/off counters show which
path ran; they do not prove the graph is faster. The query layer still performs
key construction, hashing, equality, dependency validation, and retained-memory
management, and the semantic checker still runs. The previous NameLookup key
copied the full session identity and source path for every spelling, creating
O(unique names × identity/path bytes) retained key data. The current source
replaces that with a versioned `(module, name)` key; relevant declaration,
visibility, and region changes are represented by the exact resolver-surface
query input, and identity/options changes clear the session-local graph. Cold
misses reuse the encoded request-local key and input for commit after cold
classification. This key compaction and scratch reuse have not been build- or
performance-qualified.
Keep `COMPLETE` and the pinned
input hashes with results; `ABORTED.txt` marks incomplete runs whose partial
timings must not be compared.
