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
unsupported; therefore the O0 shard cache remains disconnected from the driver.
These changes do not qualify incremental speedup.

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
while retaining each function slot; zero-fact bodies contribute empty axes. The
panic pass still builds its wrapper index and annotation views and visits
declarations; only bound-name collection and its body walkers are skipped. The conservative collector rejects
local reference writes, nested grant blocks, parenthesized expressions, and
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
across requests and calls the session-aware entry point. The new
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
speedup of about 5.0x for the dense 4,096-helper case, with identical prior
snapshot bytes, diagnostics and reuse counts. Small and low-query cases were
near parity. These are exploratory opt-in warm-cache results, not qualified
Linux results or evidence of default cold-compilation speed.

Current-function name uniqueness now also uses an index. Its exact-name hash buckets retain byte
comparison and reject a name immediately after the second exact match. In seven
shared-Mac pairs, a 4,097-function collector workload with mostly unsupported
generic bodies had a 3.046x median paired speedup; full canonical encoded
snapshot bytes matched in every pair. This span excludes parsing, object
emission and linking. The full self-host compiler seed and incremental correctness gate passed,
including uniqueness and prior-key controls at O0/O2, exact legacy encoding,
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

`src/driver/elisac_includes.elisa` expands includes into one flat source buffer and carries an original-file line map. `src/driver/elisac.elisa` tokenizes and parses that buffer into one `Ast::File`, then calls `run_semantic_gate` before creating one LLVM module. This means the first implementation should cache function bodies inside the translation unit; treating include files as independent compilation units would change name lookup and module semantics.

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
`check` requests and reparses each saved source version in a request-scoped region.
Each process is tied to one source path and fixed environment options; callers
start another host when either changes. The opaque session and one reusable
process-owned line-map buffer outlive a request; parsed source, tokens, and AST
remain request-local.
`test/parity/incremental_semantic_session_control.sh` exercises the protocol through
the Stage1 wrapper, including repeated requests and an edit that introduces then
removes a semantic error. A fresh Stage1 run is still needed to qualify session reuse
and request-region reclamation. The ordinary compiler entry continues to call the
session-disabled wrapper. Persisted sidecars still take
the current-source collector path because they are untrusted. Keep diagnostics on
the normal current-source path until a separate location-rebinding result format is
proven. The session stores only owned portable facts and grants, never AST,
SymbolTable, line-map, or LLVM handles. It keeps one bounded translation-unit
entry; changed admission inputs or invalid private snapshots clear it and run cold.

An exact session hit still deep-copies the retained portable snapshot before
reanchoring, and every request still lexes and parses the whole file. The first
host therefore validates the trusted session boundary; it does not yet prove
low-cost unchanged checks or edit-to-executable speedups.

The ordinary `main` path consumes one request and returns. It allocates
`source_bytes` in the program-lived `@source` region because the AST borrows those
bytes. The separate semantic-session command gives each request a temporary region
and publishes the new map into a reusable process-owned lexer buffer. The host
calls `PhaseTimer::request_start` and marks each completed check so
semantic timing rows exclude idle time between edits. Other process globals still
need lifecycle review.

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
`semantic-session` command is that host; ordinary compile commands remain one-shot.

In ordinary one-shot CLI compilation, the session-disabled wrapper does not consume stored
facts as authority effects. It rescans each supported body from the current AST
and rebuilds current anchors; sidecar cacheability and fact counts cannot
authorize a skip. The driver also exposes a session-aware internal entry point
that accepts only the opaque Semantic-owned session type. Its session operation
decodes private state and can reuse trusted in-process facts after checking the
exact declaration surface and unchanged body tokens. The opt-in semantic-session
host retains that session across requests; ordinary one-shot CLI calls still use
the disabled wrapper. A freshly scanned, cacheable zero-fact record can skip Global-authority walks,
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
boundary is exercised by the opt-in semantic-session host, but its protocol and
request-lifetime behavior still need an end-to-end control. Ordinary one-shot CLI
compilation continues to recollect. Do not treat a body hash, schema check, or
structural validation alone as a substitute for session provenance.

### Typed semantic query graph status

`IncrementalSemanticSession` now contains a typed query-node and bidirectional-edge
scaffold, but it is not a production dependency graph yet. The only current
`incremental_semantic_query_*` definitions are in
`src/semantic/incremental_function_facts.elisa`; semantic collection and checking
have no call sites that record dependencies or consume graph results. These
operations are private while their lifecycle is incomplete. They cannot read or
commit input/result fingerprints or mark a recomputed query Green, so the scaffold
cannot authorize semantic reuse. Its invalidation operation marks the full reverse
closure Dirty and cannot stop propagation when an intermediate result is unchanged.

Graph admission now caps owned key bytes at 8 MiB, query nodes and their possible
hash-index entries at 65,536, edge slots and free-list entries at 262,144 each,
and one replacement input at 4,096 dependency IDs. A conservative logical-storage
estimate also caps retained graph data at 32 MiB, including estimated index,
edge, and free-list overhead. New-query admission returns the sentinel and
dependency replacement returns `false` before changing graph contents when a cap
would be exceeded; replacement includes the temporary free-list peak in its check.
The estimate uses logical counts for the graph pools and the retained capacity for
the reusable worklist. `darray` and dictionary allocators can round other capacities
above those counts. In the long-lived session region, non-tail `darray` growth can
also leave old backing buffers allocated until region teardown, so the 32 MiB value
does not bound total retained region bytes across growth generations. This is an
admission bound on estimated payload, not a hard process-RSS limit. Before adding a
production caller, measure/account the graph region's retained bytes or use fixed-size
chunks with a hard capacity.
Each query node carries a u64 invalidation-generation stamp, and the session reuses
a worklist whose retained capacity is included at 8 estimated bytes per slot. The
worklist grows with the reached reverse closure and is reused by later edits; only
generation wrap clears all node stamps. This avoids per-edit O(V) visited-array
initialization and full worklist reservation.

The dense query-node record now keeps status, adjacency handles, and its invalidation
stamp ahead of the wide key spans and fingerprints. Under conventional 64-bit struct
alignment, the current field sequence is estimated at 64 bytes per node; the committed
pre-generation layout is estimated at 56 bytes, so the generation stamp adds 8 bytes.
These are source-level estimates, not a measured Elisa layout or speedup. The graph
still has no semantic callers, so profiling it should wait until an evaluate/commit
path exists.

The checked Zig revision's `AnalUnit` is a packed 64-bit kind/ID handle. Its
`DepEntry` uses a 64-bit depender handle and three 32-bit links; the dependee
identity is implicit in the typed dependency-head map. Elisa stores two 32-bit
query endpoints and three 32-bit links per edge (20 bytes by source layout). The
outgoing dependency chain is singly linked because replacement removes the whole
chain; the incoming depender chain stays doubly linked for O(1) unlink. Admission
estimates 48 bytes per edge slot for alignment headroom. Zig's layout remains a
useful alternative if Elisa introduces a typed dependency table. When callers
exist, measure edge and index capacity plus replacement and invalidation costs
before changing the representation. The source-level comparison and references are in
[`compiler_incrementality_reference_study.md`](compiler_incrementality_reference_study.md).

Before using this graph for reuse, add a session-owned evaluate/commit boundary
that validates exact inputs and dependencies, records the canonical result, and
marks a query Green only after a successful commit. A dependency-set change dirties
that query for reevaluation. After commit, propagate dirtiness to reverse dependers
only if the canonical result fingerprint changed; an unchanged result should stop
propagation. Query handles also need session/generation validation, since the current
bare indices can alias across sessions or after reset.
Dependency deduplication still uses nested scans; the 4,096-ID per-query admission
cap bounds that work, but a future real caller should measure it. Any overflow or
graph corruption must discard the graph and take the cold path. Until these
boundaries have semantic callers and parity controls, describe this as scaffolding only.
Graph reuse must also be tied to a successfully committed semantic context. A failed
snapshot store can leave the prior query graph allocated, and key lookup currently
checks only whether the session is enabled. A future request must stage graph changes
under its new source generation and publish them only after snapshot commit, or poison
the prior graph before any lookup and cold-rebuild it on failure. Checking only the
snapshot's current valid bit is insufficient if graph updates begin before commit.
Sparse and dense invalidation closure costs remain unmeasured, as do
dependency-deduplication alternatives.

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
Global-permission enforcement enabled, the same current-source fact pass also
replaces the local-name, Global.Read/Write, and direct-call collectors for eligible
top-level functions. Zero-fact records contribute false direct bits; flat
fact-bearing bodies without local bindings project their direct read/write facts
and call edges. Their function slots remain so closure and effect-row publication
still include the complete declaration set. Bodies with local bindings, nested
control flow, or nested declarations stay cold. The direct checker control enables
Global-permission enforcement, compares canonical rows, and asserts axis-scan
counters; the CLI control enables it with `# globals` and asserts the same counter
alongside the other pass counters. Runtime parity for these updated controls is
still pending a fresh Stage1 product. LLVM fragment loading remains a separate
later stage.

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

The backend/server suites, targeted race/concurrency tests, native O0/O2/O3
parity, LLVM boundary guards, debug relocation and anonymous-unit controls pass.
Read-only overlays excluded unrelated loop-proof changes; these checks do not
qualify verifier changes in the shared commit. Matching code and script hashes,
compiler hashes, raw samples and overlay sources are preserved in
`build/verification/incremental-native-final-20261018/` in both repositories.

Instruction-weight shard boundaries and complete declaration inventories remain
sensitive to large body edits or declaration insertion/removal. Those workloads
need explicit locality measurements and stable-placement work. General semantic
replay, avoiding complete LLVM generation/optimization, persistence, normal CLI
integration and representative edit-to-executable qualification remain required
for the full professional incremental-compilation goal.

## Self-host bottleneck review (2026-10-18)

The recorded Stage1 self-host profile puts semantic checking at 46% of samples,
LLVM IR construction at 39%, and O0 object emission at 4% (`docs/build-speed-notes.md`).
This sets the work order: semantic-result and body-IR reuse can address the dominant
repeated work; a native-object cache alone cannot. The Core compile-server cache
still helps object-heavy requests, as its source-to-object measurements above show,
but it does not skip frontend analysis or current-module construction.

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
stderr. The parsed tree and its source live in a request region. The host keeps
one reusable line-map buffer, and an identical map preserves the lexer's parsed
lookup tables. Only the opaque semantic session survives between requests.

This first host reuses the existing validated function-fact path for an exact
repeat or a source edit. In the trusted in-process session only, it also reuses
complete self-assignment findings for supported top-level function bodies and
rebinds their target and statement locations against the fresh token stream.
Unsupported bodies and decoded disk snapshots keep the ordinary checker path;
the portable sidecar codec does not serialize these lint facts. The report's
`self_assignment_bodies_scanned` and `self_assignment_bodies_reused` fields count
those per-body scans and reuses separately from authority facts. This does not
yet retain parse trees, skip parsing, record/replay tracked semantic query
results, or reuse LLVM/native artifacts.
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
are rendered against the current source. The source, expanded text, tokens, AST,
generated text, and other request buffers live in a request region. A single
semantic session survives up to 32 compile requests; the host then ends that
session region and starts a cold session to release retained arena storage.

The shared request routine is also used by one-shot `main`; its three normal
semantic-gate callsites receive an explicit session reference. One-shot compilation
uses a disabled session, preserving disk-sidecar behavior. Repeated compilation
uses the retained in-process session for validated function facts and self-assignment
findings, then still runs current semantic checking, LLVM IR generation, optimization,
and artifact emission. It does not reuse parse trees, semantic query results, LLVM
modules, or native objects. LLVM object, IR, bitcode, executable, wasm, and Python
extension requests dispose their builder, module, target data, target machine, and
context before the next request. `check` and `edir` return before creating LLVM state.

The first host supports `check`, `obj`, `llvm`, `bc`, `exe`, `wasm`, `pymodule-so`,
and `edir`. It rejects stdout report modes so the status protocol stays readable;
project-target subcommands and `c-archive` are not wired into this session boundary.
The wrapper preserves stdin for this mode and applies its usual process memory guard.
This source change has only had static review so far; no build or runtime control has
qualified it, so it makes no performance claim.
