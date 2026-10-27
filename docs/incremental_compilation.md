# Incremental compilation design

## Active implementation objective (2026-10-17)

Develop fast incremental compilation across ordinary edits, rather than waiting
for the outstanding compiler proof diagnostics to reach zero. All development
and measurements now run locally. The existing whole-object cache and narrow
Global-authority experiment below are foundations, not completion of this goal.

For low-level profile and generated-code caveats, see the
[incremental bottleneck review](incremental_bottleneck_review.md).
For the Zig, rustc, Clang/LLVM, and GCC design comparison, see the
[compiler incrementality reference study](compiler_incrementality_reference_study.md).

A local profiled bootstrap at core `a5f8100b` and stage1 `c2e8b8551e94`
took 111.82 seconds wall time, 107.74 seconds user time, 32.17 seconds system
time, and 5,091,180,544 bytes peak RSS. It stopped at semantic diagnostics;
it establishes no optimization, emission, or linking baseline. The Go CPU profile
sampled substantial allocation/clearing cost (`runtime.memclrNoHeapPointers`
46.76%, `runtime.madvise` 14.84%). Child solver CPU is outside that profile.
These are one-run observations, not a speedup claim. Raw local evidence is in
`build/verification/incremental-baseline/` (ignored build artifacts).

The implementation must make unchanged function analysis reusable. Start with
tracked semantic queries and a versioned function-result representation; avoid
persisting mutable AST, SymbolTable, or LLVM handles. Separate body identity from
the callable interface, including contracts, inferred effects and borrows,
constant evaluation, ghost definitions, generic specialization and inlining
dependencies. Track lookup-set dependencies as well as selected callees: adding
an overload or implementation can change an unchanged caller's resolution.

Retained results must rebind diagnostics to current source anchors, replay
errors as well as successful results, and invalidate on changes to options,
compiler semantics, dependencies, target, or runtime inputs. Corruption and
unsupported cases must take the clean path. Reuse must not require an entirely
error-free translation unit. Persistent exact-query SMT reuse can be a supporting
layer, but is not a replacement for semantic dependency tracking.

Qualify cold, unchanged, independent body edit, callee body edit, signature or
contract edit, constant edit, added/removed overload or implementation, include
edit, source relocation, and corrupt-cache cases. Compare clean and incremental
diagnostics, inferred results, native behavior and output policy. Report visited
and reused functions plus phase time; measure with whole-object avoidance
disabled when testing partial reuse. Keep backend artifact reuse as a subsequent
boundary with explicit optimizer dependencies and cold/warm parity.

## Zig-inspired graph and artifact-identity foundations (2026-10-18)

The Stage1 semantic session now owns compact query and edge IDs, exact query-key
bytes, contiguous query and edge pools, reverse and forward adjacency, dependency
replacement, and reverse invalidation. This is a storage/API foundation only:
semantic read sites do not record these edges, result fingerprints are not
replayed, and checker behavior and edit performance are unchanged. The target
descriptor also records both module and machine triples/layouts plus CPU and
features, rejecting mismatched pairs. Executable/LLVM path discovery is
available on Linux and macOS, while mapped-image digest attestation remains
unsupported; the Stage1 CLI's O0 shard-cache route therefore remains unwired.
The separate Go Core compile-server does have a narrow caller: named incremental
object requests route through `IncrementalObjectSession.WriteObject` after fresh
analysis. That source integration does not qualify the Stage1 CLI path or a
current-tree end-to-end speedup.

## Bootstrap query publication measurement (2026-10-18)

The Core bootstrap compiler has a separate in-process tracked-query session used
by its opt-in compile server. Its publication path now consumes the validated,
deduplicated input inventory directly, avoiding a full map-to-slice-to-map copy.
Atomic revision updates, missing-versus-empty inputs, and public last-write-wins
semantics are preserved. A differential edit-history test and race-enabled query
tests pass, as do the focused incremental semantic, compile-server, and native/LLVM
parity tests. Consumer tests used read-only Go overlays to exclude concurrent,
unrelated verifier edits from both baseline and candidate.

Three local runs on an Apple M5 measured median query-session publication falling
from 2.36 to 2.14 ms for 4,096 input edges, and from 19.40 to 17.56 ms for 32,768
edges (1,024 queries in each case). Allocated bytes fell about 14% and 16%.
The synthetic retained local-initializer edit benchmark measured 6.71 versus
6.51 ms medians, with exactly one initializer checked and 127 reused in both
versions. These short, sequential samples are exploratory; they do not establish
a project-wide compile speedup. Raw measurements and source hashes are retained
under `build/verification/incremental-publication-20261018.*`.

This change reduces cache-maintenance overhead. General semantic-body reuse,
persistent result replay, backend reuse, and representative edit-to-executable
qualification remain required for the full incremental-compilation objective.

The Core return-expression cache also now admits canonical `int` parameters and
returns alongside `i64`. Exact parameter/return types remain part of the source
identity; current symbol ownership, builtin types, and arithmetic operator-set
absence are checked before replay. Body/type edits, source relocation, errorful
fallback, and added/removed `int` operator implementations have cold/warm parity
controls. Local-initializer replay retains its existing `i64` restrictions.
LLVM equality and native exit-status checks cover both return types.

A 256-function analysis-only body-edit workload now reuses 255 return bodies and
checks one changed body. Three short local runs measured approximately 191 ms
medians both before and after: no reliable timing improvement is established.
Allocation counts fell from about 1.162 million to 1.016 million per edit, with
allocated bytes falling from 242.3 to 239.2 MB. Both variants include the same
alias-identity ownership fix: optimization facts formerly formatted Symbol
addresses without retaining their owners, allowing GC address reuse to merge
unrelated identities. The new per-analyzer identity map both retains owners and
reuses formatted identities. A forced-GC regression fails on the previous
implementation and passes with ownership retained. These are in-process query
and typing results, not full-build incremental-compilation qualification.

A subsequent profile of that retained-edit workload identified query publication
as the largest analyzed CPU contributor. Source-node liveness previously built a
complete canonical byte buffer and SHA256 digest, then discarded the digest.
Liveness now uses the same structural visitor with logical byte counting: it
preserves graph traversal, node identity, rejection rules, and depth/work/byte
budgets without allocating the serialization buffer or computing a hash. Identity
creation and exact-tree rebinding still use full fingerprints; liveness only
checks pointer survival for already indexed source anchors. Per-encoder
struct field-name caching also avoids repeated reflection metadata construction;
it retains no cross-invocation schema state. A golden baseline fingerprint guards
encoding compatibility, and differential tests cover trees, shared nodes, cycles,
and byte/work/depth rejection.

Three alternating local before/after samples measured the liveness scan at
222 versus 114 microseconds median, with 191,329 versus 61,600 allocated bytes.
The 256-function edit workload retained the same 255 reuse / one check counts and
reduced allocated bytes from about 239.2 to 223.4 MB. Its timing was variable on
the shared host, so these samples do not establish an overall compiler speedup.

Lexical query keys now use a versioned, length-prefixed encoding with canonical
ASCII base64 transport instead of repeatedly encoding the dependency spec as
JSON. Function identity, tree digest, source ordinal/kind, lookup role, domain,
and requested name all remain exact key fields. A schema gate refuses added
fields until the encoding is reviewed. Decoding rejects truncation, oversized
lengths, invalid UTF-8 fields, trailing data, unknown versions, and alternate
base64 spellings. Existing negative-prefix, nil-blocker, mutation, and binding
invalidation controls remain applicable; query results and diagnostics keep
their existing representation. Validation-only call sites avoid constructing
keys they would immediately discard. This remains a server-local query format,
not a persistent semantic-result cache.

Three alternating local samples measured key encoding at 670 versus 198 ns and
decoding at 2,656 versus 355 ns medians. The synthetic retained-edit analysis
workload measured 177 versus 166 ms medians with the same 255 body reuses and one
body check. Allocated bytes fell from about 223.4 to 211.8 MB per edit. These short
analysis-only samples exclude parsing, native emission, and linking; they do not
establish project-wide edit-to-executable performance.

A final confirmation on the bounded codec used three alternating pairs with
five timed edits per sample: medians were 211 versus 195 ms, with 223.4 versus
211.8 MB allocated per edit and unchanged reuse/check counts. The full semantic
suite, compile-server controls, LLVM/native parity, and 18,934 codec fuzz inputs
passed. Consumer gates excluded concurrent unrelated verifier edits through
read-only Go overlays; they do not qualify that separate verifier candidate.

## Native pipeline baseline (2026-10-18)

`BenchmarkIncrementalEditPipeline` in the Core backend now measures fresh parsing,
analysis, LLVM lowering/verification, and native O0 object emission together. It
alternates a real single-body edit in 256 integer arithmetic functions. Parsing
is inside timing; session warmup, linking, and process startup are outside it.
The fresh control uses ordinary analysis without a retained query session.

Three local samples of three edits each gave these median stage times:

| Mode | Parse | Analysis | LLVM lowering | Native object | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fresh | 14.3 ms | 63.3 ms | 52.7 ms | 275.1 ms | 406.1 ms |
| Retained | 13.6 ms | 161.4 ms | 51.5 ms | 273.6 ms | 501.1 ms |

Retained analysis checked one body and reused 255 on every edit, yet the complete
measured pipeline was about 23% slower than fresh. Allocated bytes were 259.7 MB
versus 108.1 MB. The earlier before/after query optimizations improved the
retained path, but do not establish that retention is faster than clean analysis.
Do not enable it by default on that evidence. These are synthetic, short-run
measurements, not full compiler self-compilation timings.

The next performance gates must compare against fresh compilation, as well as
the previous retained implementation. Query publication/validation overhead must
fall below the work it avoids. Native object generation is also a major reuse
target. Current lowering emits bodies into one shared LLVM module; emitting a
body can additionally create globals, helpers, and generic specializations.
Backend reuse therefore needs a dependency-complete artifact boundary, target
and code-generation option validation, and native parity across edits. Skipping
an unchanged body without restoring its generated dependencies is insufficient.

### Keep resolver auditing separate from compilation

Profiling the retained pipeline identified a shadow lexical query audit as a
major cost. It records ordinary resolver reads, builds a separate query world,
then compares query answers to the ordinary resolver after analysis. That world
does not authorize the current primitive typing replay: current parameter/local
binding queries and integer-operator-set checks provide that admission boundary.

The default `NewIncrementalAnalysisSession` now omits this shadow audit.
`NewIncrementalAnalysisSessionWithOptions` with `AuditLexicalReads: true` retains
the complete audit for qualification and future query integration. Lexical audit
tests explicitly select it. This option does not disable any dependency used by
current reuse. An edit-history test compares fresh, retained, and audited results
through source relocation, body edits, missing identifiers, and type changes,
while requiring identical body/initializer replay decisions. LLVM/native parity
also runs with auditing enabled and disabled.

The pipeline benchmark now has separate `fresh`, `retained`, and `retained-audit`
modes. Earlier retained measurements in this document included the audit; do not
compare those timings to default sessions without accounting for this change.
Three subsequent rounds, each running all three modes for five timed edits,
measured these medians with no other tests from this task running:

| Mode | Analysis | Parse through object | Allocated bytes/edit | Allocations/edit |
| --- | ---: | ---: | ---: | ---: |
| Fresh | 60.79 ms | 421.69 ms | 108.10 MB | 1,053,503 |
| Retained | 56.87 ms | 408.50 ms | 105.16 MB | 908,851 |
| Retained with audit | 173.00 ms | 527.43 ms | 259.50 MB | 1,330,367 |

Both retained modes checked one body and reused 255 per edit. Moving the shadow
audit off the normal path reduced its analysis median by about 67% and allocated
bytes by about 59%. Retained total samples ranged from 402.7 to 511.7 ms;
fresh ranged from 409.0 to 433.9 ms. Shared-host timing variation is too large to
qualify a reliable overall advantage over fresh compilation. These samples
establish the audit's cost on this synthetic workload, not professional compiler
iteration latency. Raw logs and source snapshots are retained under
`build/verification/incremental-audit-options-20261018/`.
The full isolated semantic suite passed in 62.390 seconds; focused compile-server
and LLVM/native parity checks also passed. Read-only overlays excluded concurrent
verifier implementations and their matching new tests. The incremental source
snapshots match Core commit `de3a9a8428d6`; that commit also includes separate
verifier work which these isolated checks do not qualify.
The full general semantic and backend reuse objective remains unfinished.

## Historical local implementation snapshot (2026-10-11)

Historical VAST timings are motivation, not the current local baseline;
qualification uses local compute and pinned compiler/runtime tuples.
At that date, the `main` worktree had an opt-in persistent-cache implementation
for one narrow Global-authority case. A fresh self-host build and focused parity
controls passed then, but this was not the general semantic cache described
below and had no performance qualification. The current status is recorded in
the implementation stages below.

Current-invocation authority event reuse has passed native diagnostic and ordered
effect-array parity tests in isolated candidates. It reuses observations during
one compilation, without loading records from a previous build. A matched profile
of the earlier candidate did not establish a robust end-to-end speedup. The field
index and immutable field views in candidate `400d4173` passed a frozen native
gate, but its own compiler product and performance remain unqualified.

The backend source separately prepares stable logical shards, restricted LLVM
bitcode snapshots with verifier checks, and an exact target-machine recipe. These
drafts still need native qualification. They are boundaries
for object reuse; they do not skip semantic analysis or IR construction. The native
streaming digest is still a source draft. Persistent cache admission, atomic object
publication, and scheduling only cache misses remain to be implemented and tested.
Producer and loaded LLVM identities must be verified against actual artifacts;
environment paths or supplied digest strings alone cannot authorize a hit.

The function-fact collector and snapshot codec are connected to an explicit
`ELISA_STAGE1_INCREMENTAL_CACHE_DIR` opt-in. The driver reloads a bounded,
versioned snapshot and recollects facts from the exact current AST/source/token
tuple. Persisted flags and facts remain hints for matching only; they never
authorize a checker skip. Current-source records with unique top-level definition
anchors, successful supported-body scans, and zero direct facts can skip the
Global-authority inference walk and, when enabled, its report walk, repeated
effect-source body scans, and the two per-body panic-coverage walks, including on
cold runs. A direct-call-only body can also replace the Global-authority inference
walk after its targets are resolved against the current function index; its report
walk stays cold. When Global permission enforcement is enabled, Read/Write axes
project freshly collected facts for eligible flat bodies without local bindings,
while retaining each function slot; verified zero-fact bodies contribute empty
axes. The live collector now leaves every plain `Stmt.Assign(..., Assign, ...)`
out of the incremental fact lane, regardless of target or RHS; literal
`Stmt.VarDecl` bindings remain independently eligible. This conservative cache
boundary avoids relying on incomplete name indexes while the Global-permission
and Global-authority walkers disagree about fresh identifier targets. It
preserves cold/warm parity without deciding assignment semantics. The source
change has not been compiled or tested; the reference study records the
required Stage0 oracle and cold/warm parity cases.

The panic pass still builds its wrapper index and annotation views and visits
declarations; only bound-name collection and its body walkers are skipped. The
conservative collector rejects local reference writes, nested grant blocks,
parenthesized expressions, and
unsupported syntax so these skips preserve authority behavior and walker-depth
diagnostics. Global-authority replay also stays cold for the whole unit when
inline-grant annotations are present, because their spans are not yet bound to
function facts. Other bodies, checkers, closure construction, and report publication
stay on the cold path. Invocation-local body anchors are rebuilt on each parse.
For the disk-sidecar path, semantic diagnostics are recomputed every invocation;
that path does not replay semantic results or qualify an incremental-compilation
speedup.

The opaque `IncrementalSemanticSession` handle also supports edits within the
same canonical include graph, options, phase, and semantic version. Semantic
owns its retained state. The session compares an
exact declaration surface that retains function headers, then copies facts only for
functions whose tokenized bodies are unchanged; copied owners and byte spans are
rebuilt in the new snapshot, and current parse anchors are regenerated. Changed or
unsupported bodies take the collector walk. Disk sidecars never authorize this
cross-edit fact reuse. Ordinary one-shot CLI compilation still uses the
session-disabled wrapper. The opt-in `semantic-session` host retains one session
across requests; the opt-in `compile-session` host retains a source-bound session
for up to 32 requests per epoch. Both call the session-aware entry point. The new
`test/parity/incremental_semantic_session_control.sh` control drives cold, exact,
edited, invalid, and restored requests through the normal Stage1 wrapper. It checks
the status protocol and the reported session hit/edit decisions; it still needs to
run against a fresh Stage1 product before qualifying the host's runtime behavior.

The long-lived session also retains bounded self-assignment linter facts per
function. When the function key and body tokens match exactly, it rebinds saved
target and statement token ordinals to the current source, then replays those
diagnostics. Bodies without complete, valid anchors use the original streaming
checker. These linter facts are process-local and omitted from disk sidecars.
`self_assignment_bodies_scanned` and `self_assignment_bodies_reused` report this
path separately from direct-fact matching. The session control also checks that
warning locations move with an inserted source line, that a captured-loop
self-assignment stays on the checker fallback and is still reported, and that the
report records replay for supported straight-line bodies. It is a correctness control,
not a performance measurement, so it does not establish a compiler speedup.

The existing narrow parity controls previously covered cold, first-cache, warm,
body-edited, option-changed, structurally valid forged-sidecar, and corrupted-cache
runs for diagnostics and exit status, plus canonical effect rows in direct checker
controls. They predate the current-source skip expansion and tightened fact
eligibility; those changes still need parity and performance qualification. They
do not validate reuse of semantic body analysis. Existing
Global-permission, static-generation, and source-identity shadow gates also pass.
Further invalidation workloads must cover dependencies before eligibility expands.
No timing claim is made from these parity controls. Small cross-language
frontend/object timings do not prove incremental performance or professional
compiler efficiency across representative projects.

Prior-snapshot function-key lookup is indexed on `main` (integrated at
`93cc402c`). Seven paired shared-Mac warm-cache runs showed a median paired
speedup of about 5.0x by the runner's `wall_seconds` metric for the dense
4,096-helper case, with identical prior snapshot bytes, diagnostics and reuse
counts. This is outer wall time and includes `/usr/bin/time -l` wrapper startup
and capture overhead. Small and low-query cases were near parity by the same
metric. The runner separately records and reports `compiler_real_seconds`; that
metric does not underlie these headline ratios unless its specific paired ratio
is quoted. These are exploratory opt-in warm-cache results, not qualified Linux
results or evidence of default cold-compilation speed.

Current-function name uniqueness now also uses an index. Its exact-name hash buckets retain byte
comparison and reject a name immediately after the second exact match. In seven
shared-Mac pairs, a 4,097-function collector workload with mostly unsupported
generic bodies had a 3.046x median paired speedup by runner `wall_seconds`, the
outer wall metric that includes `/usr/bin/time -l` wrapper startup and capture
overhead; full canonical encoded snapshot bytes matched in every pair. The
runner separately records and reports `compiler_real_seconds`; that metric does
not underlie this headline ratio unless its specific paired ratio is quoted.
This span excludes parsing, object emission and linking. The full self-host
compiler seed and incremental correctness gate passed, including uniqueness and
prior-key controls at O0/O2, exact legacy encoding,
warm/cold diagnostic and effect-row parity, source revalidation of forged
sidecars, body/option invalidation, generated input and corruption misses.
These correctness checks support integration; the timing result remains scoped
to this collector workload rather than general compiler speed.

Cache preparation also needs its own cost accounting. The current snapshot helper
verifies the parent, builds owners, clones the complete module, strips foreign
bodies, verifies the clone, and serializes bitcode for each shard. A production
cache path should prepare the immutable owner inventory and parent verification
once, then reuse each restricted shard for hashing and any miss emission. Record
clone, restriction, verification, serialization, hashing, lookup, and emission
costs separately. Measure hit count and total elapsed time on a compiler body edit;
valid keys alone do not prove that caching improves throughput.

Per-variant arena storage remains a separate language/runtime requirement. The
current packed AST uses an AoS store with side words; that is not evidence that
each AST variant has its own iterable array. A future arena ADT layout must retain
pattern matching and stable handles, expose bounded variant iteration, preserve
ownership and reference invalidation rules, and support bulk construction before
parallel traversal. Benchmark allocation and traversal costs independently of
incremental reuse, including scalar and vectorized loops over eligible fields.

## Goal

Make a body-only edit pay for the changed function's semantic analysis and code generation, while reusing results for unaffected functions. The first target is the paired `check_ungranted_panic` and `check_mutable_global_authority` work: the current path scans bodies in both passes, and the authority pass rebuilds its function/global indexes and effect closure on each invocation. The reported 993-second paired diagnostic interval is the motivating workload; its exact phase timing must be captured on the same seed and box before and after each milestone.

Cache reuse is valid only when it produces the same diagnostics, inferred effect rows, and compiled behavior as a cold full compile. A cache miss, unsupported syntax, changed compiler semantics, or invalid cache data must take the ordinary full path.

## Current seams and limits

`src/driver/elisac_includes.elisa` expands includes into one flat source buffer and carries an original-file line map. Generated-source diagnostics compose that map to preserve original file and line locations; when no include map exists, the driver composes an identity map. Columns still refer to the generated buffer. `src/driver/elisac.elisa` tokenizes and parses that buffer into one `Ast::File`, then calls `run_semantic_gate` before creating one LLVM module. This means the first implementation should cache function bodies inside the translation unit; treating include files as independent compilation units would change name lookup and module semantics.

In `src/semantic/semantic_api.elisa`, `collect_effect_sources` runs before `check_ungranted_panic`, and `check_mutable_global_authority` follows it. The body passes still compute from current AST facts: zero-fact records bypass supported body walks, direct-call-only records can seed Global-authority inference after current target resolution, and Global-permission axes project current direct facts for flat bodies without local bindings. Both call-based projections fall back to the AST when ordinary global lookup resolves the callee spelling, preserving the cold walk's callee-identifier read. `check_mutable_global_authority` still creates a fresh `GlobalAuthority`, collects declarations and lexical indexes, closes call/effect rows, publishes rows to `SymbolTable`, and walks unsupported or fact-bearing bodies outside the direct-call-only case. Its numeric function slots, lexical scope numbers, AST nodes, offsets, and interned references are invocation-local and cannot be written to disk as identities.

The compiler has content-addressed caches for a complete unchanged stage1 object build in `scripts/elisac_stage1.sh`, plus build/runtime object provenance helpers. Those caches do not help when one function changes because the object key covers the complete compile invocation. The semantic sidecar is an opt-in prototype; it currently saves narrowly eligible body walks in the Global-authority, effect-source, panic-coverage, and Global-permission passes. It does not cache codegen, pass-level indexes, closure construction, or diagnostics.

The backend has a useful body boundary: `src/backend/codegen_module.elisa` declares module entities before `emit_module_bodies`, and `src/backend/codegen_declare.elisa` contains `emit_function_body`. It currently emits into one shared LLVM module. `src/backend/llvm_c.elisa` binds bitcode writing, but not bitcode parsing or module linking. Reusing a body therefore needs an explicit fragment restore path; skipping `emit_function_body` alone would leave the new module without that body.

## First semantic artifact

The persistent unit is a **function body fact record**, not an AST, `SymbolTable`, or LLVM object. One record is produced for each supported function after the current declaration and import environment is known. A single per-invocation collector should supply facts to both panic/effect analysis and mutable-global authority analysis. The existing full implementation remains the reference path while the collector is introduced.

Schema version 1 should contain:

```text
CacheHeader {
  format: "elisa-semantic-facts"
  schema: 1
  compiler_semantic_fingerprint: Digest
  language_and_semantic_options: CanonicalOptions
  translation_unit: CanonicalPath
  include_graph_structure_fingerprint: Digest
}

FunctionRecord {
  key: StableFunctionKey
  declaration_api_fingerprint: Digest
  body_fingerprint: Digest
  dependencies: [Dependency]
  observations: FunctionBodyObservations
}

StableFunctionKey {
  source_path: CanonicalPath
  lexical_module_path: [Name]
  owner_kind_and_name: Optional[CanonicalOwner]
  function_name: Name
  canonical_generic_shape: CanonicalTypeText
  canonical_parameter_types: [CanonicalTypeText]
  canonical_return_type: CanonicalTypeText
}
```

The function key excludes signature effect rows: changing an effect contract should keep the function's identity so dependents can be invalidated through its changed API fingerprint. It includes the owner and lexical module because equal method names in different protocol/impl/module scopes are different functions. Overload identity uses canonical source-level types, never `DeclId`, `TypeId`, parser offsets, AST handles, or table slots. If the language permits return-type-only overloads, the return type in the key keeps those distinct.

`declaration_api_fingerprint` covers all caller-visible properties: parameter and return types, generic constraints, defaults and labels, receiver mutability/state, declared effect row, and ABI-relevant attributes. The exact canonical type/effect encoding must be versioned. Fingerprint equality is meaningful only within the compiler semantic fingerprint.

`body_fingerprint` is initially a digest of the function body's token sequence, excluding the declaration signature and surrounding trivia. The token sequence retains literal/name/operator spelling but ignores comments and whitespace. Diagnostic anchors are token-relative and remapped through the current source line map, so a body can move when text before it changes. If the parser cannot provide complete token bounds for a body, that record is non-cacheable.

`FunctionBodyObservations` must own only serializable values:

- Direct reads and writes of resolved mutable globals, including canonical global identity and access-site anchor.
- Local `can` grant and `trusted` firewall regions, with canonical effect references and lexical scope identity.
- Direct calls, including the resolved stable callee key, selected overload-set fingerprint, source anchor, and grant/firewall state at the call.
- Panic, signal, raw effect-call, and other effect-source sites plus the grant/firewall state needed to replay diagnostics.
- Callback handoff/returned-callee edges and generic instantiation identity when the collector can resolve them completely.
- Dependency records needed to prove that those observations still mean the same thing.

An anchor is a byte range relative to the exact body bytes, not an absolute file offset or line. Diagnostics are regenerated from current anchors and the current line map; serialized diagnostics are not authoritative. This lets an unchanged body move because another declaration was inserted before it.

The facts are direct observations. Do not persist a transitive effect row as if it were direct. Recompute the small call-graph closure from direct rows and edges every invocation at first. This makes caller summaries respond correctly when a callee body changes without rescanning each caller body. Later profiling can justify persisting closure results with reverse-edge invalidation.

## Invalidation contract

Each cache record is reusable only when its compiler fingerprint, options, stable key, body fingerprint, and every dependency fingerprint match. Initially a changed translation-unit include graph structure or compiler semantic fingerprint invalidates all records. The graph fingerprint covers canonical paths, include edges, and expansion order, rather than all file contents; hashing all contents here would turn every body edit into a complete cache miss. File content changes are accounted for by body, declaration, and lookup dependency fingerprints. Ordinary body edits should invalidate only that body record plus downstream closure and diagnostics that depend on changed facts.

Record the following dependencies explicitly:

| Dependency | What must be fingerprinted | Invalidation consequence |
|---|---|---|
| Resolved function call | Stable callee key and caller-visible API fingerprint, including effect row | Recompute call coverage and effect closure for the caller and reverse callers when the callee's inferred/exported row changes. A stable call edge does not require rescanning the caller body. |
| Overload selection | The full candidate set visible at the lookup point, with candidate API fingerprints and selection-relevant type data | Any candidate add/remove/change invalidates the call observation. |
| Positive name lookup | Resolved declaration identity and relevant API/type fingerprint | Re-resolve if the declaration or referenced API changes. |
| Negative or ambiguous name lookup | Fingerprint of every searched lexical scope, import set, wildcard/member-import set, and candidate-name set | Adding a previously absent declaration or import invalidates the body even though no old positive edge points to it. |
| Mutable global access | Canonical global identity, mutability, type, and layout/field/index information used by the operation | Reanalyze the access and its grant diagnostic if the global contract changes. |
| Type/layout use | Canonical type declaration plus fields, enum variants/payloads, packed/SoA layout, aliases, and generic arguments that affect resolution or ABI | Reanalyze bodies depending on that type; ABI changes also invalidate their codegen fragments. |
| Protocol/conformance lookup | Protocol method contract, implementation owner, candidate methods, and conformance/constraint result | Re-resolve affected calls and implementations if a method, protocol contract, or conformance changes. |
| Effect capability lookup | Alias members, permission `includes`, lexical origin scope, local `can` grants, and `trusted` filters | Recompute affected rows and diagnostics. `trusted` removes only the exact Unsafe members it names; Global and other families still propagate. |
| Import/module ownership | Canonical include path, lexical module path, import aliases, from-member bindings, and wildcard visibility | Invalidate positive and negative lookups in the affected scopes. |
| Compiler/build mode | Strict unsafe/global enforcement, runtime-std mode, feature flags, target-independent semantic options, and cache schema/compiler semantic fingerprint | Invalidate facts whose observations or diagnostics can differ under the changed mode. |

Name lookup dependencies must include misses. A cache that records only resolved callees is unsound: adding a same-scope function or overload can change which function a body calls. Scope identities are canonical lexical module paths rooted in the canonical source path; in-memory scope integers are never persisted.

When a function's body facts change, invalidate its direct row and outgoing edges. Rebuild effect closure. If the resulting exported/inferred row changes, walk the reverse call-edge graph and rerun call-site grant diagnostics for affected callers. A changed body that preserves its externally visible row need not invalidate caller bodies. This is the first point where compounding reuse becomes useful: unchanged callers keep their resolved body facts while their small edge checks consume the new callee row.

The following values must never cross the disk boundary: `Ast::Expr`/`Ast::Decl`/`Ast::Pos` handles, `DeclId`, `TypeId`, `RegionId`, numeric module/function slots, local binding ordinals, intern-table indices, arena addresses, and `GlobalAuthority` scope or row indices.

## Fail-closed behavior

Version 1 should mark a record non-cacheable if the collector cannot record a complete dependency or observation for any construct in its body. The compilation may still proceed through the existing checker; it simply rescans that function on later invocations. Cache read errors, digest/schema mismatch, unsupported records, and incomplete writes are misses. Write a complete snapshot to a temporary file, validate it, then atomically rename it. Never merge a partial cache with current semantic output.

The first collector should reject caching, rather than guess, for unresolved or ambiguous calls, dynamic/indirect calls, lambdas and callback flows whose source cannot be represented, unsupported generic instantiations, macro/static-generated bodies without a stable generated-source fingerprint, unknown AST variants, and cross-boundary declarations whose ownership cannot be tied to a canonical source/module key. These limitations should be explicit counters so tests and real builds show what fraction of bodies reuse.

Effect and grant facts must keep declared and inferred rows distinct. Preserve mandatory-vs-inferred row semantics and canonical effect references. The existing `test/parity/mutable_global_authority_report.elisa` and `test/parity/global_permissions_smoke.sh` provide a useful row oracle; the existing row reporter is not itself a persistent cache fingerprint.

## Code generation stage

Semantic facts are the first milestone. Once the semantic cache is byte-for-byte equivalent to a cold run, reuse function bodies in a fresh module. Keep module-wide declaration, global, type-layout, and ABI construction current, then load cached bodies only when the function API, referenced global/type layouts, callee ABIs, generic arguments, compiler backend fingerprint, target triple/data layout, and codegen options match.

The natural generation hook is `emit_function_body` after all declarations have been entered into the current module. The required restore hook needs LLVM bitcode reader and module-link APIs in `src/backend/llvm_c.elisa` (or an equivalent narrow bridge), plus a stable way to create a function-body fragment that shares the current module's identified types and declarations. The current binding only writes bitcode. Do not treat saved object files as a substitute for this step: they skip neither semantic analysis nor changed-module IR construction.

Start codegen reuse with `-O0`, without debug/profiling/coverage metadata, and with deterministic per-function fragments. Verify linked IR before emission and compare executable behavior/object semantics against a cold compile. Keep module-wide optimization as a full step: the current LLVM `-O2` pipeline can inline and optimize across functions, so reusing already optimized function fragments would change optimization opportunities. A later ThinLTO-like design can import dependency bodies and cache per-module summaries, with its own parity gate.

## Implementation stages and acceptance

1. **Instrument the baseline.** On the exact local compiler seed and host in a quiet window, record phase wall/CPU time for `check_ungranted_panic`, `check_mutable_global_authority`, their combined interval, number of function bodies visited, number of resolved calls/edges, and current diagnostics/effect-row report. Do not infer the 993-second cost from unrelated historical self-host timings.
2. **Collect and bind facts.** The opt-in driver path now passes the exact analyzed source and tokens alongside the AST, while policy options still come from the original source. Ordinary, expanded `static generate`, and early `pymodule` gates use the paired frontend inputs. The collector remains deliberately narrow; unsupported bodies stay cold. The separate shadow observer remains observational and must not be confused with checker reuse.
3. **Persist and consume one proven case.** An opt-in sidecar uses bounded no-follow, nonblocking reads, schema/semantic/options validation, recollection against current source, exclusive temporary-file creation, and atomic rename publication. A symlink or FIFO at the cache-file path is a miss; a stale or pre-existing temporary path fails publication closed instead of being followed. These flags protect the final path component only; the configured cache directory is not pinned against symlink substitution. Every candidate body is rescanned before its current facts can authorize a skip; prior record flags and counts are only hints for body matching. The checker uses current-source-verified, uniquely anchored, cacheable zero-direct-fact top-level bodies to skip Global-authority inference/report walks, repeated effect-source scans, and two panic-coverage body scans. It also replays direct-call-only records into Global-authority inference after resolving targets against the fresh function index, and projects current direct facts into Global-permission Read/Write axes for flat bodies without local bindings. Both retain function slots and closure/row work. The direct control compares diagnostics and canonical rows with Global-permission enforcement enabled, and asserts effect-source, panic-coverage, and Global-permission axis counters. The CLI control covers cold/warm/body/option invalidation, a valid-checksum forged sidecar, corrupt-cache fallback, and asserts GA plus effect-source, panic-coverage, and Global-permission axis counters. These expanded controls have not been run against a fresh Stage1 product. Both available products checked—the default `bin/elisac-stage1` and `build/goal-compiler-latest-b11e/bin/elisac-stage1`—report provenance schema `elisa-stage1-provenance-v1`, while the current checker requires v5. A fresh seed attempt using a Stage0 binary rebuilt from the current dirty Go tree (SHA-256 `83d2e903…91bb2`) with a 12 GiB guard exited 1 during semantic analysis; its log contains 97 located non-warning diagnostics and 32,078 warning rows (`/tmp/elisa-incremental-current-seed.log`). It did not produce a current Stage1 binary. This narrow checker-work reduction is not an end-to-end performance result.

Gate W later seeded the frozen compiler source at HEAD `423420b143cb59babaff6659b5d178470c34eaf9`
with clean Core HEAD `cbaa661924bc481c8769c9cdd1d6906e9819d87e` and Stage0 binary SHA-256
`de9801afab1c61a487fdd44aa13ef9565d3581b0ac6ccb212bb97166a63fb068`. Its snapshot manifest
records 6,413 tracked paths and a source-tree match at freeze. Stage0 exited 1 before creating
`elisac_stage1.o`; the log has 25,398 warnings and 113 non-warning diagnostics
(`/private/tmp/elisa-stage1-source-snapshot-20261018-gate-W.log`). The machine-parser borrow
diagnostics present in Gate V are absent in W, but V used a different Stage0 revision, so the
count change is not a controlled source-only comparison. Gate W produces no Stage1 runtime or
incremental-reuse qualification.

Gate X used the same Core HEAD and Stage0 binary as W, with a different frozen compiler source
snapshot (tracked working-diff SHA-256 `fe2b695993f0a4233b25c3b7b68e8d5b5119a33d2cbf35267876fea1c2bd3009`).
It also exited 1 without producing Stage1 and reported 25,398 warnings and 114 non-warning
diagnostics. The broadened request-region signatures did not clear the resolver lifetime
cluster; the 11 `resolve_expr_walk` argument-6 errors and the related `resolve_flow`, `resolve`,
and `semantic_api` errors remain. Gate X added a region-binding mismatch at
`driver/elisac_source_probes.elisa:285`, where the `request` region is bound to both `borrow`
and `request`. This is a useful same-bootstrap comparison with W, but X also changes the EASM
proof source and still provides no Stage1 or incremental runtime qualification. The live source
has since changed `run_semantic_gate_with_lookup_context` to bind its context to `@request`,
matching the Semantic API; Gate X predates this wrapper correction, which Gate Y later checks
against the matching signatures.

Gate Y froze compiler HEAD `a350f7f87559e2192ad20a9100398e1ccb92c1ac` with tracked working-diff
SHA-256 `7c2a5d21812a6d2934453bde0452063b644d05294fbc54e13685342d85b679ef`; the frozen `src/`
matched the live tree at freeze. It used clean Core HEAD `cbaa661924bc481c8769c9cdd1d6906e9819d87e`
and Stage0 SHA-256 `de9801afab1c61a487fdd44aa13ef9565d3581b0ac6ccb212bb97166a63fb068`. Stage0
exited 1 and produced no Stage1 object. The original log was overwritten by a duplicate seed
refusal and contained 84 NUL bytes, so the owners repeated the same frozen inputs with a separate
StoreScan trace log. That clean rerun also exited 1 without an object and contained 25,398 warning
lines and 111 non-warning diagnostic headers. The source-probe `request`/`borrow` mismatch from X
is absent. The clean trace has 43 broad `call may store` reports; 14 use the function-local-
reference wording. Thirteen resolver reports are formal-6 cases: `from=3` is a local
`darray[sview]` lexical-binding array (11 in `resolve_expr_walk`, one in `resolve_flow`, one in
`resolve`), while `from=1` and `from=2` are not local. The separate `semantic_api` report is
formal 22 from a stack `SymbolTable`. Core emits these diagnostics through its Go
`queueCallArgumentStoreChecks` / `returnBorrowCallArgStoreFlow` path. The trace identifies the
source argument but stops at the direct `AddrOfExpr`; it does not yet prove the internal StoreFlow
summary edge. A six-formal reproducer is structural evidence, not yet a source-matched explanation
of that edge. The separate `STORESCAN`/`CHAIN` rows at `key.reserve` come from Core's
`region_struct_target_store_scan` analysis and must not be treated as proof for the
`LOCALSTORE` diagnostics. A W-to-Y multiset comparison keyed by relative source path and full
diagnostic message, ignoring line/column spans, found 109 common non-warning records, four W-only
and two Y-only. The four
removed are the `driver/project.elisa` start-trim postcondition, loop-decreases warning, and two
loop invariants; the two added are the `bytes_trim_end_from` postcondition and an
`backend/easm_operand_scan.elisa` `scan_instruction` postcondition. Exact path/span/message
multiset comparison instead yields 102 common, 11 W-only, and 9 Y-only records because some EASM
diagnostics moved; comparing unique exact keys yields 96 common, 9 W-only, and 6 Y-only.
The grouped comparison describes message-level changes, not one-to-one span correspondence. The
assoc-index wrapper also had one invariant and two postcondition failures.
Neither Y run qualifies semantic reuse or runtime parity because neither produced a Stage1
compiler. The clean trace rerun uses the same pre-fix Core Stage0 and is diagnostic evidence only.
The unresolved formal-6 StoreFlow reports later prompted Core commit `1366c770`, which suppressed
scalar DArray push flows using the resolved argument type. Review found that pointer-to-integer
casts can preserve address provenance, including through scalar locals and helper returns whose
StoreFlow summary currently drops scalar return edges. An expression-independence WIP narrowed
the direct case but did not cover those paths, so Core commit `e97b9983` withdrew the shortcut;
`region_store_flow_summary.go` now matches the prior Core baseline `cbaa6619`. The restored-source
focused StoreFlow/StoreScan controls passed in 0.545 seconds. These are Core-only results and do
not resolve Gate Y's diagnostics or qualify a Stage1 build or incremental speedup.
Core `b5df0720` now has an uncommitted reserve-specific StoreFlow summary path and a new focused
test. At this snapshot the handling is not yet propagated through the other retention consumers:
local view provenance, filled-value analysis, struct-target scanning, parameter-write scanning,
and StoreFlow edge-kind analysis still classify `reserve` through the broad
`containerGrowthMethods` set. That set also drives allocation/region inference, where reserve must
remain a growth operation, so retention analysis needs its own operation-specific payload
classification and direct scanner controls. This review does not attribute Gate Y's `LOCALSTORE`
reports to those separate analyses. The builtin implementation validates reserve's sole argument
as `usize`, returns the receiver, and invalidates receiver-derived views; this supports excluding
capacity from retained payload while preserving receiver mutation. A separate repro checkout is
testing StoreScan/local-provenance behavior for the `name`→`key` `RAISE`/`CHAIN` path. It is not the
current Core working tree. Its six focused reserve/alias tests pass as structural checks, but its
synthetic helper-return test injects handled return names rather than exercising the full callee
summary; cross-function scalar-formal address provenance remains open. Keep that scalar-push
optimization unpromoted. Neither candidate yet has a source-matched Stage1 qualification.
After the freeze, the live `semantic/assoc_index_bound_marker.elisa` removed three ghost
postconditions present in Gate Y and changed the scan body; its proof checker has since been
updated in the live worktree, but that updated proof has not been run against a current compiler.
The `driver/project.elisa` trim loops also changed after Gate Y, and
`check_project_whitespace.py` was updated to follow them; that proof control likewise has not
been run against a current compiler.
The live `semantic/linear_checked_arithmetic.elisa` source and its proof fixture also changed, as
did `driver/wasm_abi_type_classification.elisa`, `semantic/view_return_origins_sorted.elisa`, and
`backend/easm_model.elisa` with their proof controls. The separately named `storeflow-patched`
snapshot's
`GATE-V-MANIFEST.json` pins compiler HEAD `423420b1` and overlays only
`parser_stmt_when.elisa`, `incremental_function_facts.elisa`, and `resolve_expr_walk.elisa` from
the live-vs-Gate-U delta. Its supplemental `snapshot.manifest` is stale Gate Y metadata. A direct
comparison shows the snapshot still differs from live `src/` in these five files. The old seed
attempt used Core `1366c770` (Stage0 SHA-256 `35af8e93bc6942f0310c59af3739bb527a5d5c896bb6b2d2b9ffb9c276b9dc6d`)
but terminated with status 143 (signal 15), emitting no diagnostics and no object. It is not a
current-source gate. Gate Y and its trace rerun also do not cover these current inputs.
The installed Stage0 at `/Users/torarinvikbjarko/Documents/Coding Projects/Go projects/Elisa-core/compiler/bin/elisac`
is a clean build of Core `e97b9983`, SHA-256
`7b3333859c1ed4fc8acb1eb46390e9995aab1f3fcd80175f3c79452243d42faf`. Core has since advanced to
merge commit `b5df0720` and then commit `0c3a8062`, which adds the reserve-specific StoreFlow
summary handling and regression. The installed e97 Stage0 binary does not represent that source.
A candidate was built at `/private/tmp/elisac-core-storeflow-reserve-current` from b5df plus the
reserve working diff (SHA-256 `a00b9417b94397cad09330da872589e13ba83e3aef9df063076ea279ef021737`),
with `vcs.modified=true`; its binary SHA-256 is
`6abed96431e437f9401a2804f043fb45c196d61b5af9229df171e22f894aac4d`. The Core semantic suite
passed on that candidate (`ok elisacore/src/semantic 118.448s`). Core then committed the exact
reserve source/test as clean HEAD `0c3a8062`; both changed file hashes match the full-suite input
manifest. A Mach-O comparison reports that all file-backed sections match the clean committed
build except four metadata differences: the 59-byte Go build-ID prefix in `__text`, 63 bytes in
`__rodata`, 64 bytes in `__go_buildinfo`, and one byte in `__data` for the `runtime.modinfo` string
length. The reserve functions' disassembly matches. Keep the dirty-tree VCS provenance explicit;
the binaries are not byte-identical. A clean committed Stage0 is available at `compiler/bin/elisac`, SHA-256
`0cc10df1e515ededcf3b85914620a8f0ec7d7899d6220e4c7c44e87ddf2859aa` (`vcs.modified=false`), while
the failed 515ac seed described below used the earlier `6abed964…` candidate binary.

The source-matched-at-launch Stage1 seed ran from
`/private/tmp/elisa-stage1-live-515ac-20261018-1025`. At launch, its 1,087-file `src/` and the
`elisacore_std/` tree matched live exactly. The exact content fingerprints from
`scripts/stage1_provenance.py inputs` matched between snapshot and live at launch: source tree
`c4f0ecbbdc8120c0b48edc9d0f7d835e6bb0dfa13b03453f0ad149255ef792fe`, build recipes
`a8a727f09ebdab279c1cde7d2b62e1226ff1a57c4d17484d880adc9383c44bba`, and source-stat fingerprint
`eb3c1fde3cd60fd01f0d8781f7b4b64e0f9e3a7e1d5d0561cbe007307a0e0864`. The run used LLVM/Clang
23.1.3 with clang SHA-256
`efdad95de9f1ee4863117fd89a89bdb1a2389298a6d3c444e042aadf92d95448`. An independent tree
inventory found 1,087 source files and 45 standard-library files with empty `diff -qr` at launch.
This snapshot has package metadata but no `GATE-V-MANIFEST.json`. The run later failed with status
1 and produced no Stage1 object. Its log contains 25,510
located records: 25,398 explicit warning rows, 30 proof-lint notices (28 invariants and two
loop-decreases), and 82 hard diagnostics (31 lifetime-store rows, 50 ensure-postcondition failures,
and one ghost-purity error). The 31 lifetime rows comprise 29 `call may store` errors and two
direct longer-lived-store errors. The 50 ensure failures include 40 in dirty files: 18
`linear_mul_safe`, nine EASM compose-span, five view-origin swap, five project trim, two EASM label
index, and one Wasm classification; the other ten are in untouched files. This is source
correlation, not a clean-baseline comparison. It has no resolver lookup-context
formal-6 report and no prior `semantic_api` formal-22 report; remaining lifetime reports include
`resolve.elisa:147` argument 2 and `semantic_api.elisa:867` argument 2. This is consistent with the
reserve-capacity false edge being absent, but does not prove causality: there is no same-source
unpatched baseline or exact resolver StoreFlow `(1,3)` / wrapper `(2,5)` summary. A located-record
multiset comparison with Gate Y reports 91 common, 20 Gate-Y-only, and 21 current-only
records. Gate-Y-only includes 14 local-store reports, two assoc-index postconditions, and one EASM
scan postcondition; current-only includes 16 linear-arithmetic postconditions and five view-origin
diagnostics. Gate-Y-only assoc-index failures and the current run's assoc-index diagnostics are
unqualified against the latest two assoc-index source edits; the parser diagnostic is likewise
stale against the scalar-parser commit. Other independent proof blockers include `project.elisa:202/221`, repeated
`linear_mul_safe` postconditions, `wasm_abi_type_classification.elisa`'s `classify` postcondition,
and the view-origin reference-swap/ghost-helper checks. These are not StoreFlow evidence. This is
not a controlled A/B: the Stage1 sources and Core bootstrap differ. Later live-tree comparisons
became unstable while other agents edited the checkout, so use the frozen source fingerprint for
this run and do not treat a point-in-time `diff -qr` list as the current mismatch set. A parser
edit after launch contributes one non-warning diagnostic, so the run qualifies only the frozen
pre-parser-fix snapshot's failed seed, not the latest live source. With no object, it also provides
no current Stage1 IR, assembly, runtime, or incremental qualification. The live
`check_project_whitespace.py` checker was updated for the post-Gate-Y trim loops, but its proof
control has not been run against a current compiler.

A separate seed, `/private/tmp/elisa-stage1-live-f54f-20261018-1035`, used the clean installed
Stage0 SHA-256 `0cc10df1e515ededcf3b85914620a8f0ec7d7899d6220e4c7c44e87ddf2859aa` and a frozen
`src/` plus `elisacore_std/` content fingerprint of
`9b4a82364500024f27396485ec90739bd1391ea16246db67aed9147c9b31106d`. It finished with status 1,
log SHA-256 `781015b229ec083660ba423ac8ad7042c934c594240788f6c1b527204a2f92b7`, and no object.
The 25,509 located rows comprise 25,398 ordinary warnings, 29 proof-lint notices (27 invariant
fallbacks and two loop-decreases), and 82 hard diagnostics (29 call-may-store lifetime errors, two
direct longer-lived-store errors, 50 ensure-postcondition failures, and one ghost-purity error).
Compared with the 515ac log by normalized path and message, 109 diagnostics are common, three are
old-only, and two are new-only; the parser scalar-step proof is cleared, while the updated
assoc-index scope proof still fails. Relative to the copied f54f source, 26 of the 50 ensure
failures are in four changed files (18 linear arithmetic, five view-origin, two EASM model, one
WASM ABI classification); the other 24 ensure failures and all 31 lifetime-store errors are in
source files identical to live at that comparison. These are source correlations across distinct
Core/source snapshots, not causal evidence for the reserve change.
The single ghost-purity error at `view_return_origins_sorted.elisa:35` comes from body assertions in
the frozen snapshot that were later removed in favor of an ensures relation. Thus 27 hard rows map
to changed source (26 ensures plus that ghost error); the other 55 are in files identical to live
at that comparison.
This is a distinct run from the failed 515ac seed above. Concurrent edits made live-source
comparisons unstable; at one later comparison, checkout hash `ef0ec9606e12a9930b68263eb851c9056cc68c209b960971e6e01e4511936ae3` differed in five source files, including `incremental_function_facts.elisa` with the new clone/reanchor spans. Bind this failed result and its 10-second phase sample only to the frozen fingerprint and Stage0 binary, not to current-source behavior or timing of the new spans.

A later validation run at `/private/tmp/elisa-stage1-live-f54f-current-20261018-1045` used frozen
reported frozen-input identifier `1aaa6e778e2fdc78465c89456c9a4a974f5ce9eed75099af8ed851ea341ad7c8` and the same
clean Stage0 SHA. The snapshot contains clone/reanchor spans but predates sidecar spans. A later
live comparison found two tracked source differences, both limited to timing instrumentation:
`elisac_incremental_cache.elisa` adds sidecar spans and `incremental_function_facts.elisa` removes
redundant effect annotations from clone/reanchor timer calls. The seed failed with status 1, log SHA-256
`53213c914ce021f70bebf2f6d96ca901357f102602f2863b52dd02fecf9cc7b2`, and no object. Its 25,491
located rows comprise 25,402 ordinary warnings (including four redundant `can Global{Read,Write}`
warnings on timer calls), 29 proof-lint notices (27 invariants and two loop-decreases), and 60 hard
diagnostics (31 lifetime-store errors and 29 ensure-postcondition failures). Compared with the
1035 run, ensure failures fell from 50 to 29 and the ghost-purity failure cleared: 16 resolved in
linear arithmetic, four in view-origin ordering, and one in WASM ABI classification. All 31
lifetime-store errors remained in unchanged source files. The two
`check_never_leak_threading_walk:118` and `semantic_api:867` lifetime errors remain. `ELISA_STAGE1_TIMINGS`
was unset on wrapper and compiler, so this run cannot report clone/reanchor span values; it is a
separate proof/source validation, not a timing run. The 29 remaining ensures are nine EASM compose,
five project trim, two each in EASM model, linear arithmetic, assoc-index scope, iterator alias,
and ownership lookup, plus one each in declaration-name position, reference-initializer typestate,
assoc-index bounds, view-origin ordering, and ownership flow. The four redundant timer-effect
warnings were removed from the live clone/reanchor calls after this run; that cleanup was not
validated by this snapshot.

A separate Stage1 retry used candidate Stage0 binary SHA-256
`b92221eb76e98f1e47b7f0f14659ffb8c1ee8f4da5390046b22afc591a2484c9`, built from detached Core
HEAD `cbaa661924bc481c8769c9cdd1d6906e9819d87e` plus a tracked diff (SHA-256
`cf73f04da2a67434c49d3cae7b0b8b2e3859f52bdc18663ad5c055e72af4ec9d`) and four untracked repro
tests (aggregate dirty-tree fingerprint `95a845f82975d2452ae8b432d7d0fad75d06abc6c8bb87ec4f10f812c6e712ac`).
It is a combined dirty WIP, not a single-change build. The input was the same reported
frozen-input identifier `1aaa6e778e2fdc78465c89456c9a4a974f5ce9eed75099af8ed851ea341ad7c8`
used above, not the current live Stage1 tree. The candidate run failed with status 1 and produced
no object. Its log is `/private/tmp/elisa-stage1-candidate-seed-20261018.log`, SHA-256
`4b073ca57045369277f3c0bb6560a9d9b3bad1e0dccbf975951eae1e96e667e8`. The exact tally is 25,510
located headers: 25,404 warnings by severity (25,402 `warning:` rows plus two unprefixed timer
effect diagnostics classified as warnings), 27 invariant fallback notices, two loop-decrease
fallback notices, and 77 hard diagnostics (27 ensure failures and 50 StoreFlow/lifetime reports).
The two timer calls at `elisac_incremental_cache.elisa:262` and `:266` report missing
`can[Global]` facts but are warning-level in this run. Against the installed clean Stage0 run on the
same frozen Stage1 input, hard rows changed from 60 to 77: StoreFlow/lifetime reports rose from 31
to 50, ensure failures fell from 29 to 27, and the two timer warnings were new. The raw `call may store` count rose from 29 to 45; the new set also
includes local-reference reports in `resolve_expr_walk.elisa`, `resolve_flow.elisa`, `resolve.elisa`,
and `semantic_api.elisa`, plus region-value reports in `check_readonly_ref.elisa` and
`check_call_argument_exclusivity_refs.elisa`. Static follow-up suggests the 14 new local-reference
reports concern a request-local lookup context passed synchronously through resolver helpers, with
no observed storage into the symbol table or session snapshot; they may be a no-escape summary
false positive, but this needs code-path confirmation. The two region-value reports are separate
and still need triage. Source review found the exclusivity helper has no current call sites and
returns neither local accumulator; the readonly checker passes a local `SymbolTable` through a
synchronous recursive walk and returns no table. These also look like possible no-escape false
positives around mutable out-parameters, pending confirmation against the candidate StoreFlow
summary. Three additional candidate-only reports say values escape an `in auto:` scope
in `check_borrow_after_move.elisa:1272`, `:1277`, and `:1278`; the two direct longer-lived-region
store rows in `check_global_permissions.elisa` are present in both runs. Thus the net StoreFlow/lifetime
increase is 16 new call-store rows plus three new scope-escape rows, not a change to those two
existing direct stores. The diagnostic delta alone does not establish whether the new reports are
soundness gains or regressions. The two assoc-index-scope ensure failures absent from the candidate
output were still present in the frozen source, so this is changed proof behavior from the combined
Core WIP, not validation of a Stage1 source fix. The live Stage1 tree has since changed three files
(`assoc_index_bound_marker.elisa`, `assoc_index_impl_scope.elisa`, and
`linear_checked_arithmetic.elisa`); this run does not cover those edits. The live tree also gained
explicit timer grants after this candidate snapshot; the later clean-Stage0 seed below includes
them, though it failed on other proof diagnostics. The
candidate's enclosing driver function already carries global effects and neighboring timer calls
are accepted; a branch-local effect-fact issue is another possible explanation for the two missing
local grants, so the diagnostic does not establish the root cause. A later clean-Stage0 seed below
includes the explicit grants and reports no hard `can[Global]` failures at those sites, though it
still reports ordinary effect warnings for `Abort`, `Memory`, and `Unsafe`; the broader seed failed
and does not establish a complete fix. No timing environment was enabled, and the failed candidate
seed provides no Stage1 artifact, parity, or incremental-performance qualification.

A subsequent installed-clean-Stage0 run used the seed owner's launch-time combined `src` plus
`elisacore_std` fingerprint `18b864939acc553e997670dd9c3fd97e5877a7ad1f8f17a32043dbefad1f41c5`
(1,132 files). It used the same Stage0 SHA above and the timer-grant and three assoc/arithmetic
edits reported present at launch. The owner says the later `backend/easm_compose_text.elisa`
named-local rewrite postdates this seed. The scratch path was reused and changed after the run, so
the reported launch fingerprint is the source identity; rehashing its current contents or comparing
them with the current checkout does not establish the compiled bytes.
The run failed with status 1, produced no Stage1 object, and wrote
`/private/tmp/elisa-stage1-source-fixes-seed-20261018.log` (SHA-256
`17182d484f985ad9b63ea527251a800f48d195c000edc25ed8d9b933aa5aa1c2`). Its 25,492 located rows
are 25,402 warnings, 27 invariant fallback notices, two loop-decrease fallback notices, and 61 hard
diagnostics: 30 failed ensures and 31 lifetime/store reports (29 `call may store` rows and two
direct stores at `check_global_permissions.elisa:336` and `:349`). The two candidate missing-
`can[Global]` warnings are absent; warnings for other effects at the timer calls remain. The
`line_is_impl_scope_from` ensures absent in the combined-Core candidate output are also absent here.
A normalized comparison with the old 1045 log shows its two `linear_mul_safe` ensures at lines 62/63
are absent, but four ensures at lines 47, 50, 66, and 67 plus an `easm_operand_scan.elisa:537`
ensure appear. The earlier scratch source directory was reused and later changed, so this raw log
comparison is triage only, not a controlled source attribution. Use the seed owner's launch-time
combined fingerprint rather than rehashing the reused scratch path: a later inspection found the
directory had changed, and its present
contents do not prove the exact bytes compiled. The run also predates a later live edit to
`backend/easm_compose_text.elisa`; its nine `easm_compose_span` ensure failures do not validate that
new assertion form. This remains a failed proof seed, not Stage1 object, parity, or incremental-speed
qualification.

3a. **Replay one dependency fact.** Current-source-only direct-call records may replace a supported caller's Global-authority inference walk after ordinary global lookup misses and every target resolves uniquely against the fresh function index. Keep report walks and cold fallback. Add warm/cold controls for callee `Global.Read`/`Global.Write` changes, body relocation, and ambiguous target invalidation before widening eligibility.
3b. **Use a trusted process-local semantic session.** The driver’s
`run_semantic_gate_incremental_with_session` accepts an opaque
`Semantic::IncrementalSemanticSession` created by Semantic. Its private state stores
exact analyzed bytes, the complete serialized source/include graph identity, exact
options, input phase, semantic version, and a size-bounded typed snapshot validated
when it enters the session. Exact-input hits deep-copy the private facts and rebuild
source anchors from the fresh parse before skipping the fact collector. For body
edits within the same graph and options, the collector reads the private prior
snapshot directly, compares an exact declaration surface that retains function
headers, and reuses facts only for bodies with identical token streams; changed or
unsupported bodies are scanned. The binary snapshot codec remains the disk-sidecar
format. The report uses `prior=session` and `session=edit` when this path reuses a
body, while exact-input hits report `session=hit`.

The opt-in `elisac-stage1 semantic-session SOURCE` host retains one session across
`check` requests and reparses the source on each request. Each process is tied to
one source path and fixed environment options; callers start another host when
either changes. The opaque session and one reusable process-owned line-map buffer
outlive a request. The driver now opens `request_scratch` around source
processing, but parser/AST payloads and parser names remain typed in global
`@source`. The current Stage1 seed rejects request-region arguments at parser
calls, so this wrapper has not established per-request reclamation. The source
and name allocation lifetime remains unqualified until the parser representation
and API accept that boundary.
`test/parity/incremental_semantic_session_control.sh` exercises the protocol through
the Stage1 wrapper, including repeated requests and an edit that introduces then
removes a semantic error. A fresh Stage1 run is still needed to qualify session
reuse; this control has no RSS or allocator-growth bound, and request-region
reclamation is not yet implemented. The ordinary compiler entry continues to call
the session-disabled wrapper. Persisted sidecars still take
the current-source collector path because they are untrusted. Keep diagnostics on
the normal current-source path until a separate location-rebinding result format is
proven. The session stores only owned portable facts and grants, never AST,
SymbolTable, line-map, or LLVM handles. It keeps one bounded translation-unit
entry; changed admission inputs or invalid private snapshots clear it and run cold.

An exact session hit currently calls `ifc_clone_session_snapshot` before testing
whether source bytes match, then `incremental_reanchor_exact_snapshot` scans
declaration/token spans and mutates request anchors, reuse flags, and counters.
Simply moving the equality check ahead of the clone would expose session-owned
facts to those mutations. Source review narrows the split: reanchor reads retained
`bytes`, `direct_facts`, and `active_grants`, while it writes current anchors,
matched/reuse counters, `functions[*].matched_previous`, and
`self_assignment_ranges[*].reused_previous/complete`. A safe no-op optimization
can share immutable pools and move only these mutable fields into a request-local
overlay, or copy just mutable record/range metadata. Changed-source requests also
look eligible to read a retained snapshot directly: a static alias/lifetime audit
found no mutation counterexample, and the collector receives `prior` read-only
while building the replacement separately. Removing that clone still needs a
borrowed-view implementation that pins the session snapshot until collection
finishes; make the clone source parameter immutable as part of that change. The
live source now times clone and exact reanchor
separately, though the clone span includes non-exact prior-snapshot requests and
the spans have no matched profile yet. Add copy-byte/record counts and compare
complete cold/warm results; hold the session snapshot stable until semantic replay
ends and take the cold path on invalid self-assignment data. Every request still
lexes and parses the whole file, so the current host validates the trusted session
boundary but does not yet prove low-cost unchanged checks or edit-to-executable
speedups.

There is another no-op cost when the same driver request also enables a disk
cache through `ELISA_STAGE1_INCREMENTAL_CACHE_DIR`: `elisac_incremental_cache.elisa` admits the cache path before session
lookup, then its common tail re-encodes the snapshot and atomically writes the
sidecar even when `session_hit` is true. Live source now times serialization and
publication separately with `incremental-sidecar-encode` and
`incremental-sidecar-write`; both f54f snapshots predate these spans, so they have no
source-matched timings yet. A future skip must be conditional on a
known successful publication for the same path and content identity; set that
marker only after atomic publication succeeds. Cold starts, edits, and missing or
invalid sidecars still need publication. If a warm hit skips writing, preserve the
meaning of the existing `published=yes` report and add a separate skip/reuse
counter. Measure session-only and session-plus-sidecar modes separately, and
verify a fresh process can load the sidecar after repeated warm checks.

The ordinary `main` path consumes one request and returns. The semantic-session
and compile-session hosts open request regions around source processing;
compile-session also starts a fresh semantic-session region after 32 requests.
However, the parser API, AST payloads, and parser name store still declare
source-backed data in global `@source`, and the current exact-source Stage1 seed
reports request-region arguments rejected at parser call sites. These wrappers
alone therefore do not prove that a full parse generation is reclaimed. A
passing source-matched lifetime check and repeated-edit memory control are
required to establish which buffers die at request end and which remain
process-lived. Both hosts publish the new map into a reusable process-owned
lexer buffer. The semantic host calls
`PhaseTimer::request_start` and marks each completed check so semantic timing rows
exclude idle time between edits. Other process globals still need lifecycle review.

4. **Prove invalidation.** Compare warm incremental output byte-for-byte with cold output for: unchanged build; a body-only edit with unchanged API; a callee body edit that adds/removes `Global.Read` or `Global.Write`; a callee effect-contract change; adding an overload after a previous lookup; changing an import or alias that resolves a previous miss; changing a global from immutable to mutable or changing its type/layout; changing a protocol method contract/conformance; changing strict/global options; and corrupting or versioning out the cache.
5. **Add body codegen fragments.** Cache and restore eligible `-O0` LLVM function bodies in a newly created module, then test link validity, object/executable parity, and invalidation for function API, type/global layout, callee ABI, target, and codegen flags.
6. **Expand eligibility and optimization.** Add callback/generic/debug support only with explicit fingerprints and controls. Consider cross-function optimized reuse only with an import/summary model and runtime parity evidence.

The semantic MVP passes only when warm and cold diagnostics, canonical effect rows, exit status, and source locations match exactly; a body-only edit demonstrably visits only changed/unsupported bodies in the paired passes; and edits to a dependency cause all required affected call checks to rerun. The codegen MVP additionally requires equivalent executable behavior and a valid verifier result after cached fragments are restored.

## Current production integration boundary

The driver supplies the exact source bytes and token stream that produced each AST,
plus a stable source-unit identity. For expanded `static generate` input, the AST,
source, and tokens come from the expanded frontend result; policy headers continue
to come from the original source. Early `pymodule` gates use the same pairing.
Without stable identity, the driver resets any session and runs the ordinary cold
semantic gate. An empty cache directory disables sidecars; a host that retains an
opaque session can still use the session-aware entry point. The opt-in
`semantic-session` and `compile-session` commands are persistent hosts;
`compile-session` keeps one authoritative source snapshot per epoch and resets it
when request identity changes. Ordinary one-shot compile commands remain stateless.

In ordinary one-shot CLI compilation, the session-disabled wrapper does not consume stored
facts as authority effects. It rescans each supported body from the current AST
and rebuilds current anchors; sidecar cacheability and fact counts cannot
authorize a skip. The driver also exposes a session-aware internal entry point
that accepts only the opaque Semantic-owned session type. Its session operation
decodes private state and can reuse trusted in-process facts after checking the
exact declaration surface and unchanged body tokens. The opt-in semantic-session
and compile-session hosts retain that session across requests; ordinary one-shot CLI
calls still use the disabled wrapper. A freshly scanned, cacheable zero-fact record can skip Global-authority walks,
effect-source scans, panic-coverage body scans, and Global-permission body-axis
collectors only at a unique top-level definition offset. Direct-call-only records
can also seed Global-authority inference after fresh target resolution.
Global-permission axes project direct facts for flat fact-bearing bodies without
local bindings. Collection still appends every function slot, then closes the
call graph and publishes rows. Panic coverage
still builds its annotation and concrete-wrapper indexes and traverses the
declaration tree. Local reference writes, nested blocks, parenthesized
expressions, duplicate anchors, and unsupported syntax stay cold. Global-authority
replay also stays cold for the whole unit when inline-grant annotations are present.
Ordinary one-shot CLI compilation still rescans every candidate body and recomputes semantic
diagnostics; it does not replay results. In the opt-in session host, only the
self-assignment linter currently replays complete rebound diagnostics; all other
semantic diagnostics are recomputed. The current serialized controls cover body edits, semantic-option
changes, a valid-checksum forged sidecar, and corrupt cache data, but the expanded
current-source skip and tighter eligibility need fresh parity qualification.
Dependency-change invalidation remains to be added before eligibility expands. The manual
`INCREMENTAL_SEMANTIC_ENGINE_VERSION` must be bumped whenever changes can alter
collector eligibility or the meaning of facts consumed by replay.

The current compile-session control has no global declarations, so
`check_global_permissions` exits before `gp_project_direct_facts`; it does not
exercise Global.Read/Write projection or direct-call effect closure. Add a separate
current-source parity case with a mutable-global read/write and a caller edge, and
compare cold/warm diagnostics plus canonical rows before treating those counters as
consumer coverage.

This trust policy sets a hard limit on sidecar reuse: exact body equality proves
that a cached record names the current body, but it does not prove that the
record's semantic observations are true. A checksum detects accidental damage;
it does not authenticate those observations. In the driver path, disk sidecars
therefore require current-source recollection before their facts can affect
checker behavior. The low-level checker bridges accept snapshots and have a
trusted-caller contract; the type system does not prevent other Semantic API
callers from passing decoded sidecar data to them. The current driver obeys this
contract. The opaque session API supplies a separate process-local provenance
boundary: only
Semantic can create or advance the session state, which stores facts emitted by
the current collector and checks exact options, include identity, declaration
surface, and body tokens before reusing them. That
boundary is exercised by the opt-in semantic-session and compile-session hosts,
but their protocol and request-lifetime behavior still need end-to-end controls. Ordinary one-shot CLI
compilation continues to recollect. Do not treat a body hash, schema check, or
structural validation alone as a substitute for session provenance.

### Typed semantic query graph status

`IncrementalSemanticSession` now contains a typed query graph with private key
lookup, exact-byte evaluate/commit, dependency replacement, and invalidation
operations in `src/semantic/incremental_function_facts.elisa`. Handles carry a
session cookie plus graph, request, and committed-context generations, so a handle
cannot be reused across a reset, graph clear, graph-using request, session, or
committed-context change. The exact-source collector fast path currently returns
before `begin_request` and does not touch the graph; any graph use on that path must
advance the request generation first. Evaluation
checks exact input bytes, the dependency set, dependency result generations, and
Green status; commit requires Green dependencies and publishes a query as Green
only after the canonical result and dependency edges are stored. A changed result
marks its reverse dependers potentially dirty, which can return to Green when their
dependency results are unchanged.

Evaluation checks only direct dependencies and requires them to be Green already.
Callers for a deeper graph must evaluate dependencies bottom-up; there is no recursive
try-mark-Green operation. Query keys, inputs, results, and dependency sets also need
complete, versioned serialization from any future semantic caller. The graph API does
not infer missing context from the current AST or symbol table.

This remains an unqualified private prototype, not a production query engine. The
session collector checks cached `SourceInput` and `FunctionBodyFacts` results. A body
query reuse for an ordinary body is attempted only after the trusted prior snapshot
proves an exact declaration surface, cacheable prior record, and exact body match.
The `complete_empty_body` exception and a successfully scanned prior zero-fact
record can reuse a graph query after the exact body match without trusted
whole-surface admission. A body hit decodes canonical query bytes into the current request snapshot, validating each fact against the
previous snapshot's typed facts before it bypasses the body walker.
For ordinary bodies, this query path is an overlay on the existing typed-snapshot
reuse: the graph lookup requires the same exact prior body/surface admission and
checks its decoded facts against the prior typed record; a graph miss falls back to
copying that same record under the same gate. It therefore does not yet demonstrate
additional body-fact extraction skipped versus graph-off. The `complete_empty_body`
syntax path skips collector scanning independently of the graph; the prior
zero-fact path also skips a scan using the successful typed record even when the
graph misses. Treat graph counters as routing/revalidation evidence until a
graph-only path demonstrates additional analysis work avoided.

A resolver `NameLookup` query is connected at `Expr.Ident` classification: the
driver reacquires a request context after collection, and the serial
declaration-resolution walk checks the cached `(known, module_only)` result before
scanning global symbol/member chains. Key
schema 2 stores only current module and exact name; input schema 4 packs six boolean
surface facts into one flags byte and stores only the two result-relevant counts:
non-module symbol count and member-row count. The total same-name symbol count is
omitted because the resolver classification does not read it. The logical input is
13 bytes (schema, flags, and two 32-bit counts); this source change still needs a
source-pinned build and parity validation. The session-local
graph resets when identity or options change. After declarations, aliases, imports, and region annotations
are collected, the first eligible unbound name-classification read lazily builds a
collision-safe exact-spelling surface index. Requests with no eligible reads skip the
O(import annotations + symbols + members + regions) pass; any request that reaches one
still pays that setup because the builder first reconstructs imported-module and
imported-member sets from the import annotations, then indexes the declaration surface.
The request context memoizes the build attempt, including failure, so unsupported
surfaces use the cold classifier without repeating the prepass. The input
records non-module symbol count and module-member row multiplicity; total same-name
`symbol_count` is omitted because neither classification formula reads it. It also
records module presence, imported visibility,
current-module membership, region-name presence, the `name_indexed` gate bit, and the
forced-builtin class. This preserves the existing visibility/count rule while giving
negative names stable all-zero surface facts. NameLookup has no `SourceInput` edge; the
SourceInput handle remains a request-generation guard. Unrelated declaration changes can
leave a name query green, while additions/removals, aliases, visibility, current-module,
and region changes update the matching input. The resolver checks lexical bindings before
querying; on a miss it passes that known local miss and the indexed region fact to the cold
classifier. If the index is unavailable or fails completeness checks, it skips the query
and uses the cold classifier, including its region-name scan. The ordinary
`resolve_declarations` wrapper uses a disabled context, so it remains on that path.
This input is complete for the current resolver because its symbol and module-member rows
come from the parsed expanded unit, while imports contribute visibility annotations and
aliases over rows already in that table; this path does not read an external module
interface. If interface summaries become resolver inputs, they must be explicit query
inputs or the lookup must fall back cold, since `SourceIdentity` records include paths and
edges rather than external-file contents. The surface-index changes have source review
only; no build, parity run, or benchmark has verified them.
This can reuse classification across body-only edits because the declaration surface
omits function bodies, while every declaration-surface change invalidates all these
name queries. The resolver still performs the indexed chain walk on misses.
For ordinary cacheable bodies, each `FunctionBodyFacts` node still depends on the
whole `SourceInput`, whose value includes the declaration surface and options. A
declaration change can therefore make those body queries non-green even when an
unrelated function body and its facts are unchanged. The same broad surface match
also gates prior-snapshot reuse for ordinary bodies; if the surface differs, the
collector cold-scans those candidates.

There are two source-independent body-fact cases, with different proofs. A
supported body containing exactly one `return` of an integer, float, string,
character, or boolean literal is marked `complete_empty_body` directly from its
AST shape, before the fact walker runs. Separately, a retained-session record may
be classified as a source-independent zero-fact body after a successful completed
fact scan has proved it cacheable with zero direct facts. Reusing that record requires the
current header to remain supported, the body bytes to match exactly, and the
prior fact span to be valid. This can cover a multi-statement literal-only body
or literal local declarations that do not have the closed `complete_empty_body`
shape. A zero fact count by itself is not the proof; an incomplete or rejected
walk cannot enter this class.

Both cases can reuse direct-fact results without a `SourceInput` dependency.
Only the prior `zero_fact_body` proof skips the broad declaration-surface gate
for a non-`complete_empty_body` body; a new body with no prior proof is scanned
on the ordinary path before its result can be published without that edge.
These shortcuts cover direct-fact collection only. Parsing, type checking,
diagnostics, and the normal semantic pipeline still run. The query graph has not
yet shown additional end-to-end body-work savings over the typed-snapshot path.

The next useful graph step for non-empty bodies is to record the actual name observations used by the fact
walker as dependencies, scoped to the canonical direct facts this syntax walk
emits. For `GlobalRead`/`GlobalWrite`, record mutable-global membership plus the
owner's local/binder shadowing; this walk does not inspect all-global presence on
that path. For zero-argument `DirectCall`s, capture resolver-visible shadowing
and candidate selection/eligibility, including imports, modules, extern/scoped
declarations, visibility, and added or removed names. The collector's local
`all_globals` and function-candidate arrays do not cover that complete lookup
surface, so they cannot alone authorize reuse. Preserve the builtin-versus-call
classification for `panic()`. These projections must come from a complete current
resolver lookup surface; otherwise retain the `SourceInput` dependency and
cold-scan. Semantic resolution and type checking still run on the current
AST/SymbolTable, so a signature change that does not alter walker eligibility or
direct-fact bytes need not invalidate this query. Preserve namespace-wide
dependencies where uniqueness or all-name enumeration matters, and the
whole-surface dependency as a conservative fallback whenever extraction is
incomplete or syntax is unsupported. Relax the broad surface gate only for an
exactly matched body record whose complete observed dependency set revalidates.
Retained-session controls should keep body bytes unchanged across these transitions
and compare cold/warm full diagnostics, canonical inferred rows, and body-reuse
versus-rescan counters: an unrelated declaration leaves the body green;
adding/removing a referenced global or call target invalidates only its users;
renaming an owner parameter so a fixed body identifier changes from local to
mutable-global resolution invalidates that fact; a referenced global changing
mutable→readonly→mutable invalidates and then restores the read fact; and adding or
removing a same-named global shadows or reveals a zero-argument call as the resolver
does. Include callee eligibility/effect-row changes as well as declaration-class
collisions in the call tests. The following is a proposed retained-session control;
the existing include-body unresolved-name transition in
`test/parity/incremental_semantic_session_control.sh` is narrower and does not
cover this callee/row/effect combination. Change a previously supported callee
to unsupported nested flow while adding a `Global` access and an ungranted
panic/effect call. Require cold/warm diagnostics and inferred-row parity, prove
an unaffected sibling remains reusable, and require the changed callee to take
the current-AST cold scan so no prior typed facts survive the eligibility
transition.
Do not persist request-local declaration IDs or handles in those dependencies.

`complete_empty_body` remains the first, closed AST-shape exception: one bare
`return` of a self-contained integer, float, string, character, or boolean
literal, with no local bindings, grants, calls, identifiers, or additional
statements. It is recognized before scanning. A separate retained-session path
uses the current scanner's successful prior result: the prior record must be
cacheable, its body must match byte-for-byte, its direct-fact count must be zero,
and its fact range must be in bounds. The current header must remain supported,
and the active session's semantic fingerprint, generated-input mode, options,
and identity must still match. This completed scan is the proof that the body
emitted no declaration-sensitive direct facts. It can include additional
literal-only statements or accepted literal local declarations. A current cold
scan can publish a cacheable zero-fact body without a `SourceInput` edge, but it
cannot authorize prior-record reuse until a later exact-body request. A bare zero
count without a successful cacheable scan and valid span never authorizes
an empty dependency set.

The scanner remains fail-closed: local/parameter identifier reads, declaration
lookups that are not represented by direct facts, unsupported syntax, and
incomplete scans stay non-cacheable and use the ordinary `SourceInput` path or
cold semantic fallback. Neither source-independent class caches type checking
or diagnostics. The `zero_fact_body_*` report counters describe collector-side
proof, restore, and publication routing separately from `complete_empty_body_*`;
if final declaration-surface projection fails, the collector invalidates all
body records and suppresses graph publication even if an earlier scan or restore
count was recorded.

For the current collector, keep the first dependency manifest scoped to observations
from bodies that are already cacheable. `ifc_walk_expr` rejects absent/readonly
globals, owner-local-shadowed names, ambiguous calls, and unsupported call targets,
so those bodies already take the cold path; negative/ambiguous lookup edges are
needed only if a later change broadens eligibility. Include the current owner
parameter/local-shadowing projection for each recorded identifier or zero-argument
call: adding a parameter with the same spelling can change whether the walker emits
a global fact while the global's own projection stays identical. The body query key
is currently path plus function name, so add the owner's current eligibility result
and ordered parameter/binder names before relaxing the whole-surface admission gate.
Eligibility depends on unique-name status, alias-aware return-type support,
defaults, generic/inline-grant status, and valid source spans; encode these observed
facts canonically rather than relying on raw header text alone. The current
uniqueness check only rejects duplicate top-level `Decl.Func` names; it does not
establish uniqueness against resolver-visible extern, nested/module/scoped, or
imported candidates. Keep such calls cold until the current callable-resolution
inventory is complete, and add same-name collision tests across those declaration
forms. Collect or precompute the
complete body dependency set before query evaluation; later resolver `NameLookup`
hits cannot validate an earlier body-fact query. If extraction is incomplete or
over budget, retain `SourceInput` and cold-scan.

Projection precision matters when this manifest is implemented. For this walker's
`GlobalRead`/`GlobalWrite` observations, `ifc_walk_expr` checks owner locals and then
membership in `mutable_globals`; it does not consult `all_globals` on that path.
Therefore the minimum global projection for those facts is mutable-global membership
plus the owner's parameter/local-shadowing context. Keep a separate `all_globals`
shadow check and exact candidate multiplicity/eligibility projection for `DirectCall`
resolution. Adding `all_globals` presence to every global-read projection would be
sound but would invalidate bodies on declaration changes the walker does not observe.
The current candidate census only enumerates top-level `Decl.Func` and global
`Decl.Const`; it does not by itself represent resolver-visible `Decl.Import`,
`Decl.Module`, `Decl.Scoped`, or `Decl.Extern` names. Do not let a
`DirectCall` context turn green from those local arrays alone unless resolution
rules prove the omitted declaration forms cannot affect selection. Include their
current visibility/uniqueness effects in the canonical projection, or retain the
whole-surface/cold path. Add same-name add/remove controls for each declaration form.
An unchanged import line also does not prove that its provider's contents stayed
the same. A `DirectCall` through an imported/module provider needs that provider's
stable identity and revision/content in the context, or a current resolver-visible
callable projection; if neither is available during collection, keep that call cold.

Graph reuse must also refresh saved projections, not merely rebind old dependency
IDs: dependency checks validate edge status and result generations but do not
recompute a name query's input against the current translation unit. Persist a
bounded, validated prior edge manifest, reevaluate each referenced name/call
projection in the current request, then pass those current handles to the body
query. On a body miss, rescan it and commit the replacement dependency set.
Malformed edges, cap overflow, unsupported projections, or incomplete extraction
must cold-scan (and poison the graph if required) before publication.

To limit dependency-edge fan-out, an alternative is one per-body
`FunctionFactContext` query. Build its canonical input from the validated prior
fact manifest, the current projection for each observed fact, owner eligibility,
and the owner's parameter/binder names; evaluate it before `FunctionBodyFacts`,
which depends on that single context node. Unrelated declarations then leave the
context bytes unchanged, while a changed observed projection dirties the body
through the reverse edge. Keep exact length-delimited bytes and collision-safe
equality. On a body miss, cold-scan and publish the refreshed context and fact
result together. This still requires a complete current changed/removed-name
manifest from the compiler adapter; the generic frame/catalog layer cannot infer
omitted declarations or attest that its enumeration is complete.
When a stable function key becomes ineligible because its body or header changed,
do not skip context publication while leaving the old context node Green. Commit a
canonical ineligible context result for that key, or explicitly stale the prior
context/body node before skipping publication, so a later request cannot reuse
facts from the previously eligible version. Stage current context bytes during
collection and publish only after the replacement snapshot stores successfully.
A fresh session or sidecar without a complete validated prior manifest must take
the cold scan; it cannot infer context equality from old fact record offsets alone.
Collection and publication must use the same dependency set. The current publisher
uses `[SourceInput]` for ordinary cacheable bodies and no dependency for
`complete_empty_body` or a successfully scanned zero-fact body; its request-local
hit marker records that dependency mode. Validation checks the source result
generation for ordinary bodies and requires zero dependencies for either
source-independent case. All currently publishable records still require valid,
bounds-checked declaration-surface metadata. As additional dependency classes are
added, carry their validated classification through the request snapshot or
recompute it from the same complete manifest at publication, and assert the
committed edge set in a control. Prefer one deterministic dependency builder for
collection-time evaluation and post-store publication; retain request-local
projection evidence separately from handles, then reacquire handles under the
committed graph generation.

That broader dependency-policy mechanism remains future work. The
`complete_empty_body` and scanner-proven zero-fact exceptions can be collected
without an admitted `SourceInput` and published without that edge, even when the
encoded source value exceeds its per-value cap. They still require valid
declaration-surface metadata and spans; ordinary bodies remain gated by the
`SourceInput` path. A source-value cap miss alone no longer prevents these
source-independent nodes from publishing or requires a graph clear. Keep
predictable misses for future context queries local; clear and rebuild only for
actual aggregate-capacity or structural failures.

Query-value capacity is part of this dependency policy. A valid source surface
whose `SourceInput` key or value exceeds its cap must still allow a fitting
context-only body query to publish; an invalid surface keeps its body records
ineligible. Treat predictable admission misses separately from graph-capacity
failures so an over-cap `SourceInput` preflight does not clear unrelated query
nodes and retry the same miss. After an actual graph clear, preserve or recompute
each owner's dependency policy and reacquire handles in the new generation; the
old validated-hit marker cannot authorize publication across that generation
change. If publishing one owner's context itself fails its key, value, or edge
budget, retry the committed snapshot once after the clear with the same per-owner
policy. Clear and stop if the rebuilt working set still exceeds graph capacity.
A fallback for one owner to `SourceInput` is an optional optimization when the
failure is known to come from its context and the source dependency fits; leave
that owner unpublished when neither dependency fits. Add retained-session
controls for both a large declaration surface with small context-only bodies and
a context payload that exceeds its own cap.

The validated-body-hit marker now records whether the body requires `SourceInput`.
Publication validates its source result generation for ordinary bodies and checks
that the dependency list is empty for `complete_empty_body` and scanner-proven
zero-fact bodies; it also checks the exact body span, key, graph generation, and
result generation. Graph clears still invalidate the marker. Any future dependency
class must carry equivalent evidence for its exact current dependency set before
it can skip publication.

The existing `NameLookup` query returns only `(known, module_only)` and omits
binding types, signatures, attributes, and declaration identities. It can skip
name classification, but cannot alone authorize body-fact reuse. Body reuse needs
a distinct versioned canonical `FunctionFactName`/`CallTarget` projection or a
complete declaration-surface fallback; this projection is not a semantic-resolution
cache and need not serialize type details the fact walker does not observe. Do not
persist request-local declaration IDs or handles.

The query graph propagates dirtiness when a node's canonical result changes;
changing its input alone advances the node's input bytes but does not increment
its result generation or dirty its dependers (`ifq_query_commit`). Therefore a
`FunctionBodyFacts` edge to the current `NameLookup` result is insufficient even
if that lookup's input includes more resolver facts: the result can remain
`(known, module_only)` across a binding change, such as a const becoming mutable
or a same-name callable candidate being added. A body-context query must return
the exact typed facts the body walker consumes (or its canonical fingerprint),
so an observed dependency change changes the context result and reaches the body
through the reverse edge. Add a same-classification/different-binding
invalidation control before relying on this propagation.

If graph lookup, admission, evaluation, or result restoration misses, the collector
falls back to copying prior typed facts when the current declaration surface and
body exactly match; malformed or incompatible prior facts fall through to the AST
body scan. This preserves the existing safe reuse path when graph limits reject a
query. After a successful snapshot store, the private publisher seeds or updates
source and cacheable body nodes, which can repopulate a cleared graph; generation
exhaustion permanently disables graph use for that session. After collection,
publication rebuilds and reevaluates the source query. For body-query hits restored
successfully during collection, request-local markers let publication reacquire a
fresh body-query handle and skip duplicate body copying, hashing, and evaluation only
when graph generation, exact query key, body-record span, result generations, Green
dependencies, and graph health still match. The markers contain request-local IDs
and generation evidence, never query handles; graph clears and retries invalidate
them. The `body_query_publish_skips` counter exposes validated skips. Misses and
unrestored bodies keep the existing publication path. The resolver's `SourceInput`
admission also copies the declaration surface into a temporary span and again into
the encoded input before evaluation on each semantic request. A span-backed evaluator
could avoid those copies while keeping exact equality. These work-reduction paths are
not measured costs or speedup claims. No source-matched retained-edit benchmark has
qualified the graph path, and the implementation has not passed runtime parity or
performance qualification.
Persistent `semantic-session` and `compile-session` hosts keep graph evaluation and
publication disabled by default. Set `ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH=1` to
opt in; the typed snapshot and exact-fact fallback remain active in either mode.
Per-value preflight guards are now present in the live source: the collector and
publisher check the exact encoded `SourceInput` size before making its graph value
copy, body lengths above 16 MiB skip graph copies, `ifq_query_evaluate` returns a miss
before hashing an oversized input, and direct-fact result size is validated against
the same per-value limit before serialization reserves or appends bytes. The typed
snapshot remains the fallback for values rejected by these checks. The collector
still assembles the proposed declaration surface needed for exact snapshot
comparison. These checks do not preflight remaining aggregate graph capacity: a
permitted body copy or canonical result can still be materialized before commit
discovers that the 16 MiB value pool or 32 MiB aggregate estimate has insufficient room. The aggregate logical
cap also excludes these pre-admission temporaries. A remaining-capacity preflight or
span-based evaluation path could reduce that transient peak; keep the graph opt-in.
These guards have source review only and still need parity and retained-session
performance evidence.
The opt-in `incremental-ga-cache` report now separates request-local
`function_body_facts_restored`, `prior_snapshot_fact_fallbacks`, and
`cold_body_scans` counts. They are mutually exclusive per collector candidate and
bounded by the candidate count. A restore means the graph result decoded and
validated against the trusted prior typed facts; a fallback means the graph path
did not restore and exact prior typed facts were copied; a cold scan counts a call
to `ifc_scan_candidate`, including candidates that the scan later rejects. The
`source_input_admitted` flag means both the exact SourceInput query hit and the
trusted prior declaration surface admitted the graph body path. It is false on an
exact-source session return because that path bypasses the graph, and it does not
describe either source-independent body-fact path that deliberately has no
SourceInput edge. The separate `zero_fact_body_eligible` and
`zero_fact_body_restored` counts describe scanner-proof/restore attempts before
final declaration-surface validation; if that projection fails, the collector
clears all cacheable body records and publication does not proceed. The
`zero_fact_body_publish_skips` and `zero_fact_body_commits` counts apply only to
successfully published graph records. These class counters supplement, rather
than replace, the general restore/fallback/scan counters.
These counters describe routing only; do not claim a production query engine or
speedup until parity controls and measured results show the graph improves the
retained-edit path.

The paired retained-session harness now has `zero-fact` and `call-facts` workloads.
Its `zero-fact` fixture is the literal-return `complete_empty_body` control; it does
not cover the broader scanner-proven zero-fact class described above. A future
control should use a multi-statement literal-only body, change an unrelated
declaration, and then mutate the body to read a local/parameter identifier to
prove that the zero-fact cache path is dropped. The `call-facts` workload uses a
distinct leaf callee per body and requires warm `NameLookup` hit
totals to exceed the prime request's same-request duplicate baseline, exposing
aggregate prior-request reuse. It also asserts `direct_fact_count` is one per
`bench_*` body, while the `zero-fact` workload asserts there are no direct facts.
Both workloads compare complete non-telemetry transcripts and body-edit fact
restores. Both graph modes report NameLookup `classification_chain_visits`. That
counter covers only symbol/member rows visited by the fused NameLookup cold
classifier. Direct `name_known` callers such as `Expr.RegionNew`, value-block
captures, and flow checks, plus qualified `Expr.Scope` probes through
`name_is_module`, `ancestor_names_module`, `two_part_names_module`, and
`module_declares_member`, are excluded; this is not total resolver name-chain work.
Lexical bound-name checks still run before the query;
region membership comes from the finalized surface on active queries and is scanned
only on the cold fallback. Surface construction is lazy at the first eligible unbound
read; a request with no such read skips the prepass, while one eligible read still pays it. The benchmark fixture has no locals, region names, or
qualified paths and does not measure those costs.
For `call-facts`, the runner requires positive cold visits on the graph-on prime request,
then fewer visits than graph-off on exact-repeat and body-edit requests. The prime request
seeds the graph and is reported separately from warm body-edit timing ratios. Chain-visit
reductions can include both duplicate same-request reads and retained hits; the counters do
not partition those sources. Timed arms set `ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1`,
which adds per-row chain-counter work; graph-off visits more rows, so current ratios
include asymmetric telemetry overhead and may overstate graph-on gains. Treat these
timings as instrumentation-biased, not production-equivalent, until a counter-disabled
timing arm exists. The harness records request timers but does not capture compiler
process instructions or cycles. It has not produced a source-qualified performance
result, so its assertions and timing ratios are qualification machinery, not evidence
of a speedup.

Graph admission caps owned key bytes at 8 MiB, canonical input/result bytes at 16
MiB, query nodes and their possible hash-index entries at 65,536, edge slots and
free-list entries at 262,144 each, and one dependency set at 4,096 IDs. The
`SourceInput` key is preflighted from identity/path lengths and rejected before copying
or hashing when it exceeds 8 MiB; the generic key API also rejects oversized keys
before hashing. These rejections preserve the collector's typed-fact fallback. A
conservative logical-storage estimate also caps retained graph data at 32 MiB, including estimated
node/index, edge, free-list, and worklist overhead. Commit checks replacement's
temporary free-list peak before changing graph contents. The estimate uses logical
counts for graph pools and retained capacity for the reusable worklist. `darray` and
dictionary allocators can round other capacities above those counts. In the long-lived
session region, non-tail `darray` growth can also leave old backing buffers allocated
until region teardown, so the 32 MiB value does not bound total retained region bytes
across growth generations. This is an admission bound on estimated payload, not a hard
process-RSS limit. Before qualifying or expanding the current collector caller,
measure/account the graph region's retained bytes or use fixed-size chunks with a
hard capacity.
Each query node carries a u64 invalidation-generation stamp, and the session reuses
a worklist whose retained capacity is included at 8 estimated bytes per slot. The
worklist grows with the reached reverse closure and is reused by later edits; only
generation wrap clears all node stamps. This avoids per-edit O(V) visited-array
initialization and full worklist reservation.
Each node also tracks its incoming-edge count and adjacency validation generation.
Dependency preflight fully checks a chain when its validation generation is stale;
checked local edge splices advance the count and generation together, so the shared
`SourceInput` chain is not rescanned for every body commit. Reverse-closure invalidation
still walks each reached chain and requires the traversed edge count to match before it
changes query statuses, catching a cleanly truncated tail without a per-body O(N²) scan.

The dense query-node record keeps status, adjacency handles, and its invalidation
stamp ahead of the key spans and fingerprints. Its six key/input/result span fields
are checked `u32` values under the 8/16 MiB pool caps. With the current incoming-chain
validation fields, the sequence is estimated at 112 bytes under conventional 64-bit
alignment, versus 136 bytes with `usize` spans; admission budgets 128 bytes per node
to include index overhead. The edge record is 28 bytes by field width and about
32 bytes with conventional alignment; admission budgets 48 bytes. These are
source-level estimates, not measured Elisa layouts or speedups. The current graph
has collector `SourceInput`/`FunctionBodyFacts` callers and a resolver `NameLookup`
caller. These are distinct query paths; body-fact reuse still overlaps the existing
snapshot reuse path, and none has source-matched parity plus retained-edit timing
qualification. Profile each path separately before crediting a speedup.

The checked Zig revision's `AnalUnit` is a packed 64-bit kind/ID handle. Its
`DepEntry` uses a 64-bit depender handle and three 32-bit links; the dependee
identity is implicit in the typed dependency-head map. Elisa stores two 32-bit
query endpoints, three 32-bit links, and a 64-bit observed result generation per
edge (28 bytes before alignment). The outgoing dependency chain is singly linked
because replacement removes the whole chain; the incoming depender chain stays
doubly linked for O(1) unlink. Admission estimates 48 bytes per edge slot for
alignment headroom. Zig's layout remains a useful alternative if Elisa introduces a
typed dependency table. As additional callers are added, measure edge and index
capacity plus replacement and invalidation costs before changing the representation. The
source-level comparison and references are in
[`compiler_incrementality_reference_study.md`](compiler_incrementality_reference_study.md).

Dependency deduplication still uses nested scans. Current `SourceInput` and
`NameLookup` callers pass no dependencies, and `FunctionBodyFacts` passes one
`SourceInput` dependency, so current fanout does not make those scans a measured
hot path; the 4,096-ID admission cap is a future bound. Preflight already
deduplicates the checked IDs, making the apply-side duplicate scan redundant
under its current private caller. If future queries record per-name or per-symbol
dependencies, measure the complete check-and-commit path and dependency-count
distribution before adding a scratch set. A more plausible near-term experiment
is a scalar 0/1 dependency-check path: preflight currently creates both
`dependency_ids` and `old_ids`, and `FunctionBodyFacts` checks its single source
edge during evaluation and again during validated warm-hit publication. Measure
the resulting scratch allocations and full retained-request time first; keep the
existing generic validation path for larger sets. The value pool is
append-only between graph clears. After each successful session snapshot store, the
publisher records the current source and cacheable function results; on failure it
clears and retries once, then leaves the committed semantic snapshot available to
the cold-safe path. Region allocator growth can retain prior backing buffers until
teardown, so the logical limit is not a hard RSS bound. Before treating graph hits as
a performance feature, qualify failure behavior across context-store failure, graph
overflow, and cold fallback; then measure the full publisher cost as well as sparse
and dense invalidation and dependency-deduplication costs. Graph-generation
exhaustion is fail-closed and permanently poisons that session's graph rather than
wrapping a handle generation back to an earlier value.

One graph optimization refreshes stale dependency generations when the
dependency IDs are unchanged. [`ifq_query_commit`](../src/semantic/incremental_function_facts.elisa#L3071)
sets `dependency_replacement_required` only when IDs differ and sets
`dependency_generation_refresh_required` for equal IDs with stale generations
and Green dependees. Changed IDs still run the cycle check and use
[`ifq_apply_dependency_set`](../src/semantic/incremental_function_facts.elisa#L2992)
to replace topology. Equal IDs use
[`ifq_refresh_dependency_generations`](../src/semantic/incremental_function_facts.elisa#L3038),
which validates the entire edge chain before updating each edge's
`observed_result_generation`; adjacency and incoming-chain generations remain
unchanged. If any validation fails, the graph fails closed. The earlier
`current-settled` semantic gate started before this helper was added. The later
source-hashed `frozen-a73ea` gate included it, but still reported compiler errors
in snapshot reanchoring and the semantic API, so this path has no passing build
qualification yet. Add separate generation-refresh and topology-rewrite counters, then
use a declaration-surface edit to verify refreshes without rewrites and measure
edge work plus full retained-request time. No timing result establishes a
speedup yet.

A later source-matched Stage1 seed on 2026-10-19 used source hash
`4109a3adab3cf74376f792a3d01f2f141065488eb7fae2bc3cf1def19b10fac6` and build-recipe
hash `f4cf2fb863d549b4e5e7d8d0182295b7bf51dca565d284a89550f2836f70a67e`. Its before
and after source and recipe content hashes and stat fingerprints matched, but the
Stage0 bootstrap compile exited with status 1. The log is
`/private/tmp/elisa-goal-rgn-seed.log`. Remaining region diagnostics include an
`input_source` escape into the exact-reanchor plan and escapes through the semantic
lookup session/context at `semantic_api.elisa:893` and
`elisac_source_probes.elisa:285`, plus wrapper lifetime errors in `semantic_api.elisa`.
The worktree has since changed, so this is a qualified failed attempt for that exact
source snapshot, not a qualification of the live tree or a Stage1 product. A second
pinned seed used source hash
`93ef7df21cf5c72be9e6e610036d0ef91d59c9df9a67b2bbcd49a3fbad73e58f` with the same
recipe hash; its before/after provenance also matched and it failed with the same
remaining plan and semantic API lifetime diagnostics. Its log is
`/private/tmp/elisa-goal-rgn2-seed.log`. The worktree advanced again after this run.

A later shared-tree seed captured source hash
`7566eae6e51ff8342d4b01846649df55191477e993107e60870a4b19ea0b11d8` and ended with
status 1; the log is `/private/tmp/elisa-goal-clean-seed.log`. Its post-run source hash
was `1b52569a1a433f75e141dc064d2cd17d40a5e6ad741645c018efe3a13956a56f`, while recipe
hash and stat fingerprint matched. The only source file reported as changed during
the run was `incremental_function_facts.elisa`. The captured revision had no IFC
plan-region diagnostic, but this does not qualify the later IFC source. Unchanged
`semantic_api.elisa` and `elisac_source_probes.elisa` still reported eight lifetime
diagnostics across their lookup-context and local-storage boundaries. This is mixed
source evidence, not a full-tree qualification.

The next seed captured source hash
`0084d187fd7441276329a705b3c7d2461e3681017446b5a0296d6001c73d8e94` and was
terminated with status 143 before producing an after-provenance file. Its log is
`/private/tmp/elisa-goal-ifc-annotated-seed.log`; the recipe fingerprint matched at
launch. During the run, live provenance showed source hash
`b2d193afa0a97cdc5c816874b61d43320c3dceaa9426f65637e2a002bbde404a`, with edits after
capture to `check_borrow_binders.elisa`, `semantic_api.elisa`, and
`store_through_summary.elisa`. This interrupted run provides no build qualification.

The report counts `eligible_bodies` and `matched_eligible_bodies` by unique
cacheable function record, so a body with multiple facts cannot inflate
eligibility. `visited` counts candidates passed through the collector walk,
including candidates rejected before `ifc_walk_body`; it excludes session bodies
whose facts were copied. `matched` counts exact body matches under a compatible
declaration surface. Exact-input session hits recompute the match flags for all
current cacheable records during reanchoring; they do not carry forward a prior
edit's match ratio. For sidecars those bodies were rescanned; `session=edit`
means at least one matching body actually reused in-process facts. `ga_walks_skipped` counts Global-authority body walks skipped.
`effect_source_bodies_skipped` counts function bodies whose repeated effect-source
scans were bypassed. `ungranted_panic_bodies_skipped` counts function bodies whose
bound-name collection and two panic-coverage body scans were bypassed.
`global_permission_axis_scans_skipped` counts Read/Write body collectors replaced
by current-fact projection or by an empty zero-fact result. Each eligible function
contributes two when Global-permission enforcement is enabled and the file has at
least one mutable global. Fact projection currently keeps bodies with local
bindings or nested control flow on the AST path. Each metric counts bodies or axes
once per pass, not individual helper walks. Any future
local-initializer products must be reported separately from function-body counts.

The current-source fact scan also allows `collect_effect_sources` to skip its
repeated body scans for a uniquely anchored, cacheable top-level function with
zero direct facts. This applies on cache hits and misses because the evidence is
recollected from the current AST; stale sidecar flags and names do not authorize
the skip. Duplicate or malformed anchors and unsupported bodies remain on the
cold path. The report counts these bodies as `effect_source_bodies_skipped`,
separately from `ga_walks_skipped`. A second Global-authority case consumes a
record only when every current fact is a direct call with no active grants. It
resolves all targets uniquely against the fresh function index before adding
edges, then skips that body's inference walk; the report walk remains cold to
preserve exact diagnostic locations. The same proof skips only the body-bound-name,
panic statement, and grant-coverage scans in `check_ungranted_panic`; effect-wrapper
indexing/closure, code generation, and linking remain on the full path. With
Global-permission enforcement enabled, verified current-source facts can skip
direct body scans for eligible top-level functions while retaining every function
slot for closure and row publication. A zero-fact record is usable only after the
current anchor, cacheability, and complete fact span checks pass; literal
`Stmt.VarDecl` bindings may occur in that lane. Fact-bearing records use the
restricted flat-body projection, while `=` assignments, nested control flow,
comprehensions, nested declarations, and unsupported expressions stay cold. The
direct checker control enables Global-permission enforcement, compares canonical
rows, and asserts axis-scan counters; the CLI control enables it with `# globals`
and asserts the same counter alongside the other pass counters. Runtime parity
for these updated controls is still pending a fresh Stage1 product. LLVM fragment
loading remains a separate later stage.

The Global-permission fallback has since replaced the old function-wide local
census with source-order binding stacks and branch/scope copies. Its expression
and call visitors now cover the previously listed `Expr.If`, match/catch guards,
call callee and argument, assignment-place, block, comprehension, and recovery
children. The incremental collector remains narrower: verified zero-fact records
can skip both Global axes, while fact-bearing records use a flat-body projection
and unsupported control-flow, contracts, comprehensions, or call shapes stay on
the cold AST path. Literal `Stmt.VarDecl` bindings can still occur in a verified
zero-fact body; they are not categorically cold. Keep the current-record,
cacheability, and fact-span checks ahead of every empty-fact shortcut. These are
source observations; the latest full Stage1 seed has not qualified them.

R69 source review found that a zero-argument `panic()` is recorded as `PanicSite`,
but the Global-permission projector treated that kind as a no-op even though the
cold call walker adds a conservative unknown-target edge. The current projector
now rejects `PanicSite` during its preflight pass, before appending any projected
edges, so both Global axes fall back to the cold body walkers. This is a
source-level soundness repair, not yet Stage1- or parity-qualified. The existing
`panic_only` fixture cannot exercise this projection path because it uses a
trusted block and does not call the function; a future parity control should use
a flat cacheable `panic()` body called from an ungranted caller, with both
Global.Read and Global.Write siblings, and compare cold, first-snapshot, and warm
diagnostics.

One cold-path semantic disagreement remains for plain `=` to an identifier.
The Global-authority walker treats it as a new local binding, while the separate
Global-permission write walker can infer `Global.Write` if the unbound spelling
resolves to a global. The incremental collector now keeps every plain
`Stmt.Assign(..., Assign, ...)` cold, regardless of target or RHS; this avoids a
cold/warm difference without deciding which pass matches Stage0. Re-admit this
shape only after a Stage0 oracle and binding-aware parity establish the intended
semantics.

The scoped Global call graph now tracks declaration slots, routes local or
computed callees through a conservative unknown edge, and closes effects with a
worklist. However, effect-row publication still calls `gp_push_source_row` with
the bare function name; `function_effect_refs` and the ungranted-call path also
look rows up by the leaf returned from `called_function_name`. Same-named
functions in separate modules can therefore share inferred Global rows after
the scoped closure. Preserve a scoped declaration key through publication and
lookup, and make the existing `Left::touch`/`Right::touch` parity fixture check
the published rows and caller diagnostics.

Two remaining cold precision limits are separate from cacheability. The Global
walkers traverse every `Stmt.Contract`, including proof/frame-only
`decreases`, `decreases*`, `invariant`, `changes`, and `preserves` that the
backend does not lower at runtime; filter those kinds to match runtime behavior.
They also analyze literal lambda callback arguments as executable even when a
known callee never invokes them. The incremental collector rejects these shapes,
so these are cold over-approximations, not warm-cache undercounts.

The function-value signature checker still collects fn-typed locals from nested
branches and loops into function-wide name/type arrays, then chooses the first
same-spelled entry when validating assignments. Shadowed function-typed locals
can therefore use the wrong declared effect row. Its separate site-check visitor
also covers only selected expression kinds. The fix belongs in a
scope-aware local-to-type map and a deliberate expansion of that visitor.
The AST now carries a `query_scope_id` on comprehension nodes and collection
comprehensions preserve their original opener `Pos`. The parser derives this
parse-local `u32` as `for`-token offset plus one, reserving zero for synthetic
nodes. The backend now derives scope IDs for query annotation rows and uses them for
comprehension emission, count, and extremum recognition. Semantic annotation
ingestion retains the raw `for`-token offset, while the resolver, all three
global-permission walkers, and the global-authority walker convert that offset to
the same parse-local ID and compare it with the AST scope ID; `Pos` remains for
diagnostics. This fixes the opener-versus-`for` join and same-line clause identity.
These semantic consumers still scan every binder row for each query and truncate
mismatched parallel offset/name arrays, so add a validated per-scope range index
and fail closed on malformed metadata. If
annotation tables merge parse units, qualify the identity by parse unit rather
than using an offset alone. Backend lookup also scans by scope. The leading
enumerate-query parser accepts a comma list of extra binders; codegen currently
supports one extra binder for the recognized enumerate form and declines larger
arities. Nested `for` clauses parse one binder, and nested lowering now declines
an extra binder on the leading clause before dispatch rather than dropping it.
Either lower every accepted binder or preserve explicit fail-closed handling for
unsupported arity and lowering shapes. IFC currently declines comprehension
bodies, so this is a cold semantic scope issue rather than a demonstrated
warm-cache undercount.

### Driver source context boundary

For each gate, `static generate` may replace the analyzed inputs. The existing
`report_src_ptr`, `report_tokens`, and `report_source_len` track that expanded unit;
the original input remains the source of header-based checking options. These are
two distinct inputs to cache validation: expanded program identity and original
policy configuration. Passing the original token stream beside an expanded AST is
not a valid reuse context. Early pymodule semantic gates use the same rule.
An environment path alone does not attest either source buffer.

A bound record must also prove exact current body-token equality and current
source-declaration membership. Matching a path, name, definition offset, and token
range is insufficient when bytes changed at the same offsets or synthetic callable
rows entered the authority inventory. Invalid or ambiguous binding takes the cold
checker path before any stored effect facts are applied.

## Native partition reuse (2026-10-18)

Core commit `1cb75ef0d05d` adds bounded in-process native partition reuse to the
compile server's opt-in `mode=obj` path. It still rebuilds and optimizes current
LLVM IR. Exact post-optimization partition bitcode plus resolved target settings
authorize native reuse; a digest alone does not. Native cache entries own no
semantic/LLVM handles. Source filenames provide stable unit identities; anonymous
units and unsupported partition constructs take direct emission. Selective
definition cloning reduces preparation overhead, and short cache/LRU locks allow
independent O0 requests to compile concurrently. Address-significant private
constants have one owner, preserving pointer equality across partitions.

A final source-matched real-server run on the local M5 fixed both paths at eight
partitions/workers. Nine novel constant body edits in 256 integer arithmetic
functions measured HTTP source-to-object medians of 338.24 ms fresh and 280.01 ms
incremental. Four-request warm batches measured 930.60 versus 558.22 ms medians
over five batches: 4.30 versus 7.17 requests/second. Cold incremental was slower
at 576.30 ms. The shared host produced variable timings, including a slower
incremental single-edit sample. These are synthetic O0 measurements, excluding
final executable linking/execution, not self-compiler or project qualification.

A separate synthetic `BenchmarkCompileServerNativeBodyEdit` profile from Core
`cbaa6619` measured 1.20 seconds CPU over 1.78 seconds elapsed; `IncrementalObjectSession.WriteObject`
accounted for 790 ms cumulative. The measured codegen implementation and benchmark harness files
are unchanged through Core `e97b9983`, so the cache-order observation still applies to the current
path. Source order in `llvm_incremental_object.go` confirms the current module is built and
optimized before partition cloning, bitcode serialization, and per-partition cache lookup. The
profile attributes about 250 ms to module build/optimization,
100 ms to partition cloning, 180 ms to bitcode serialization, and 130 ms to target emission;
inclusive Go/native counters overlap and are not disjoint costs. This synthetic sample is not
end-user latency, but it shows why partition reuse alone does not skip frontend, IR construction,
whole-module optimization, or partition serialization.

The backend/server suites, targeted race/concurrency tests, native O0/O2/O3
parity, LLVM boundary guards, debug relocation and anonymous-unit controls pass.
Read-only overlays excluded unrelated loop-proof changes; these checks do not
qualify verifier changes in the shared commit. Matching code and script hashes,
compiler hashes, raw samples and overlay sources are preserved in
`build/verification/incremental-native-final-20261018/` in both repositories.

Instruction-weight shard boundaries and complete declaration inventories remain
sensitive to large body edits or declaration insertion/removal. The reviewed
modulo-divisor ownership scheme can rebucket nearly every function after one
insertion; fixed logical bucket IDs with empty buckets allowed would preserve
placement better, with an ownership-version bump. These workloads need explicit
locality measurements. General semantic
replay, avoiding complete LLVM generation/optimization, persistence, normal CLI
integration and representative edit-to-executable qualification remain required
for the full professional incremental-compilation goal.

## Fresh-process partitioned-submit cache check (2026-10-27)

Core `963744f2` enables the guarded O0 partitioned-submit path for a mutable
pool and a generic permission parameter. The focused
`TestPartitionedStoreCapturingSubmitRuntime` matrix passed all ten serial,
generic, disk-cold/warm, and experimental partitioned cases under the 28-second
outer test limit. Each child compiles, links, and runs the fixture; the retained
server is disabled. `TestPartitionedIRDiskCacheFreshSessions` also passed its
four revisions (20, 20, 21, 20), including a changed body and a revert, with
native-status parity and disk partitions reused by newly created sessions.

Two separate fresh `go test` processes with a shared disk-cache directory and
the retained server disabled confirm the experimental submit fixture emits two
native partition objects on the first invocation and zero on the repeat. Its
internal phase samples were 5 ms partition generation plus 14 ms merge on the
first run, and 2 ms generation plus 14 ms merge on the repeat; both whole test
processes took about 0.4 seconds. This tiny fixture verifies disk reuse and
runtime correctness, but the end-to-end timing is dominated by fixed work and
does not establish a speedup. The full Stage1 self-host build, normal CLI
integration, and representative edit timings remain unqualified.

## Self-host bottleneck review (2026-10-18)

The recorded Stage1 self-host profile puts semantic checking at 46% of samples,
LLVM IR construction at 39%, and O0 object emission at 4% (`docs/build-speed-notes.md`).
This sets the work order: semantic-result and body-IR reuse can address the dominant
repeated work; a native-object cache alone cannot. The Core compile-server cache
still helps object-heavy requests, as its source-to-object measurements above show,
but it does not skip frontend analysis or current-module construction.

The older ownership-binding lookup in
[ownership_binding_lookup.elisa](</Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/src/semantic/ownership_binding_lookup.elisa:33>)
had a possible hot-path cost: its successful postcondition contained an
existential over all `ref_pos` rows, even when the implementation had selected
a row from the owner bucket. A reduced-shape probe has compiler and source
provenance: its source
`/private/tmp/elisa_exists_value_probe_stage0.elisa` (SHA-256
`893a38fe0418a6d4dd8db0a09386863e75cb8575e02f1d7c6d9aa16da60481ad`) builds
a runtime byte array and evaluates two identical Boolean `exists` expressions.
The receipt-backed Core Stage0 compiler (commit
`294e5f910a27949115af5296e071b57ebdc01659`, binary SHA-256
`191fc072361b79932e26397354e641270e45cb939aaa74fc64242d030b44343b`) emits
two separate loops in the `-O3` IR (SHA-256
`5ed757d3eac5dd2702004101a8f0c3c294accf1db2e5ffe841546abb5ac07b5b`). LLVM
23.1.3 `llc -O3 -mcpu=apple-m5` emits
`/private/tmp/elisa_exists_value_probe_stage0_O3.s` (SHA-256
`cc6ba2f8f10aba9d5dfd800e6fa0e1d20f586fd1b9432767a1668d7215f951c5`) for
`arm64-apple-darwin27.0.0`, with two loops that each perform one byte load and
comparison per visited element; the second loop restarts at the array base.
When a matching byte is at the last position, this reduced positive case reads
and compares up to `2N` bytes. This confirms that the optimizer does not merge
these repeated quantifiers in this reduced value-expression shape. It does not
establish the optimized code shape of the current
`ownership_binding_at_position`. An earlier `assert exists` probe was removed
from emitted IR and is not evidence. The current source returns a `witness_index`
and checks its bounds and exact row with `ownership_lookup_candidate_matches`,
removing the table-wide quantified ensure. The proof fixture mirrors that
selected-row contract and the miss sentinel, but R76 still failed to prove some
lookup postconditions; the fixture and source-bound checker were edited after
that snapshot, so their updated state has not yet passed a compiler gate.

The current lookup still walks a linked list of references for the owner. A
multi-row bucket can therefore take O(k) row visits per lookup; repeated lookups
for k references can remain O(k²) in a large function. This is a source-level
worst-case, not a measured runtime result. No source-matched Stage1 IR or
assembly for the exact lookup has been produced, so emitted cost and the net
effect of the witness result remain unverified. Any future indexing change must
preserve the ambiguity and malformed-row fail-closed behavior.

The local static artifacts are historical and do not match this checkout. The
2026-08-05 `build/s1_driver.ll` has 1,079,457 instructions across 5,020 functions;
`Semantic.check_full` alone contains 492 call sites. The 2026-09-14 Stage1 object
`build/field-lifetimes-20260914/selfhost/elisac_stage1_gen2.o` disassembles to 7,691
arm64 instructions for `Semantic.check_full_into` (451 calls, 205 branches, about
5.5 KiB of stack frame) and 4,457 for `Backend.emit_module_core` (116 calls, 206
branches, about 18 KiB of stack frame). These counts explain why the unoptimized
self-hosted compiler has substantial frontend and IR work, but are not current-tip
timings or a matched IR/assembly pair. The saved August IR also fails to assemble
with the installed LLVM at a typed `insertvalue` mismatch, so it cannot provide a
current assembly comparison. Regenerate a source-matched IR/object pair before
using instruction counts to choose a local code-generation micro-optimization.
An IR emission attempt with the available 2026-10-11 Stage1 product also failed on
current standard-library/backend syntax before code generation, so it cannot refresh
these artifacts.

## Stage1 semantic-session host (2026-10-18)

`elisac-stage1 semantic-session SOURCE` is an opt-in persistent host for the
Stage1 semantic session. Send one `check` line for each saved edit and `quit` to
stop it. Each check rereads the same source path, rebuilds the include graph,
line map, tokens, and AST, and returns `0` for accepted, `1` for rejected, or
`2` for an invalid protocol command on stdout; compiler diagnostics remain on
stderr. The current server opens `request_scratch` around source processing in
`src/driver/elisac_incremental_server.elisa:73-125`, but the parser API and AST
payloads still declare source-backed data in global `@source`
(`src/parser/parser.elisa:93` and `src/parser/ast_nodes.elisa`). Parser names
also use the append-only `@source` `NameStore`. The request wrapper is therefore
an intended lifetime change, not proof that each request’s source, AST, or names
are reclaimed. The exact-source Stage1 seed currently fails its lifetime checks,
and a retained-edit memory control has not qualified reclamation. The host also
keeps a reusable lexer line-map buffer, and an identical map preserves the
lexer’s parsed lookup tables. Every check still rereads and parses the source
before semantic reuse, so cache hits do not avoid frontend work.

The session snapshot copies analyzed bytes and portable facts into session-owned
buffers. Its reviewed representation contains offsets and scalars rather than
borrowed source views. A passing lifetime check must establish that source and
AST views do not escape through semantic publication or diagnostics, and show
which parser/name allocations remain in `@source`. Measure retained session,
line-map, and any process-lived parser capacity across repeated edits.

This first host reuses the existing validated function-fact path for an exact
repeat or a source edit. In the trusted in-process session only, it also reuses
complete self-assignment findings for supported top-level function bodies and
rebinds their target and statement locations against the fresh token stream.
Unsupported bodies and decoded disk snapshots keep the ordinary checker path;
the portable sidecar codec does not serialize these lint facts. The report's
`self_assignment_bodies_scanned` and `self_assignment_bodies_reused` fields count
those per-body scans and reuses separately from authority facts. It still rebuilds
the parse tree for every request. The query graph backs this narrow body-fact path
and also has an opt-in resolver `NameLookup` route at `Expr.Ident` classification;
it does not replay full checker results or reuse LLVM/native artifacts.
It is intentionally tied to one source path and fixed process environment for
its lifetime; launch a fresh host to change compiler options or source identity.
Ordinary CLI compilation remains one-shot. The host control is wired into
`test/parity/incremental_prior_key_index_gate.sh` and runs through the Stage1 wrapper.
It checks exact repeats, body edits, error invalidation, self-assignment replay and
fallback, and shifted diagnostic locations. Bash syntax and ShellCheck pass, but the
control still needs a fresh Stage1 run before its runtime assertions qualify the host.

## Stage1 compile-session host (2026-10-18)

`elisac-stage1 compile-session [-emit MODE] [-o OUT] SOURCE` is an opt-in repeated
ordinary source compile host. Send `compile` for each saved edit and `quit` to stop;
each compile writes `0` or `1` to stdout, and compiler diagnostics stay on stderr.
The root path, command-line options, and inherited environment are fixed for the
process. Every request rereads that source and rebuilds its include identity and
line map, so an include or root edit changes the session key and current diagnostics
are rendered against the current source. Request processing is enclosed in
`request_source`, but the parser API ties AST data and source views to program
`@source`; the driver also stores `source_bytes` and generated `expanded` text
there. Parser name storage and synthesized semantic names also use `@source`.
Because these allocations are attached to `@source` rather than `request_source`,
the driver does not establish that ending the request region reclaims them. Whether
the enclosing `@source` region is reclaimed per request or retained by the host
requires runtime/allocator verification; the current controls do not prove either
bounded reclamation or unbounded growth. Reclaiming each parse generation remains
an open lifetime/API question. The compile-session control sends fewer than 32
requests and has no RSS or allocator-growth assertion, so it does not exercise
epoch memory reclamation.

The shared request routine is also used by one-shot `main`; its three normal
semantic-gate callsites receive an explicit session reference. One-shot compilation
uses a disabled session, preserving disk-sidecar behavior. Repeated compilation
uses the retained in-process session for validated function facts and self-assignment
findings, then still runs current semantic checking, LLVM IR generation, optimization,
and artifact emission. The query graph reuses `SourceInput` and
`FunctionBodyFacts` results and, when `ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH=1`, can
cache resolver `NameLookup` classification for `Expr.Ident`. A body hit restores
canonical facts into the current snapshot; a name hit skips the fused classifier's
symbol/member-chain walk for that NameLookup probe. No source-matched retained-edit benchmark
qualifies this graph path yet.
The host does not reuse parse trees, other semantic query kinds, LLVM modules, or
native objects. LLVM object, IR, bitcode, executable, wasm, and Python
extension requests dispose their builder, module, target data, target machine, and
context before the next request. `check` and `edir` return before creating LLVM state.

The first host supports `check`, `obj`, `llvm`, `bc`, `exe`, `wasm`, `pymodule-so`,
and `edir`. It rejects stdout report modes so the status protocol stays readable;
project-target subcommands and `c-archive` are not wired into this session boundary.
The wrapper preserves stdin for this mode and applies its usual process memory guard.
This source change has only had static review so far; no build or runtime control has
qualified it, so it makes no performance claim.

## Fresh-process disk-cache measurements (2026-10-27)

The Core Go compiler's persistent analysis cache was measured separately from the
Stage1 CLI. The compiler was `/tmp/elisac-stage0-active`, Core main revision
`963744f2b903924ff0f10bf2a2bbae8b7ed6d6c7`, SHA-256
`c713b49457634fb8013a47bd7cbdde614180b77c858a316e6ebff2e1bb57ef3e`. The Core
worktree also contained uncommitted diagnostic-only IR-input/source-locator work;
the executable hash pins the tested binary. The deterministic fixture contained
8,192 functions of the form `def fN(x: i64) -> i64: return x + N` and a `main`
calling `f0`. One edit changed `f0` from `return x + 0` to `return x + 1`.
Base and edited source SHA-256 values were respectively
`9645a1cb5e2d3f8a3cdf5c5cf5e2efca3354a303db2a22e8c6fd90148b04b1de` and
`94e6e860227ab47d6f9c4d9b4a01580988adad6b3b6c97a5ebbc8d72a95bfb78`.

Three sequential fresh-process cycles used `-O0 -emit llvm`, a new persistent
analysis-cache directory per cycle, `ELISACORE_ANALYSIS_CACHE=1`,
`ELISACORE_BUILD_CACHE=0`, and an empty `ELISACORE_RETAINED_SERVER`. Every compiler
command had an external 28-second limit. Median wall times were 0.993 s for the
cold baseline that populated the cache, 0.178 s for an unchanged rebuild,
0.244 s for the edited build from the disk snapshot, and 0.403 s for an independent
cold compile of that edited source. The changed build restored a 22.9 MB analysis
snapshot, reported `update changed=1` and `fast=true`, and took about 60 ms in the
semantic update. Across all three cycles, generated LLVM IR matched the cold edit
after normalizing only generated identifiers matching `__([a-z_]+)_[0-9]+`, and
diagnostics matched exactly. This qualifies a medium synthetic LLVM workload; it
does not stand in for the full compiler tree.

The identical three-cycle matrix at `-O3` had median times of 0.975 s cold
baseline, 0.164 s exact repeat, 0.230 s cached body edit, and 0.386 s cold edited
compile. Each cached edit reported `update changed=1` and `fast=true`; generated IR
and diagnostics matched the independent cold compile in all cycles. The timings
show that this analysis-cache path retains the selected optimization level rather
than meeting the edit target by lowering optimization.

Separate Core regressions also passed for the seven-edit fresh-process IR oracle,
fresh-process native execution, and proof retraction after a contract edit:
`go test ./src -run '^(TestAnalysisDiskCacheFreshProcessEditOracle|TestAnalysisDiskCacheFreshProcessNativeExecution|TestAnalysisDiskCacheRetractsProofAfterContractEdit)$' -count=1`
completed in 2.968 s. The edit oracle includes a body change, record-field layout,
contract, effect, overload, and signature edits, and compares each result with a
cold compile.

The Stage1 wrapper's object cache remains opt-in. On a one-function `-O0 -emit obj`
fixture, three exact-repeat cache hits had a 0.566 s median while three uncached
compiles had a 0.317 s median; the cached and uncached object bytes matched. Cache
admission and dependency validation cost more than compiling this small input, so
the default was restored to `ELISA_STAGE1_CACHE=0`/unset. Explicit
`ELISA_STAGE1_CACHE=1` remains available for workloads where a full-source cache hit
has measured value. Symlink output paths bypass the cache so cache-hit publication
preserves the ordinary compiler's output-path behavior.

A separate Stage1 O0 self-host attempt on `src/driver/elisac.elisa` exceeded the
28-second external limit without producing an object. A five-second stack sample
captured 4,202 main-thread samples; 3,917 were in
`frontend_parser_parse_file_with_length`. This points to parsing the whole compiler
source as the next measured bottleneck. No Stage1 whole-tree speedup is claimed by
the synthetic disk-cache result above.

## Full-source O0 disk-partition repeat (2026-10-27)

A later no-server run compiled `src/driver/elisac.elisa` to an O0 object with the
Core partition cache enabled and then disabled, holding source, compiler, flags,
and the warm persistent analysis cache constant. The exact-repeat wall times were
3.835 s with `ELISACORE_BUILD_CACHE=1` and 4.894 s with
`ELISACORE_BUILD_CACHE=0`; this is one pair, not a median. The hit reported
`native 0s x0`; the uncached repeat emitted 96 native partitions, totaling 11.889 s
of native work. Both objects were 33,121,480 bytes with identical SHA-256
`fbe43b81a0b879eea30991122237bddb1fd9cb69b3cb6acaf302ba0fd43f3575`. Both linked
and ran the same Stage1 `-emit ast` smoke fixture successfully with byte-identical
output. The retained server was empty for both runs.

This is a measured 1.06 s (about 22%) reduction for an exact full-source O0 object
repeat, but it remains above the 0.5 s exact-repeat target. The measured tree
contained local, uncommitted 24-pass dispatcher chunking and its effect grants;
this cache-on/cache-off pair does not measure that source change against `main`.
It also does not qualify a body edit, O3 object quality, or a cold build under the
30-second cap. The earlier timed-out attempt above predates this completed run.

With timing and analysis-debug observers removed, the Core whole-object cache
stored this self-host object in 4.080 s and restored it in 0.220 s on the next
fresh process. A further fresh process with `ELISACORE_BUILD_CACHE` unset also
reported a hit in 0.218 s, confirming the default-on behavior. The retained server
was disabled. Populate and hit objects were byte-identical at the SHA-256 above,
and the combined compiler output transcript was byte-identical after removing the
cache status line. This meets the 0.5 s unchanged-object target for this machine
and invocation. It does not accelerate changed-source builds; those still run the
analysis and codegen paths measured below.

## Chunked semantic dispatcher codegen (2026-10-27)

The 221-pass dispatcher now routes through ten helpers, each owning a contiguous
range of 24 pass IDs (the final range is shorter). The generator audit verifies
that each existing ID and call remains covered exactly once, and the generated
file round-trips byte-for-byte. Its 96 Python generator tests pass; the audit
reports 146 parallel-eligible and 75 serialized passes. A Stage0 semantic compile
also removed the two new dispatcher-call effect warnings after the wrapper and
both call sites declared the helper's Unsafe requirements.

For a source-to-source comparison, both the current `main` dispatcher and the
chunked version compiled `src/driver/elisac.elisa` at O0 with native object cache
disabled, persistent analysis cache enabled, and the retained server disabled.
Across two runs per version, the `ir+partitions` phase median fell from 5.691 s on
`main` to 5.064 s with chunking (11.0%). Each build emitted 96 native partitions;
the median total native time was effectively unchanged (14.095 s vs. 14.316 s),
so the observed difference is in IR and partition preparation. The complete CLI
wall times are not used as the comparison because the restored analysis snapshot
replayed different source deltas for the two versions.

Both compiled self-host binaries linked and emitted the same 109-byte interface
for `test/breadth/parallel_range_fixture.elisa` (SHA-256
`ad580dc7737ebf528a22917fc4e9ff7428f31e6f07c1ad9c7b336535591fefe9`). This
qualifies the measured O0 phase gain and that semantic fixture only; it does not
qualify all pass combinations, O3 output quality, edit-to-executable latency, or
the 30-second cold-build target.

## Persistent partition cache on a current-source O0 body edit (2026-10-27)

The first current-source edit comparison used four fresh Core CLI processes in
two reversed-order pairs. The Stage1 tree was clean at
`59f1c081275585d0300285691f7ff5e5eadde149`.
The Core CLI binary SHA-256 was
`a3419e7303a1eae76a349633faf8cdc5b02a7697e41235deb91e8a87654316e3`; its Go
build metadata records VCS revision `eb16f6a2eac9091803eee04eb10ce51ba85c3727`
and `vcs.modified=true`, so the binary hash, rather than a clean-source claim,
pins the measured compiler. Every command had an external 28.5-second timeout,
used `-O0 -emit obj` on `src/driver/elisac.elisa`, restored semantic state from
one persistent disk cache, and ran with an empty retained-server setting. The
whole-object cache was bypassed with timing/debug observers; native partition
caching was enabled for the warm runs and disabled for the comparison runs.
`ELISACORE_PARALLEL_IR=1` and 96 object partitions were held constant.

The edit changed `emit_ast_annotation_private` in
`src/driver/elisac_emit_ast_decl.elisa` from `name.len >= 2` to the equivalent
`name.len > 1`. Each process reported one changed declaration and a fast semantic
update (739–780 ms). The two cached runs took 14.779 s and 14.385 s; the two
cache-disabled runs took 15.920 s and 15.795 s. Their medians were 14.582 s and
15.858 s respectively, a 1.276 s (8.0%) reduction in this two-pair sample.
Native emission dropped from 45 and 43 partitions in the cache-disabled runs to
one partition on the first cached edit and zero on the next, after that changed
partition had been stored. Both paths produced the same 33,117,088-byte object
(SHA-256 `52b800ed780f081f5d1ed786c9de3088b96c7d5b149ac83c6907125115010005`)
and the same 29,468 warning/error lines.

The whole edit still took about 14.6 seconds. IR generation alone was 8.6–8.8 s;
the partition cache avoids native emission but does not avoid generating the
current module IR. This is a correctness-qualified cache hit and a small
measured wall-time reduction, not qualification of the 2-second body-edit target.
More samples and reuse before whole-module IR generation remain necessary.

## Partition-local parallel-for workers on a current-source edit (2026-10-28)

Core commit `336081e5e2b2728974dd531b8bb5849590809919` gives O0 partitioned IR
generation a safe local identity for each generated parallel-for chunk, worker,
and chunk-specific `pool_submit1` specialization. The generated submit
specialization is emitted privately in the same module as its caller. Previously,
parallel-for lowering marked that partition unsafe, causing the IR-partitioned
attempt to fall back to whole-module lowering.

The focused Go verification passed under the 28-second outer limit:

```
go test ./src/backend -run '^(TestPartitionedParallelWorkerUsesPartitionLocalIdentity|TestPartitionedParallelWorkerRuntimeMatchesSerial|TestGenerateLLVMIRLowersParallelForOverFrozenPackedStoreForIndexSOA|TestPartitionedDistinctLambdaBodies|TestPartitionedGenericLambdaAcrossPartitions)$' -count=1 -timeout=23s
```

The regression checks that the worker and submit specialization are private
definitions in the owning partition, verifies the LLVM module, and emits both
IR partitions. A second fixture runs the generated worker callback and returns
the same status (`9`) after partitioned and serial compilation. The packed-store
parallel-for lowering control, distinct lambda identities, and generic lambda
partition tests also passed.

The Stage1 tree was clean at
`46925506e08ebdc6134dd7fc4c454c0e1fb90f09`. I built a Core CLI with SHA-256
`466c3249a84100df724409a07b4608014c47c3aca611430048e4c95b38a64bd6`; build
metadata records Core revision `bb7b6bd181d0c61f7fb01e74df30f81362d544b1`
and `vcs.modified=true` because the binary also includes diagnostic-only local
work. The commit above pins the parallel-for change, while the binary hash pins
the exact compiler used for measurement. A fresh 696,852,126-byte analysis
snapshot was seeded for that binary through resumable compiler processes. Each
compiler invocation had an external 28.5-second process-group timeout, used
`-O0 -emit obj`, kept `ELISACORE_RETAINED_SERVER` empty, enabled persistent
analysis and object partition caches, bypassed whole-object replay with
`ELISACORE_BUILD_TIMING=1`, and held 96 object partitions constant.

Three reversed-order comparisons used the same one-body edit in
`emit_ast_annotation_private` (`name.len >= 2` to equivalent `name.len > 1`).
Every request reported `analysis-disk update changed=1 fast=true` in 731–751 ms.
The partitioned object phase plus merge was 4.087, 3.974, and 4.002 seconds;
the whole-module IR phase plus native partitions and merge was 10.065, 9.915,
and 10.114 seconds. Their medians were 4.002 and 10.065 seconds, a 60.2%
reduction in the measured object-backend phase. The first changed partitioned
build emitted one native partition (178 ms); the next two emitted none. The
whole-module route still lowered the full module on every edit.

In the third fresh-process pair, total compiler wall time was 6.186 seconds for
partitioned IR and 12.322 seconds for whole-module IR. Both produced an object
successfully; the partitioned object hash was
`f99c0b19df095de0198257765bae32376b48180f790cd7917c779cd42015b95c`, while
the whole-module object hash was
`52b800ed780f081f5d1ed786c9de3088b96c7d5b149ac83c6907125115010005`. The
hashes differ because the partitioned path generates private, partition-named
helpers. The two paths emitted exactly the same 29,468 warning/error lines. The
runtime parity check covers the dedicated parallel-for fixture; the full
self-host object was not linked and run in this measurement.

This change brings this O0 body edit below 10 seconds in the measured setup, but
does not meet the 2-second body-edit target. It also does not qualify O3,
signatures, contracts, major edits, exact-repeat latency, or the full linked
self-host gate. Those remain part of the active target.

## macOS GC target for partitioned body edits (2026-10-28)

The Core CLI's default macOS Go GC target is now 300 (`fe66d2c3`); an explicit
`GOGC` value still overrides it. This follows two reversed-order pairs on the
same M5 Mac, with 24 GiB installed RAM and the existing 60%-of-RAM soft heap
limit. Each fresh process compiled `src/driver/elisac.elisa` with `-O0 -emit
obj`, an empty retained-server setting, the same persistent analysis and native
partition caches, whole-object replay bypassed for timing, and 96 O0 IR
partitions. The only measured change was `GOGC=100` versus `GOGC=300`; the
single function-body edit was the equivalent `name.len >= 2` to `name.len > 1`
change in `emit_ast_annotation_private`. The restored analysis state was
696,852,126 bytes; both edits reported `changed=1`, `fast=true` (746–764 ms).

Median CLI wall time fell from 6.543 s at 100 to 5.478 s at 300 (16.3%). The
partitioned backend phase plus merge fell from 4.299 s to 3.141 s (26.9%). No
native partitions needed emission in these already-warm runs. Both settings
produced the same object SHA-256
`f99c0b19df095de0198257765bae32376b48180f790cd7917c779cd42015b95c` and the
same 29,468 warning/error lines. A sampled peak-RSS pair was 5,314 MiB at 100
and 5,329 MiB at 300. The tracked binary used for these runs had SHA-256
`466c3249a84100df724409a07b4608014c47c3aca611430048e4c95b38a64bd6`; it was
invoked with explicit `GOGC=100` and `GOGC=300`, which match the old and new
runtime settings. The Core unit tests for platform selection and explicit
override passed.

This is a measured macOS O0 body-edit improvement on a warm disk cache. It does
not qualify other platforms, O3, other edit classes, cold-build time, or the
full linked self-host gate, and does not change the 2-second target status.
