# Loop scratch allocation: first measured increment

Stage0 already tightens some iteration-local allocations into lazy regions and
resets lazy loop regions between iterations. Stage1 now implements lazy loop
region reuse and a conservative subset of automatic scratch inference.

The inferred subset starts with one fresh, unpinned `darray` of primitive scalar
values. Its remaining statements may push/reserve that array, read scalar elements
or metadata, update existing scalar locals, branch, break, or continue. Unknown
unproved calls, aliases, slices, outer-container growth, extra declarations, and
unrecognized syntax retain the existing allocation behavior. This is a local
proof, not a general interprocedural escape analysis.

A retained arena carrier is initialized once in the function entry. Scope exits
reset it after user defers; function exits release it. Tests cover normal exit,
break, continue, early return, skipped loops, nested regions, void fallthrough,
and loops inside deferred bodies. Explicit-capacity regions retain their existing
allocation policy. Reset retains capacity; this change does not add adaptive
trimming or promise to return pages to the OS each iteration.

Profiling also exposed a scalar-trace ABI declaration with its arguments in the
wrong order. The declaration now matches the emitter and elisa-profiler collector.
The profiler's existing lifecycle records and OS peak RSS suffice for this
measurement; no live-byte or leak inference is made from raw event sizes.

Self-host validation additionally exposed an existing region-checker false positive:
a known container's count/capacity metadata is a scalar copy, not a borrow of its
backing. Metadata type resolution now recognizes these fields on known containers,
while user-defined fields with the same spelling retain ordinary lifetime checks.

## Reproduction

```
bash test/parity/loop_region_reuse_smoke.sh
bash test/parity/profile_loop_regions.sh BEFORE_BINARY AFTER_BINARY OUTPUT_DIRECTORY
```

Set `ELISA_STAGE1_BIN` for the runtime smoke and `ELISA_PROFILER` if the profiler
is not in the sibling `elisa-profiler` checkout. The comparison uses one runtime
object, identical source for each pair, target optimization `-O2`, one warmup,
and five measured repetitions. It rejects event loss and unsuccessful target runs.
`summary.json` records event counts and medians. Source/compiler/runtime identities
and host provenance remain in the native profiler captures.

The baseline is compiler commit `9791a8e1` with only the trace ABI repair, so that
both versions can be profiled. These synthetic fixtures allocate 200 temporary
4096-element i64 arrays; they demonstrate allocation policy, not an application-wide
speedup. Region-create events are runtime lifecycle operations, not an mmap census:
the allocator can satisfy them from its cache. Allocation request counts stay at
200 in both versions.

## Measurement on 2026-09-14 (Apple arm64 host)

| Fixture | Before | After |
| --- | ---: | ---: |
| Explicit region: create events per run | 200 | 1 |
| Explicit region: reset events per run | 0 | 200 |
| Inferred region: create events per run | 7 | 1 |
| Inferred region: reset events per run | 0 | 200 |
| Inferred region: median peak RSS | 8,323,072 bytes | 1,769,472 bytes |

The inferred fixture uses about 79% less peak RSS. All five measured repetitions
per configuration completed with exit 0 and no capture/event loss.

Full instrumentation adds reset records: the inferred fixture's median CPU time
increased from 5.699 to 8.363 ms. Treat that as instrumented execution cost, not as
a production slowdown. An uninstrumented control calls the same 200-iteration
batch 200 times. Across seven alternating before/after repetitions after warmup,
median CPU time was 15.017 ms before and 4.212 ms after; median wall time was
22.330 and 7.593 ms. Background compiler activity was present on the host, so these
short timing samples are indicative, not a stable performance ratchet. The memory
and event-count result is the stronger evidence. The final compiler emits a
byte-identical object for the timing workload to the measured candidate.

Reproduce the control with:

```
bash test/parity/time_loop_regions.sh BEFORE_BINARY AFTER_BINARY OUTPUT_DIRECTORY
```

Local raw captures and summary: `build/loop-memory-20260914/`. These ignored build
artifacts preserve profiler provenance and loss accounting. The runtime smoke
checks scalar inference, early exits/deferred reads, proved borrowed calls, fallback on mutation/overloads
and outer growth, metadata copy-out, and trace compilation. A negative user-defined
`count` field test preserves stage1's baseline rejection; stage0 currently accepts
that separate unsafe escape, so it is not used as a negative oracle there.


## Initial loop-reuse validation

- The focused runtime smoke passes against stage0 and the candidate stage1.
- Fifteen targeted differential corpus workers report MATCH, with zero mismatches
  and zero declines (loops, regions, drops, protocol dispatch, and the original
  module-nested UFCS cases).
- Profiler runs have zero dropped events; their target results remain exit 0.
- The normal optimized stage0-seeded build and runtime build succeed. The installed
  `bin/elisac-stage1` passes the runtime smoke and emits byte-identical objects to
  the profiled candidate for both traced and uninstrumented benchmark inputs.
- At the initial loop-reuse revision, self-hosting was blocked by `easm_verify_file`, `easm_emit_export`, and
  `easm_join_into`. After the metadata correction, those were the only reported
  backend declines. The baseline compiler produces the same three declines when
  its earlier metadata false positive is bypassed for diagnosis only. No gate was
  disabled for candidate validation and no ratchet was changed.

The whole differential corpus and bootstrap fixpoint are not claimed as passing.
Diagnostic logs are saved with the local profile artifacts.

## Direct-call lifetime summaries

Stage1 now records a conservative, reusable function fact before emitting bodies:
`FnTable.scratch_readonly` means a direct helper reads its borrowed scalar array
without retaining it and returns a scalar. Facts start unknown and propagate to a
fixed point, so forward references and chains of proven helpers work. Recursive
cycles remain unknown.

The initial proof accepts a uniquely named global function with one borrowed
scalar-darray parameter and one return statement. Its return expression may use
scalar literals, element reads, count/capacity, scalar operators, and other proven
helpers. Unknown expressions, globals, mutations, multi-statement bodies, decorated
functions, externs, error returns, and overload ambiguity prevent a proof. Generic
instantiations appended after the analysis have no summary. Calls must be direct,
unlabelled, and pass the loop-local array; local callee shadowing prevents inference.

The loop emitter uses this fact to admit calls such as `first(&xs)` in scalar
expressions while keeping the existing reset/free and exit cleanup rules. This is
an initial interprocedural subset, not general escape analysis: helpers with local
reduction loops and functions returning borrowed views still retain the original
allocation behavior. Missing proof never means permission to reclaim memory.

The smoke gate checks runtime parity with stage0, requires scratch lowering for
simple and transitive helper calls, and requires fallback for mutation, overloads,
and outer-container growth. `test/bench/loop_region_helpers.elisa` and the extended
`test/parity/profile_loop_regions.sh` measure the new case with elisa-profiler.

Measured helper-call workload (five full-trace repetitions, one warmup; same source
and pinned runtime): median peak RSS 8,323,072 → 1,769,472 bytes (about 79% lower).
Each run still performs 200 allocation requests. Backing creation events fall from
7 to 1, and reset events rise from 0 to 200. All runs return zero with complete
captures and zero dropped events. The candidate also frees its unused ambient
carrier, so free-call counts are not counts of physical backing allocations.

Full-trace CPU rises from 5.915 to 8.849 ms because the reset events add observer
work. The uninstrumented helper control (200 batches, seven alternating samples
after warmup) instead measures median CPU 14.171 → 3.823 ms and wall time
20.780 → 9.586 ms. Other builds were active: these timings are indicative, not a
performance ratchet. Raw captures and summaries are under
`build/lifetime-summaries-20260914/` (ignored build artifacts).

The helper benchmark places `main` before its helper in both versions. The previous
compiler rejects the reverse order with an invalid cross-function debug location
under full tracing; this separate debug-info defect is not a memory optimization.


The lifetime-summary revision also fixes named region activation: `in r:` now
selects the hidden caller arena for a declared `@r`, instead of requiring an Arena
local. It borrows that arena and preserves outer-container growth bookkeeping.
This removes the three EASM declines recorded above. The two-output region fixture
matches stage0 at runtime; emitted IR routes the outputs to distinct hidden slots.

Validation for this revision: both the stage0-seeded candidate and its self-hosted
gen2 pass all nine loop/region runtime fixtures, positive and negative inference IR
checks, and the 8/8 EASM command smoke. `self_host_gen2.sh` completes successfully.
The final seed emits a byte-identical traced helper benchmark object to the
profiled candidate. No full corpus or multi-generation bootstrap fixpoint is
claimed; no gate was bypassed or ratchet changed. Changes remain uncommitted.
