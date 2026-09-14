# Loop scratch allocation: first measured increment

Stage0 already tightens some iteration-local allocations into lazy regions and
resets lazy loop regions between iterations. Stage1 now implements lazy loop
region reuse and a conservative subset of automatic scratch inference.

The inferred subset starts with one fresh, unpinned `darray` of primitive scalar
values. Its remaining statements may push/reserve that array, read scalar elements
or metadata, update existing scalar locals, call proven read-only helpers, copy
scalars into an outer scalar darray, branch, break, or continue. Unproved calls,
aliases, slices, aggregate escapes, extra loop-local declarations, and unrecognized
syntax retain the existing allocation behavior. This is a conservative proof, not
general interprocedural escape analysis.

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

The initial proof accepted a uniquely named global function with one borrowed
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
claimed; no gate was bypassed or ratchet changed. This increment was committed as
`e58764ee`.


## Broader helper bodies and surviving scalar outputs

The next increment proves explicitly typed scalar locals, local assignments,
conditionals, scalar conditional expressions, array/range `for` loops, `while`
loops, and ordinary break/continue. The parser's capture-header block wrappers are
checked recursively with lexical scope restoration. Read-only helper chains still
reach a fixed point; recursion without a proof stays unknown. Names cannot shadow
the borrowed parameter or another active local in this subset. References,
aggregate locals, writes through arrays/fields, and writes to globals are rejected.
Module-qualified, overloaded, generic, and multi-parameter helper summaries remain
future work.

An outer scalar darray may now receive `out.push(sum_values(&xs))`: only the scalar
result survives. Existing growth routing allocates `out` in its declaration arena,
while `xs` resets each iteration. Tests validate every output after repeated growth
and after scratch cleanup. This does not yet infer split lifetimes for returned
strings, views, or aggregate results.

Set `ELISA_EXPLAIN_MEMORY=1` when compiling to print opt-in memory explanations to
stdout. Helper records identify the declaration line and either its proven summary
or the blocking operation; loop records report scratch reuse or fallback. Included
sources currently use the backend's expanded-unit line numbers. Normal compilation
is silent. For example:

```
ELISA_EXPLAIN_MEMORY=1 bin/elisac-stage1 -emit obj -o /tmp/reduction.o \
  test/differential/cases/loop_scratch_summary_reduction.elisa
```

Across five complete elisa-profiler captures, the reduction case falls from
8,323,072 to 1,802,240 median peak RSS bytes; the surviving-output case falls from
8,323,072 to 1,785,856. Both perform 200 scratch resets. Allocation requests remain
200 and 201 respectively; the output workload keeps a separate output allocation.
There are zero dropped events. Full tracing adds reset observer work and increases
CPU time, so the uninstrumented reduction control is also recorded: median CPU
17.193 → 5.233 ms and wall time 27.105 → 11.600 ms. The host was running other builds;
timings are indicative, not a ratchet. Artifacts are in
`build/memory-reductions-20260914/`.

Real-parser profiling is reproducible with `test/parity/profile_parser_memory.sh
COMPILER OUTPUT_DIRECTORY [SOURCE_INPUT] [MODE]` (default mode: `sample`). The earlier compiler rejects its traced
build because function prologues inherit the previous function's debug location.
The new emitter establishes a function-local fallback location, preserves statement
locations while hoisting allocas, and uses exact declaration identities for DWARF
overloads. Stripped runtime/collector bodies also lose their definition-only debug
metadata. The regression tests use `-g` and `-ftrace`, link and execute the result,
and require distinct debug attachments for both overloads.


The real parser harness produces byte-identical uninstrumented `-O2` objects before
and after the new lifetime inference. There is consequently no claimed parser
speedup from this subset. It parses `codegen_locals.elisa` with zero errors (1,531
tokens, one top-level declaration), and the elisa-ui text-measurement/layout source
with zero errors (472 tokens, four top-level declarations). Profiling the latter is
a parser workload over UI source, not a measurement of the running UI application.


The repaired self-hosted compiler records complete sample-mode parser captures
with zero dropped events: median peak RSS 2,834,432 bytes on compiler source and
2,490,368 on UI source. These are instrumentation-mode measurements, not evidence
of an inference speedup or allocation-site attribution. The native profiler itself
needed no source changes; the blockers were malformed compiler debug metadata.

A full detailed parser capture is also complete and lossless: 636 allocation calls,
23 in-place reallocations, and 27 moving reallocations (686 requests). Their
requested sizes sum to 456,640 bytes; this sum includes reallocations and is not
live memory. There is one backing-region creation. Empty/lazy carrier cleanup
accounts for many free calls, so free-call counts do not imply OS allocations.
This input does not reproduce loop-region accumulation; the new synthetic wins
must not be generalized to parser throughput. `parser-full.html` and
`parser-allocation-summary.json` preserve the evidence for further work.

Final validation: the installed optimized stage0-seeded product and the latest
self-hosted build pass all 13 paired stage0/stage1 runtime cases, positive/fallback
inference checks, explanation assertions, debug-prologue execution, and overload
DWARF checks. Both pass the 8/8 EASM command smoke. Self-host rebuilds succeed, and
the installed compiler records a complete, zero-loss real-parser profile. Its
non-DWARF traced reduction/output objects are byte-identical to the profiled
candidate. No full corpus or bootstrap fixpoint is claimed, and no ratchet changed.
The broader-proof and profiling fixes are uncommitted.

## Module helpers, scalar parameters, and allocation sites (2026-09-14)

The summary proof now accepts a single borrowed scalar darray at any parameter
position, accompanied by scalar value parameters. It analyzes the scalar
parameters as locals and checks every call argument. Module-qualified calls and
bare calls within the same module participate in the fixed-point proof. Names
must still be unique across the declaration tree and function table; overloads,
generics, UFCS spelling, additional reference parameters, and aggregate results
remain conservative. This is namespace helper support, not a general method
or ownership proof.

`loop_scratch_summary_module` covers a module-qualified, transitive helper with
scalar arguments on both sides of its borrow. `loop_scratch_summary_multi_mutation`
checks that an additional mutable reference prevents inference. The seed and
self-hosted compilers pass all 15 paired runtime cases plus positive/fallback IR
checks. The self-host rebuild succeeds. No corpus ratchet was changed.

The corresponding `loop_region_module` benchmark performs 200 iterations with a
32 KiB temporary buffer. Five full-mode elisa-profiler repetitions per version,
with one warmup, produced complete captures with zero drops:

| Measurement | Before | After |
| --- | ---: | ---: |
| Peak logical live allocation | 6,553,600 B | 32,768 B |
| Peak observed backing capacity | 7,340,032 B | 1,048,576 B |
| Median peak RSS | 8,323,072 B | 1,966,080 B |
| Allocation requests | 200 | 200 |
| Region resets | 0 | 200 |

The allocation traffic is unchanged; its lifetime is shorter. The 99.5% logical
live-byte reduction is reconstructed from ordered runtime events, not inferred
from RSS. RSS is a separate full-instrumentation observation on this host; no
precise timing speedup is claimed. After a reset the scratch arena retains 1 MiB
of backing capacity for reuse. Function exit releases it.

Artifacts are in `build/memory-sites-20260914/`: `summary.json`, the paired module
captures, `module/{before,after}-sites.json`, `parser-final/parser.json`, and
`parser-sites.json`. The profiler's `scripts/analyze-allocation-sites.py` produces
the site/lifetime analysis, while its native HTML report provides a source-site
traffic table with retained caller context. Unsupported lifecycle operations
(adoption, trim, rewind) explicitly disable reconstructed lifetime metrics;
raw observations and traffic remain available.

### Next real workload: tokenization and parsing

The real parser was profiled on `src/backend/codegen_locals.elisa` for five
complete, zero-loss full-mode repetitions. Its first repetition reconstructed
300,968 B peak logical live allocation and 1 MiB observed backing capacity. This
is a baseline measurement, not a claimed parser optimization.

Allocation attribution now identifies both the lexer token-buffer growth and
`result.extend(lexer.machine_tokens)` in `src/lexer/lexer_tokens.elisa`. The latter
copies the completed buffer immediately before returning it. This is the next
concrete aggregate-ownership target: prove when the finished field can transfer
to the result, and separately prove which lexer/parser state can be reclaimed
while the returned tokens/AST remain alive. Source-backed string views must keep
the input alive. Region reset must never substitute for that field-level proof.

Several approximately 37 KiB allocation requests also occur at parser
construction and expression/statement returns. Their observed source sites are
now known, but their causes and escape relationships still need investigation;
no stack promotion or early reclamation has been applied to them.

Final product check: the optimized compiler and native profiler have been rebuilt
and installed. The installed compiler passes the 15-case runtime/IR smoke and a
fresh full-mode module benchmark capture confirms the 32 KiB logical-live peak.
The profiler passes collector content/trace-buffer/identity tests, allocation-site
thread and truncation tests, ASan/UBSan collector checks, protocol recovery and
offline round-trip tests, lifetime-analysis tests, and the generated HTML
controller test with adjacent uint64 identities above JavaScript's safe range.
Changes in both repositories remain uncommitted.
