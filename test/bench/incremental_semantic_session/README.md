# Retained semantic-session graph benchmark

This runner compares the experimental semantic query graph inside one long-lived
`semantic-session` host. It is separate from
[`../incremental_fact_lookup/README.md`](../incremental_fact_lookup/README.md),
which measures disk-sidecar reuse with fresh compiler processes.

The graph remains opt-in and is not qualified for production use by this
benchmark alone. The runner measures function-body fact reuse and resolver
NameLookup hits separately. Its call-heavy workload checks that resolver hits
occur, but the inactive fast path currently leaves the graph-off chain-visit
baseline at zero; no avoided-chain-work conclusion is valid until that baseline
is restored. The semantic checker still walks function bodies, so production
use requires a fresh source-matched paired run with repeatable end-to-end gains.

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

Each pair runs two workloads. `zero-fact` uses literal-return function bodies,
which exercise body reuse while serializing empty direct-fact payloads.
`call-facts` uses zero-argument direct calls in the function bodies, so restored
bodies carry direct-call facts as well as their body records. The edited body
switches between two leaf functions. Results and source hashes are grouped by
workload so the empty-payload control cannot hide the cost of copying actual
facts.

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

Results from a shared Mac are exploratory. Graph-on/off counters show which
path ran; they do not prove the graph is faster. The query layer still performs
key construction, hashing, equality, dependency validation, and retained-memory
management, and the semantic checker still runs. Keep `COMPLETE` and the pinned
input hashes with results; `ABORTED.txt` marks incomplete runs whose partial
timings must not be compared.
