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
authorizes an operation; it is not an implementation of resource acquisition,
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
construction authority, operation-specific transitions, and terminal states in
both compilers. Replace protocol sentinel annotations with structured metadata;
retain a compatibility adapter for legacy syntax until its users migrate.

Required negative controls: duplicate states/operations, unknown endpoints,
foreign-family states with the same spelling, ambiguous module lookup, and
mixing protocol authority with derived predicates.

### 2. Classic construction and consuming transitions

Support predicate-free `struct File[state Open | Closed]:` with an explicit legal
transition declaration. Final constructor/transition-body syntax is not shipped
by the foundation fixes above. Construction authority must be enforced before
removing the existing missing-derive diagnostic.

Start with owned, consuming transitions. Accept the declared source state only;
consume the old value; establish the target on every successful exit. Reject
arbitrary target-state literals, annotation laundering, unauthorized transition
functions, old-value reuse, surviving aliases, and graph edges without checked
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
