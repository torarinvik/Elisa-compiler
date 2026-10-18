# Retained semantic-session graph benchmark

This runner compares the experimental semantic query graph inside one long-lived
`semantic-session` host. It is separate from
[`../incremental_fact_lookup/README.md`](../incremental_fact_lookup/README.md),
which measures disk-sidecar reuse with fresh compiler processes.

The graph remains opt-in and is not qualified for production use by this
benchmark alone. The runner measures function-body fact reuse and resolver
NameLookup hits separately. Each `call-facts` body calls a distinct leaf, with
an alternate leaf for the edited body. A call's callee is still classified
twice within one request, so the runner compares warm hit totals with the prime
same-request baseline; warm totals must exceed that baseline to show aggregate
prior-request reuse. Both graph modes report the chain rows visited by the
NameLookup classification probe. The runner requires cold graph-on visits at
prime and fewer graph-on visits than
graph-off on exact-repeat and body-edit requests. Those reductions can still
include same-request duplicate checks. The counter covers only global symbol and
module-member hash-chain rows visited by the fused classifier. An active graph
request builds its exact resolver surface lazily when it reaches its first
unbound name; requests with no eligible NameLookup reads skip that build. The
first eligible read still pays the full surface scan, and every query scans lexical
bindings before checking the cache. The cold fallback scans `region_names`, while
active queries read the precomputed region bit. Surface construction and local
scans are outside the chain counter, though surface construction is included in
graph-on whole-request timing. This fixture
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

Run on macOS after the source-matched Stage1 product is available:

```sh
python3 test/bench/incremental_semantic_session/paired.py \
  --stage1 "$PWD/bin/elisac-stage1" \
  --output /absolute/path/to/empty/results \
  --pairs 5 --functions 128 --body-edits 3
```

The runner checks exact Stage1 provenance before and after the run, holds the shared compiler-benchmark lock,
and uses the same load gate as the other paired benchmarks. It alternates
graph-off/graph-on order across pairs. Each mode starts a fresh persistent
semantic host and uses the same absolute source path within a workload; each
workload uses a separate path. The sequence includes a
prime request, an exact-source repeat, several one-body edits with unchanged
declarations, and a declaration-surface edit.
The runner clears `ELISA_SEMANTIC_SERIAL` so both arms use the default parallel
semantic pass mode regardless of the invoking shell environment.

Each pair runs two workloads. `zero-fact` uses literal-return function bodies,
which exercise body reuse while serializing empty direct-fact payloads.
`call-facts` uses zero-argument direct calls in the function bodies, so restored
bodies carry direct-call facts as well as their body records. The edited body
calls a distinct leaf per function; the edited body switches to a separate
alternate leaf. The report exposes `direct_fact_count`, and the runner asserts
one direct-call fact per `bench_*` body in `call-facts` and zero in `zero-fact`.
Results and source hashes are grouped by workload so the empty-payload control
cannot hide the cost of copying actual facts.

For every body edit, graph-off must report typed-snapshot fallback reuse and
graph-on must report SourceInput admission plus restoration of every unchanged
cacheable body. The declaration-surface control must invalidate that reuse.
The runner compares the complete per-request compiler transcript after removing
only cache/timing instrumentation, so status and diagnostics must match between
modes. Prime, exact-repeat, body-edit, and invalidation timings remain separate
in `paired.json`, with timing summaries grouped by workload; only body edits
enter the paired timing ratios. Per-request
phase wall/CPU times and outer process wall times are recorded. Retired
instructions and cycles are marked unavailable because the guarded shell
launcher owns the timed PID while Stage1 runs as its child; launcher counters
would not represent compiler work.

Each workload/pair now runs two routing arms first, with
`ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1`, then two separate timing arms with
that setting explicitly `0`. Routing arms enforce all reuse, invalidation, and
NameLookup-counter assertions. Timing arms require no cache report, preserve
status/diagnostic parity between graph modes and against the corresponding
routing arm, and retain phase timing. Only timing arms enter performance
summaries; routing evidence is stored separately in `routing_arms` in
`paired.json`. Each kind alternates graph-on/off order across pairs. This doubles
the number of host launches relative to the previous instrumented runner.

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
