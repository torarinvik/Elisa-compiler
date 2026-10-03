# Typestate cleanup: implementation and release gates

This work is shared with Stage0's `codex/wasmbrowser-typestate` branch. Both
worktrees were fast-forwarded from `origin/main` before implementation. This
document distinguishes the target design from capabilities actually verified.

## Target model

`T[State]` has one surface spelling and two distinct sources of authority:

- **Protocol states:** construction and legal, implemented transitions establish
  the state. No field predicate and no synthetic mutable discriminator is needed.
- **Derived states:** pure predicates establish the state from values. A type
  annotation cannot contradict the fields; mutation must re-establish the
  predicate or invalidate the refinement.

Initially these modes must be exclusive for a state family. A transition graph
authorizes a state edge, independently of function names; it is not an implementation of resource acquisition,
release, publication, or any other effect. The legacy generated tag-writing
functions must not become the authority for the new protocol mode.

State identity must include the resolved owning declaration and module. Matching
only a string such as `Open` is not sufficient. Ownership, borrowing, nullability,
and protocol state remain independent facts.

## Delivered foundation

- Contextual constructors cannot contradict their destination's derived state.
  Stage0 already enforced this; Stage1 now has the corresponding check.
- Named derived-state construction, return values, and readonly borrows lower to
  the ordinary struct representation. Backend erasure requires an exact existing
  `(owner, state)` predicate; it does not erase arbitrary unknown brackets.
- `for` exit facts include the zero-iteration path, as `while` exit facts already
  did. A body transition cannot unconditionally establish the exit state.
- Match arms start from the same incoming facts, not the preceding arm's state.
  Their exit facts retain a singleton only when all arm results agree.

These are targeted fixes, not a claim of complete typestate soundness. In
particular Stage1's current flow abstraction is still singleton-or-diverged, not
a general state-set analysis over resolved places and aliases.

## Implementation sequence

### 1. Explicit state-family metadata

Introduce resolved state-family IDs, protocol/derived mode, declared states,
construction authority, function-independent transition edges, and terminal states in
both compilers. Replace protocol sentinel annotations with structured metadata;
retain a compatibility adapter for legacy syntax until its users migrate.

Required negative controls: duplicate states/edges, unknown endpoints,
foreign-family states with the same spelling, ambiguous module lookup, and
mixing protocol authority with derived predicates.

### 2. Classic construction and consuming transitions

Support predicate-free state families with a function-independent graph:

```elisa
affine struct File[state Closed | Open]:
    handle: i64
    transitions:
        Closed -> Open
        Open -> Closed
```

Stage0 now implements this first subset. The first declared state is the initial
construction state. Construction and `transition[Open](move file)` are restricted
to the existing owning-module privacy domain (including child modules). Root-level
declarations share a namespace; libraries requiring encapsulation must use a module.
No functions are synthesized or named by the graph. Preservation needs no self-edge.
Any independently implemented function within the authority domain can use an edge.
Consuming transitions require linear/affine ownership and an explicitly moved local
or parameter. A copied plain struct may declare a graph but cannot use the intrinsic.
The payload is transferred unchanged; external effects remain separate obligations.

Stage0 rejects target-state construction, direct and nested inline `zeroed`, missing
edges, missing moves, unknown targets, old-owner reuse, and post-move borrowed aliases
in targeted tests. LLVM lowering checks identical payload field types before
reconstructing the destination aggregate; unsupported representations fail closed.
Stage1 still rejects predicate-free named families. This is not a parity release;
Stage1 must acquire equivalent structured metadata and enforcement before enabling it.
Broader alias, control-flow, cross-module, and generic negative controls remain gates.

Stage1's parser now preserves structured `StateFamily` and `StateTransitionEdge`
rows in `Ast::File`, keyed by owning module, declaration name, and declaration
position. Edges retain the owning declaration's byte offset as well as its line;
line numbers alone are not canonical identity. The semantic loop-view copy preserves both tables. Its transition block
parser creates no operation declarations. An executable self-hosted parser probe
checks state order, affinity, both edges, unchanged declaration count, metadata
preservation, and two same-named families in distinct modules. This is parser
infrastructure only: the missing-derive guard and unsupported-intrinsic errors
remain until Stage1 ownership, construction authority, graph checks, provenance,
and backend lowering are implemented together.

Stage1 now also has a structured graph-validation pass, invoked on the semantic
loop view. It checks nonempty families, duplicate states, unknown edge endpoints,
duplicate edges, derived/protocol mixing, and edges without a named family. The
paired graph-validation gate requires the intended diagnostic and semantic exit
status; the old missing-derive rejection alone does not count as validation.

Symbol collection now resolves state-family metadata to existing `DeclId` rows,
requiring a unique struct with matching module, name, line, and byte offset.
Resolved edges carry that same declaration ID and their immutable source-row
index. Detached metadata without its declaration produces an explicit error and
no resolved family/edge authority. The metadata executable checks distinct IDs
for two same-spelled module families, edge-to-family IDs, and the detached control.
This is declaration resolution, not state-qualified alias lookup or ownership.

The resolver now records `BindingDeclaredType` rows for function parameters and
annotated locals: lexical `BindingId`, declared structural `type_id`, complete
annotation AST, module, and source position. Keeping the original annotation
preserves state arguments, `lmut`, and qualified alias spellings even when
structural interning erases qualifiers. The probe checks those retained forms;
they are not themselves resolved state identities or transition authority.
The initializer is resolved before the new local binds, and
branch-scope reference resolution retains existing distinct binding IDs. A
self-hosted probe checks inner shadowing, restoration of the outer owner, same
spelling in a second function, and distinct state-qualified/ref type shapes.
Each row also retains explicit borrow access, writable-borrow access, `lmut`, and
binding mutability independently of the structural type ID. Capability inspection
peels only outer wrappers: references inside container element types do not make
the container itself borrowed. The probe checks readonly/writable references,
`lmut` versus an owned value with the same erased type ID, a mutable owned value,
and a container of references. These are declared syntax facts, not yet ownership
authority: inferred bindings and nominal alias capabilities remain required
before consuming transitions use them.

Symbol collection also preserves complete `TypeAliasDeclaration` targets under
canonical `DeclId`, owning module, and source position. The older bare-target
tooling columns remain unchanged. The binding probe checks reference and `lmut`
state-qualified targets in same-spelled aliases from different modules and an
alias-to-alias target. This prevents irreversible capability/state information
loss. The binding capability channel now follows lexical and qualified
alias chains in the alias declaration's module and retains the terminal nominal
`DeclId`. References and `lmut` remain borrowed through the chain. Cycles,
equal-rank ambiguity, missing targets, depth exhaustion, selective-import lookup,
and generic-alias applications return `known: false`, never owned authority.
The executable probe checks separate module families, qualified uses, a cycle,
and duplicate same-scope aliases. Qualified lookup also searches enclosing module
ancestors, preferring the nearest matching module/member and enforcing separator
boundaries. It reuses the existing module-path matchers rather than allocating a
joined qualifier. Controls distinguish root, parent, and inner sibling aliases
and an `OuterKit` prefix collision. Qualified module aliases now select the nearest
lexically visible `using ... as ...` declaration. Target metadata must agree on
scope, line, and byte offset; duplicate aliases or targets remain unknown. Target
modules resolve relative to the import's declaration scope before absolute root
fallback, and remaining path segments stay under that selected module. Executable
controls cover inherited imports, local overrides, separate sibling imports,
unrelated and prefix-colliding modules, duplicate aliases, nested paths, and
relative target precedence. Selective `using Module::Type` and `from Module import
Type` records now preserve lexical scope and individual token offsets. Capability
lookup pairs member/source records by scope, line, and offset, resolves the source
module in the import's scope. Non-root lexical declarations take precedence;
visible imports form a combined lookup tier before root fallback. Conflicts,
duplicate target declarations, and missing source metadata remain
unknown; repeated imports of the same declaration do not invent ambiguity.
Controls cover multiple members and sources on one line, inherited imports,
nearer local declarations, sibling isolation, conflicting sources, and relative
module precedence. A sparse import-only table prevents per-binding scans of the
complete fields/effects/generics annotation stream. Wildcard imports now use an
explicit scoped marker, distinct from module aliases. Resolved wildcard modules
without the requested member contribute nothing. Controls cover multiple wildcard
sources, inherited imports and conflicts, sibling/prefix isolation, lexical
precedence, repeated imports, and the absence of unqualified leakage from aliases.
Chained module-alias targets and generic substitution still need implementation; this
channel does not yet authorize moves. Older file-wide import lists are deliberately
not ownership evidence.

Each declared binding now also carries `BindingStateIdentity`: a canonical family
`DeclId`, state ordinal in that family's declaration, and protocol/derived mode.
The full semantic-check and reference-resolution paths populate resolved family
metadata before binding resolution, not only declaration-only symbol collection.
Single named-state applications resolve through qualified/imported type heads and
non-generic alias chains in each alias's declaration scope. Explicit reference and
`lmut` wrappers preserve state identity without changing their borrow capabilities.
Unknown states, duplicate occurrences of the queried state, cycles, unqualified
bare families, unrelated containers, and unsupported generic/union applications
remain unknown. These records identify annotations; they do not certify graph
validity, establish runtime state, or authorize consuming transitions. Executable
controls distinguish state ordinals, same-spelled families across modules, imported
aliases, qualified construction types, outer borrow wrappers, and negative cases.
Files with no resolved state families return unknown immediately, avoiding a second
nominal/import traversal of every ordinary binding in self-hosted compiler builds.

Explicit move operands now have `ResolvedBindingMove` source records produced by
the lexical resolver. Whole-local identifiers, including parenthesized identifiers,
retain their resolved `BindingId`, move span, and operand span. Shadowed names and
same-spelled parameters in different functions cannot collapse to one owner.
Projections, complex expressions, unresolved names, and depth exhaustion retain an
unresolved record with no binding authority rather than guessing a root. Borrowed
parameters can have resolved move records without becoming legal consuming inputs.
These records are source occurrences, not an execution trace: branch/loop joins,
implicit consumption, partial places, borrow invalidation, and legal-move decisions
still require ownership flow analysis. The existing name-based affine checker is
not replaced or weakened by this metadata channel.

`ownership_flow_domain.elisa` defines the Boolean components for possibility-set
joins (OR), knownness joins (AND), and the liveness portion of move eligibility
(`known and may_live and not may_consumed`). Its complete truth tables execute
inside the binding regression. Borrow exclusivity, affinity, matching BindingIds,
state legality, and reachability are separate caller obligations; this module is
not yet integrated into a control-flow ownership checker or transition admission.

`test/proofs/ownership_flow_domain.elisa` imports that exact implementation rather
than a copied model. The Boolean-domain proof is now **admitted: 32/32 obligations**,
with 32/32 independently replayed certificates, zero semantic errors, and no trusted
assumptions. All three implementation bodies and thirteen client laws verify,
including associativity, commutativity, idempotence, identity, and consumed/unknown
input denial. Seven false claims reject at their postconditions. The admission gate
checks repeated reports, source/product hashes, all function-summary statuses and
complete replay. This admission applies only to this Boolean domain, not binding
resolution, ownership flow, borrow invalidation or transition code generation.

Coverage progressed through 19, 24 and 25 obligations before bounded same-operator
join normalization and void-return summary rewriting closed the remaining seven.
The original postconditions remain unchanged; proof bodies explicitly evaluate
the pure calls needed for their verified summary facts. Search and kernel replay
independently compare flattened witnessed atom sets, rejecting mixed operators,
numeric literal leaves, missing witnesses and fuel exhaustion. Formation precedes
constant absorption, so malformed operands cannot be erased by a neighboring
constant. No proof-analysis budget was increased or foreign axiom added.

This probe exposed a separate self-hosting diagnostic defect: raw-reference
classification consulted an outer structural type row through an intentionally
unknown loop/pattern binder. It now honors the scoped-binder sentinel, matching
the inference walker. Paired controls accept the inner `sview` loop item and still
reject the restored outer `u8&` as a string argument after the loop. This is a
scope-classification fix, not proof of complete loop-element ownership typing.

The remaining transition implementation must track values by existing lexical
`BindingId` and resolve qualified/imported type uses and aliases to the family
declaration ID. Do not extend
the legacy function-name/sentinel protocol checker: its bare-name tracking is not
adequate for shadowing, independent operation names, or module-separated families.
State-qualified types need structural type identity through calls, returns,
containers, and references, followed by owner consumption and borrow/provenance
transfer. Constructor authority, nested zero initialization, record updates,
casts, and reference projections need negative controls before relaxing the guard.

Start with owned, consuming transitions. Accept the declared source state only;
consume the old value; establish the target on every successful exit. Reject
arbitrary target-state literals, annotation laundering, unauthorized transition
authority, old-value reuse, surviving aliases, and graph edges without checked
implementations. State declaration must not permit forging native resources.

### 3. Place-based control flow and exclusive borrows

Use scope-resolved places rather than bare local names. Track possible states
through branch joins, loop fixed points, nested expressions, match bindings,
shadowing, early return, break, continue, and exception paths. A call requires
validity for every possible incoming state unless an explicit narrowing occurs.

For borrowed transitions, require exclusive mutation and invalidate every alias
whose view would otherwise retain the old state. Opaque calls invalidate state
facts unless an explicit trusted boundary contract restores them. Contracts
must be checked against callee bodies, not merely propagated to callers.

### 4. Derived-state hardening

Check contextual construction in returns, arguments, nested fields, and record
updates, not only local declarations. Ensure predicates are pure and well-defined;
check coverage/overlap according to the specified state-set semantics. Unknown
field mutation or opaque effects must not silently preserve a singleton.

Do not interpret an unknown predicate as true. Do not give protocol transitions
authority to override derived-state predicates.

### 5. Fallible operations and terminal obligations

Each outcome needs a checked state contract: success, failure, early return, and
cleanup. Verify terminal obligations on all exits. Test zero iterations, repeated
iterations, partial transition failure, and resource escape through aggregates.

### 6. Deprecate positional aggregate-slot syntax

Inventory `T[&]`, `T[!]`, and `T[?]` uses. Specify explicit nullability/refinement
replacements, preserve their guarantees, add compatibility diagnostics, migrate
libraries and compiler sources, then remove the syntax. These markers are not
protocol states and must not be mechanically converted into named states.

### 7. Proofs and WasmBrowser dogfooding

Prove the state-set join/transfer properties, construction non-forgeability,
transition preservation, and alias invalidation alongside implementation. The
proof assistant's missing features are implementation work, not a reason to admit
an unproved claim. Tests and compiler acceptance are not kernel proofs.

Start WasmBrowser migration with cache/catalog transactions and native-resource
lifecycle boundaries. Preserve existing value, FFI, and runtime gates; add
negative compile tests and runtime controls for each migrated lifecycle. A
protocol-state proof alone does not prove filesystem durability or OS behavior.

## Current regression gates

- Stage0: `go test ./src/parser ./src/semantic -count=1` from `compiler/`.
- `test/parity/protocol_graph_stage0_smoke.sh`: Stage0-only graph round trip,
  independent operation names, tag-free layout, and execution at O0/O2.
- `test/parity/protocol_graph_metadata_smoke.sh`: self-hosted Stage1 metadata
  execution and retained semantic rejection; not a transition-acceptance gate.
- `test/parity/protocol_graph_validation_smoke.sh`: paired declaration-level
  graph rejection controls, independent of the unsupported-transition guard.
- `test/parity/typestate_binding_identity_smoke.sh`: lexical binding/type-record
  controls; not a state-transition or full ownership-soundness gate.
- `test/parity/binding_loop_string_shadow_smoke.sh`: paired raw-reference/string
  boundary controls across loop shadowing and restoration.
- Stage1: a fresh seed from this Stage0 worktree, never a stale product bypass.
- `test/parity/typestate_foundation_smoke.sh`: paired semantic positives and
  negatives, complete LLVM emission, and named-state executables at O0/O2.
- `test/parity/linear_typestate_codegen_smoke.sh`: existing legacy behavior.
- `test/parity/generic_builtin_state_identity_smoke.sh`: distinct builtin state
  identities and rejection of runtime storage of phantom state tokens.

The broader `diagnostics_diff.sh` gate is **not green**: the final 2026-10-03 run
reported 104 missing/changed Stage0 messages. The constructor-mismatch wording
now agrees. Three new legacy-flow negative controls still receive Stage1's
state-focused message rather than Stage0's complete argument-type wording.
Other failures include ownership and lifetime diagnostics. No baseline comparison
has established attribution for the whole corpus; do not label all remaining
failures pre-existing or claim full diagnostic parity from the focused passes.

New features require paired accepted/rejected programs and executable checks
where layout or lowering changes. A timeout or backend decline does not count
as a successful semantic rejection. Deprecation and dogfooding remain gated on
the guarantees above; neither is completed by the current foundation patch.
# Reachability-aware ownership joins

The Boolean domain now provides `join_reachable_possible` and
`join_reachable_known`. Dead predecessors contribute neither possible ownership
nor missing knowledge; two dead predecessors produce unknown/no possible owner.
Callers must still establish matching BindingIds and actual CFG reachability.
These helpers are not yet an ownership walker or transition admission.

`test/repro/ownership_reachable_join_probe.elisa` exhaustively checks all sixteen
Boolean input combinations against a branch-based reference calculation.
`test/proofs/check_ownership_flow.py` now requires 36/36 independently replayed
domain obligations and a separate 16/16 reachability report (shared imported
helper obligations overlap), with the seven existing false claims rejected.
The earlier 32/32 figures below describe the preceding admission milestone.

## BindingId-indexed fact operations

`binding_identity_types.elisa` now holds the single canonical DeclId/BindingId
definitions and `OwnershipBindingFact`; the semantic facade and standalone
native controls import those same types, not a test substitute.
`ownership_binding_flow.elisa` joins only matching IDs, fails closed on invalid
declaration IDs and cross-binding joins, excludes unreachable predecessor facts,
and consumes a live known owner once. Failed consumption leaves facts unchanged.
Serial zero remains valid, matching the actual resolver allocator. The two
Boolean identity helpers expose their actual field predicates as postconditions.

`test/parity/ownership_binding_flow_stage0_smoke.sh` checks actual fact operations
at O0/O2: shadow/function isolation, consumed/live branch join, dead branch
exclusion, all-dead joins, repeated consumption, and all sixteen consume inputs.
It also compares all 256 pairs of frontier facts against an independent
branch-based calculation. The fresh Stage1 product executes this probe too.
These record operations are not yet connected to the AST control-flow walker.
They do not establish borrow invalidation, affine type eligibility, state edges,
or legal native effects, and do not enable Stage1 consuming transitions.

`ownership_binding_identity.elisa` dogfoods the actual identity helpers. Its
producer proves 21/21 obligations but independent replay currently admits only
20/21: `serial_zero_is_valid`, which instantiates the summary with a nested
BindingId/DeclId record, remains OPEN. `check_ownership_binding_identity.py`
tracks that exact gap and explicitly reports `admitted: false`; it is not a
green admission gate. Fix the kernel replay gap before citing this client law
as proved. The separate Boolean domain admission gate remains fully replayed.
