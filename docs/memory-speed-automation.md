# Automatic memory decisions for speed

Stage1 now applies three conservative optimizations to local `darray[i64]`
buffers. They are enabled by default and preserve the existing function ABI.
This is an initial subset, not general interprocedural ownership inference.

## Accepted programs

**Repeated scalar helpers.** Inside a loop, a scalar declaration initialized by a
unique, direct helper call can inline the helper into a caller-owned scratch
region. Existing loop-region lowering retains the region across iterations,
resets it after the scalar result is copied, and frees it at function exit.
The helper has at most four `i64` parameters and eight top-level statements,
one fresh empty buffer followed by a counted fill, read-only scalar work, and a
single final scalar return. Top-level and module-qualified calls are supported.
Original functions remain available to other callers; no hidden ABI parameters
are added. Helper-local name collisions with the caller conservatively disable
inlining. Full trace captures attribute the inlined body to the caller, while
allocation events retain the emitted source locations.

**Capacity inference.** A fresh empty buffer followed immediately by a loop
`0..<n` that pushes exactly once per iteration can reserve once. The upper bound
is an `i64` local/parameter or an integer literal. This also works inside helpers
and their inlined copies. Negative bounds are clamped to zero for the synthesized
reserve. All subsequent uses must pass the scalar, read-only lifetime proof.

**Bounded stack placement.** A proven nonescaping literal buffer, or a counted
fill with a constant bound, can use an entry-block stack allocation. The initial
limit is 256 `i64` elements (2 KiB), with at most one promoted buffer per LLVM
function. Larger or dynamic buffers retain arena storage and may receive a
reserve. Entry-block placement prevents stack growth on each loop iteration.
The buffer cannot grow beyond its proven capacity or escape the function.
This budget is per frame; it is not a whole-call-stack budget.

The proofs reject observed capacity or data pointers, aliases, escaping buffers,
unknown calls, writes through the buffer, further growth, explicit region
annotations, unsupported control flow, overload ambiguity, and generic helpers.
There is no early field reclamation or automatic trimming.

`ELISA_EXPLAIN_MEMORY=1` reports accepted decisions. For diagnostic comparisons,
`ELISA_DISABLE_MEMORY_SPEED=1` restores the old paths. Individual ablations use
`ELISA_DISABLE_MEMORY_HELPER=1`, `ELISA_DISABLE_MEMORY_RESERVE=1`, or
`ELISA_DISABLE_MEMORY_STACK=1`. These are compiler controls, not runtime policies.
They are read once per module, avoiding environment lookups in statement lowering.

## Measured results

`test/parity/benchmark_memory_automation.sh COMPILER OUT` builds ordinary `-O2`
executables using the same compiler, source and runtime, with only one optimization
enabled in each candidate. An opaque C consumer prevents removal of the measured
iterations. Outputs are checked against stage0's object-plus-link executable
before timing. elisa-profiler's paired native timer records CPU/wall samples,
randomizes pair order, excludes warmups, and verifies output hashes on every run.

On this macOS arm64 host:

| Isolated change | Baseline median CPU | Candidate median CPU | Reduction |
| --- | ---: | ---: | ---: |
| Helper scratch reuse, 31-pair confirmation | 249.812 ms | 229.305 ms | 8.2% |
| Reserve inference, 15 pairs | 233.358 ms | 208.486 ms | 10.7% |
| Small-buffer stack placement, 15 pairs | 83.957 ms | 15.679 ms | 81.3% |

The first 15-pair helper run showed a smaller 4.0% reduction in overall medians
(13/15 pairs faster). Its confirmation was faster in all 31 pairs. Reserve was
faster in all 15 pairs. A separate compiler process consumed one CPU core during
these measurements; these are workload-specific results under that background
load, not quiet-host measurements or claims about application-wide speedups.

`test/parity/profile_memory_automation.sh COMPILER OUT` independently captures
allocation behavior. All three repetitions per configuration completed with
exit 0, no allocation-event loss, and usable lifetime evidence:

- Helper fixture: 100 region creations/frees became one creation/free plus
  100 resets. The analyzer observed 99 reuses. Peak backing stayed at 1 MiB.
- Reserve fixture: 10 in-place reallocations became zero. Peak logical live
  bytes fell from 65,536 to 32,776; peak backing remained 1 MiB.
- Stack fixture: 10,001 allocations became one, retaining the fixture's separate
  surviving array. Empty automatic-arena cleanup calls still exist; the change
  removes the temporary allocations, not every cleanup call.

The [measurement record](measurements/memory-speed-20260914.json) includes raw
paired samples, hashes and per-repetition allocation summaries. Full captures
remain under `build/memory-speed-20260914/profiles/`. Trace timings are not used
as speed evidence, and backing-capacity measurements are not RSS measurements.

## Validation

`test/parity/memory_speed_smoke.sh` checks nine cases at runtime against stage0:
helper reuse, capacity inference, stack placement, aliases/escapes/observed
capacity, one-buffer stack budgeting, the 2 KiB boundary, helper fallbacks, and
module-qualified helpers with caller break/continue, and generic/non-generic
name collisions. The collision regression failed in the initial implementation
and now remains on the ordinary call path. IR assertions check both
accepted optimizations and fallbacks, plus the global ablation control.

The negative-count fixture explicitly returns before filling. An unguarded
negative counted fill exposed a pre-existing difference: stage0's inferred
reserve traps, while the prior stage1 executes an empty loop. This change does
not claim to resolve that separate language-parity issue.

The optimized compiler and its self-hosted rebuild both passed the nine-case
suite. The self-hosted product also passed the fifteen existing loop/region
runtime fixtures and their proof/fallback checks. Parser lifetime/capacity and
returned-token lifetime suites passed during integration. The final compiler's
benchmark objects and runtime are byte-identical to the measured versions after
the additional declaration-identity guard. All 329 token fixtures were byte-identical to stage0. No full
differential-corpus or bootstrap-fixpoint result is claimed.
