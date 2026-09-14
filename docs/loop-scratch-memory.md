# Loop scratch allocation: first measured increment

Stage0 already tightens some iteration-local allocations into lazy regions and
resets lazy loop regions between iterations. Stage1 now implements lazy loop
region reuse and a conservative subset of automatic scratch inference.

The inferred subset starts with one fresh, unpinned `darray` of primitive scalar
values. Its remaining statements may push/reserve that array, read scalar elements
or metadata, update existing scalar locals, branch, break, or continue. Unknown
calls, borrows, aliases, slices, outer-container growth, extra declarations, and
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
checks scalar inference, early exits/deferred reads, fallback on borrowed calls
and outer growth, metadata copy-out, and trace compilation. A negative user-defined
`count` field test preserves stage1's baseline rejection; stage0 currently accepts
that separate unsafe escape, so it is not used as a negative oracle there.


## Validation and remaining baseline blocker

- The focused runtime smoke passes against stage0 and the candidate stage1.
- Fifteen targeted differential corpus workers report MATCH, with zero mismatches
  and zero declines (loops, regions, drops, protocol dispatch, and the original
  module-nested UFCS cases).
- Profiler runs have zero dropped events; their target results remain exit 0.
- The normal optimized stage0-seeded build and runtime build succeed. The installed
  `bin/elisac-stage1` passes the runtime smoke and emits byte-identical objects to
  the profiled candidate for both traced and uninstrumented benchmark inputs.
- Full self-hosting remains blocked by `easm_verify_file`, `easm_emit_export`, and
  `easm_join_into`. After the metadata correction, those are the only reported
  backend declines. The baseline compiler produces the same three declines when
  its earlier metadata false positive is bypassed for diagnosis only. No gate was
  disabled for candidate validation and no ratchet was changed.

The whole differential corpus and bootstrap fixpoint are not claimed as passing.
Diagnostic logs are saved with the local profile artifacts.
