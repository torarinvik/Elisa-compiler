# Incremental compilation design

## Local implementation status (2026-10-10)

The design below describes the intended persistent semantic cache. That cache is
not enabled yet. Historical VAST timings are motivation, not the current local
baseline; qualification now uses local compute and pinned compiler/runtime tuples.

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

The existing function-fact collector and snapshot codec are included as prototype
APIs, but `semantic_api.elisa` does not call the collector. The portable authority
trace is independent of the production include path. Connecting either prototype
must replace authoritative work rather than add another body walk. The current
invocation event indices and AST positions need checked conversion to stable
declaration keys and body-relative anchors, followed by rebinding against the next
invocation's declarations before any persistent reuse can be admitted.

The next acceptance workloads must include unchanged rebuilds and edits to the
compiler itself, with cold/warm diagnostic, effect, and executable parity. Small
cross-language frontend/object timings do not prove incremental performance or
professional compiler efficiency across representative projects. Qualified gains
must be measured and integrated into main before they count as installed behavior.

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

In `src/semantic/semantic_api.elisa`, `collect_effect_sources` runs before `check_ungranted_panic`, and `check_mutable_global_authority` follows it. The panic checker and authority checker currently perform separate body walks. `check_mutable_global_authority` creates a fresh `GlobalAuthority`, collects declarations and lexical indexes, analyzes bodies through `ga_functions`, closes call/effect rows, publishes rows to `SymbolTable`, and walks bodies again to issue enforced diagnostics. Its numeric function slots, lexical scope numbers, AST nodes, offsets, and interned references are invocation-local and cannot be written to disk as identities.

The compiler has content-addressed caches for a complete unchanged stage1 object build in `scripts/elisac_stage1.sh`, plus build/runtime object provenance helpers. Those caches do not help when one function changes because the object key covers the complete compile invocation. There is no persistent semantic-fact format today.

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

1. **Instrument the baseline.** On the exact compiler seed and VAST box, record phase wall/CPU time for `check_ungranted_panic`, `check_mutable_global_authority`, their combined interval, number of function bodies visited, number of resolved calls/edges, and current diagnostics/effect-row report. Do not infer the 993-second cost from unrelated historical self-host timings.
2. **Extract a deterministic collector.** Add stable key/dependency/fact types and make one body traversal produce the direct facts consumed by the current panic and authority checkers. Keep full semantic execution and compare its result against the pre-change behavior. This validates facts before introducing persistence.
3. **Persist body records and reuse on body edits.** Add a versioned sidecar cache, atomic writes, fail-closed misses, and counters for hit/miss/rejection reasons. On a changed body, collect only that function's facts, rebuild closure, and replay affected diagnostics.
4. **Prove invalidation.** Compare warm incremental output byte-for-byte with cold output for: unchanged build; a body-only edit with unchanged API; a callee body edit that adds/removes `Global.Read` or `Global.Write`; a callee effect-contract change; adding an overload after a previous lookup; changing an import or alias that resolves a previous miss; changing a global from immutable to mutable or changing its type/layout; changing a protocol method contract/conformance; changing strict/global options; and corrupting or versioning out the cache.
5. **Add body codegen fragments.** Cache and restore eligible `-O0` LLVM function bodies in a newly created module, then test link validity, object/executable parity, and invalidation for function API, type/global layout, callee ABI, target, and codegen flags.
6. **Expand eligibility and optimization.** Add callback/generic/debug support only with explicit fingerprints and controls. Consider cross-function optimized reuse only with an import/summary model and runtime parity evidence.

The semantic MVP passes only when warm and cold diagnostics, canonical effect rows, exit status, and source locations match exactly; a body-only edit demonstrably visits only changed/unsupported bodies in the paired passes; and edits to a dependency cause all required affected call checks to rerun. The codegen MVP additionally requires equivalent executable behavior and a valid verifier result after cached fragments are restored.

## First code patch boundary

The collector belongs at the current `collect_effect_sources` point in `check_full_into`: declaration, name, type, import, capability, and effect indexes have been built, while the resulting effect-source rows are still needed by `check_global_permissions`. It should replace that body scan and retain the snapshot for `check_ungranted_panic` and `check_mutable_global_authority`. This makes the first reusable artifact available before all three later consumers without moving global permission enforcement out of its current order.

The first implementation patch should stop after a deterministic in-memory collector exists; it should not add persistence or LLVM fragment loading in that patch. Suggested ownership:

- Add `src/semantic/incremental_function_facts.elisa` for `StableFunctionKey`, `Dependency`, `FunctionBodyObservations`, body anchors, and complete/cacheable status. Keep this schema independent of `GlobalAuthority` arrays and parser identity types.
- Add one collector entry point, conceptually `collect_incremental_function_facts(file, table, options, previous_snapshot?) -> IncrementalSemanticSnapshot`, called from `check_full_into` where `collect_effect_sources` currently runs. Initially `previous_snapshot` is absent and the collector traverses every body.
- Refactor the current authority AST visitor (`ga_expression`/`ga_statements`/`ga_functions`) to emit direct observations through that collector while preserving the existing row/diagnostic behavior. Feed its effect-source facts into `SymbolTable` before `check_global_permissions`; then teach panic/effect and mutable-global analysis to consume the same observations rather than rescanning bodies.
- Add a focused parity fixture/report test around `test/parity/global_permissions_smoke.sh` plus panic/trusted-filter cases. Compare the existing full checker result with rows/diagnostics produced by consuming the collected facts. Add the persistence cache only after this in-memory contract is stable.

Before enabling reuse for every function, record unsupported constructs and select a small, representative cacheable subset. Each later patch should expand the collector's supported syntax without weakening its fail-closed behavior.

### Driver source context boundary

The persistent semantic consumer must receive the source bytes, token stream, AST,
and explicit source-unit identity from the same frontend result. In the current
driver, `static generate` may replace all three analyzed inputs. The existing
`report_src_ptr`, `report_tokens`, and `report_source_len` track that expanded unit;
the original input remains the source of header-based checking options. These are
two distinct inputs to cache validation: expanded program identity and original
policy configuration. Passing the original token stream beside an expanded AST is
not a valid reuse context. Early pymodule semantic gates must observe the same rule.
An environment path alone does not attest either source buffer.

A bound record must also prove exact current body-token equality and current
source-declaration membership. Matching a path, name, definition offset, and token
range is insufficient when bytes changed at the same offsets or synthetic callable
rows entered the authority inventory. Invalid or ambiguous binding takes the cold
checker path before any stored effect facts are applied.
