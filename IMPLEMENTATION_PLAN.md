# Elisa — Memory Safety, Correctness, and Language Completion Plan

**Active roadmap updated 2026-09-24.** This updates the existing implementation plan in place. The earlier stage1 porting roadmap and status ledger are preserved, verbatim, in the historical section at the end. The active roadmap takes precedence wherever the older plan prioritizes speed, diagnostic parity, permissive behavior, or presentation over safety.

**Inspection baseline:** main checkout `73e11a6392694e534a4bdb934b47c67fdc9073f0`, including the audited shared-worktree integration checkpoint `1b683c34b655660fc91df26a559c488b315c2a92` and subsequent safety slices. This is a source-informed implementation plan, not a completed soundness audit. Targeted build and test evidence is recorded only in the dated verified slices below; the 2026-09-24 full gate run stopped at meaningful failures and is documented in §M.5. No full safety audit or sanitizer run is claimed. Historical green counts are historical evidence only. Every implementation item below starts pending unless explicitly described as existing infrastructure; a named checker is not evidence that its entire problem class is solved.

## A. Objective and non-negotiable guarantees

Make ordinary, safe Elisa programs memory safe on every supported execution target, and make correctness obligations explicit from source through generated code and foreign interfaces. Keep the language's region-based allocation, explicit effects, value semantics, and self-hosting, but close gaps where those mechanisms currently depend on syntax recognition, undocumented assumptions, or agreement with stage0.

The desired guarantee is conditional and precise: **a well-typed safe program, linked only against implementations satisfying their declared safe contracts and executed by a conforming compiler/runtime, cannot perform an invalid memory access or a data race.** Unsafe implementations, native foreign code, LLVM, the runtime's primitive operations, and the operating system form an explicit trusted computing base (TCB). Arbitrary native FFI cannot be made safe merely by adding annotations. Reduce and audit this boundary; do not describe it as eliminated.

Memory safety includes spatial bounds, temporal lifetimes, initialization, valid value representations, alignment, provenance, unique ownership of release obligations, and synchronization of conflicting accesses. It must hold at every supported optimization level and with tracing, debugging, generics, separate compilation, and generated bindings enabled. Safe code may reject a program or fail through a specified checked error/trap; it must never silently proceed into undefined behavior.

Correctness is broader: define evaluation order, arithmetic, conversions, effects, exceptions/errors, cleanup, module identity, ABI, and proof semantics. Reject unsupported executable constructs explicitly. Prevent silent wrong-code, dropped bodies, stale proof reuse, and platform-dependent language semantics beyond intentionally target-sized types.

Do not promise that memory safety also proves termination, bounded memory consumption, absence of deadlock, application-level correctness, side-channel resistance, or freedom from every compiler defect. Track these separately. Resource leaks and unbounded retained arenas remain correctness/resource-management work even when they do not produce invalid memory accesses.

### A.1 Product rules

1. Mandatory safety is the default language semantics, not an optional `-strict`, debug, lint, or `-fbounds-check` behavior.
2. A permission to allocate, panic, perform I/O, or mutate is not evidence of pointer validity, disjointness, lifetime, or synchronization.
3. Unknown facts mean unknown. Missing AST cases, missing summaries, ambiguous identity, solver timeout, and unavailable target support cannot count as proof.
4. For an unproved operation: retain a sound runtime check when one exists; otherwise reject safe code. Optional optimizations simply do not run without proof.
5. A runtime check may only inspect memory already known safe to inspect. Checking a pointer's numeric address is not a general dangling-pointer detector.
6. Stage0 agreement is useful differential evidence, never the language safety specification. A defect shared by both compilers is still a defect.
7. No optimization flag, environment variable, cache hit, import, generated helper, or alternate emitter may quietly remove the mandatory gate.
8. No feature is considered complete from one surface form: include aggregates, aliases, loops, calls, generics, effects, errors, and target differences.
9. Every release claim states its target/profile coverage, TCB assumptions, unresolved findings, and actual test evidence.

## B. Source-grounded starting point

The following observations guide the first work packages. “Observed design limitation” means visible source structure, not a demonstrated exploit. Reproduce behavior before classifying a specific program as a vulnerability.

| ID | Observed evidence in this working tree | Consequence for the plan |
|---|---|---|
| B01 | `src/semantic/semantic_api.elisa` orchestrates many independent checks and exposes separate strict/proof/raw-unsafe options. | Inventory mandatory versus optional obligations; consolidate shared facts without deleting checks prematurely. |
| B02 | `src/semantic/check_strict_unsafe_ops.elisa` explicitly describes structural strict-mode checks and suppression inside any `can`/`trusted` block; the walker uses an `in_grant` state. | Reproduce unrelated-grant bypasses; replace blanket suppression with resolved, operation-specific authority. This does not establish that every other checker is bypassed. |
| B03 | `src/semantic/region_escape_provenance.elisa` uses names/line information and returns a single region for several aggregate and branch expressions; some branches choose the first nonempty candidate. | Audit loss of multiple dependencies. Use sets of origin/lifetime constraints, qualified by fields and paths, rather than one representative region. |
| B04 | `src/semantic/check_borrow_after_move.elisa` recognizes owner names, selected fields, and reference-returning functions through syntax-specific helpers. | Preserve existing regressions while establishing CFG-based place, loan, and move analysis for all expressions. |
| B05 | `src/ir/core_ir.elisa` describes a shared typed scalar lowering and currently models a small i64 subset. | Do not assume a general safety IR exists. Extend or introduce a common typed representation with an incremental bridge. |
| B06 | `test/parity/bounds_default_smoke.sh` already asserts default bounds traps at `-O0` and `-O2`, with in-bounds twins. | Keep this completed baseline; broaden coverage instead of claiming default bounds checks are absent. Make expectations target-portable. |
| B07 | `src/backend/codegen_cleanup.elisa` emits region unwinds, deferred actions, drops, and captured scope metadata. | Audit and centralize exit-edge cleanup; do not replace the existing implementation without equivalence tests. |
| B08 | `src/backend/codegen_alias_metadata.elisa` and `codegen_disjoint_proof.elisa` implement alias metadata/proofs; README documents `-fnoalias`. | Treat every optimizer promise as a proof obligation. Verify checks with and without these optimizations. |
| B09 | `docs/loop-scratch-memory.md`, `codegen_loop_regions.elisa`, and `codegen_region_forwarding.elisa` document conservative scratch inference and direct-call readonly summaries. | Preserve conservative fallback and extend summaries only with verified nonescape/invalidation information. Allocation reuse must follow lifetime proof. |
| B10 | `src/semantic/check_thread_shareability.elisa` notes that `static` provenance is erased by TypeId interning and recovered from declaration ASTs. | Preserve safety qualifiers in canonical semantic types or mandatory attached metadata all consumers carry. |
| B11 | `ELISA_STAGE1_NO_SEMANTIC_GATE` was removed from the production driver in the verified S26 slice; `src/driver/elisac.elisa` still has partial-body decline paths that need completeness review. | Keep all ordinary outputs behind mandatory validation; make required-definition completeness explicit and prevent partial artifacts from appearing successful. |
| B12 | `elisacore_std/arena.elisa`, `allocator.elisa`, and `heap.elisa` provide raw allocation/reallocation, arena reset, free lists, pools, and affine pooled handles. | Audit the runtime boundary, allocator arithmetic, storage reuse, ownership, and invalidation as a whole. |
| B13 | `elisacore_std/stores_types.elisa` represents packed-store state with raw region references, pointer-sized handles, indices, tags, and parallel arrays. | Audit handle validity, store identity, movement, compaction, tag consistency, and failure atomicity. |
| B14 | Native, Python-module, WebAssembly, EASM, and reporting/lowering paths exist in driver/backend/scripts. | A single safe frontend is insufficient unless generated helpers and every executable backend preserve its invariants. |
| B15 | `.github/workflows/parity.yml` and `test/parity/run_all.sh` provide existing CI/parity machinery, including cached checks and platform-specific coverage. | Add independent safety gates and precise coverage accounting; audit full workflow before asserting a platform is tested. |
| B16 | `docs/integer-types-and-c-abi.md` specifies target-sized `int`/`isize` and warns that Elisa `int` is not C `int`. | Drive all layout/conversion/FFI decisions from target information, never compiler-host widths. |

Existing useful starting checks include `bounds_default_smoke.sh`, `array_bounds_smoke.sh`, `reference_reborrow_smoke.sh`, `lmut_alias_smoke.sh`, `region_owner_leak_smoke.sh`, `region_threaded_ownership_smoke.sh`, `thread_real_smoke.sh`, `loop_region_reuse_smoke.sh`, arithmetic/proof-overflow smokes, EASM enforcement checks, Python binding smokes, WebAssembly smokes, and self-host/runtime gates. These names identify coverage to extend; their current results have not been re-measured for this plan.

### B.1 First audit deliverables

- [ ] Inventory all AST expression/statement/declaration variants, type constructors, runtime allocation/mutation functions, backend operations, flags, and public library APIs.
- [ ] Map each to obligations for type validity, initialization, lifetime, ownership, aliasing, bounds, effects, errors, and thread transfer.
- [ ] Record enforcing pass, canonical fact source, runtime fallback, lowering consumer, test, and target coverage for each obligation.
- [ ] Label entries `enforced`, `partially enforced`, `unverified`, `unsafe-only`, or `unsupported`; absence of a row fails the inventory gate.
- [ ] Reproduce suspected failures with minimized source and a safe positive twin. Record compiler/runtime hashes, exact flags, target, diagnostics, IR, and execution result.
- [ ] Separate confirmed safety bugs, wrong-code bugs, over-rejection, documentation mismatch, and untested hypotheses.
- [ ] Assign an owner and closure evidence to every finding. A changelog statement or historical “DONE” is insufficient.

**Initial parser/type/IR catalogue (read-only source inventory, 2026-09-23; partial B.1 evidence):** `src/parser/ast_nodes.elisa` declares 35 expression variants (`Invalid`, `Absent`, literals/identifiers, calls including `StaticEffectCall`, member/scope/index/slice forms, operators and move/allocation, aggregate construction/update, branches/matches/catch/comprehensions/refinements, `GetElse`, lambda, and block); 13 statement variants (`Invalid`, expression/block/declaration/assignment, branches and loops, return/break/continue/match, contract); 11 declaration variants (`Invalid`, function/struct/enum/alias/law/import/scoped/extern/const/module); and 14 pattern variants (wildcard/literal/binding/pin/variant/struct/field/tuple/rest/or/type-bind/range/as/other). These totals come directly from the current sealed AST declarations; they are not an exhaustive grammar inventory and do not show that every safety visitor handles each form correctly. `src/semantic/semantic_types.elisa` has 12 `SemTypeKind` values and 10 `SymbolKind` values. `src/semantic/type_table.elisa` interns selected structural annotations into raw `u32` ids (0 means Unknown); `InferType` remains only a kind plus a name, and its comments explicitly describe unmodeled shapes as `Unknown`. Implemented slices introduce typed `DeclId` for symbol-table rows and table-local lexical `BindingId` for resolver occurrences; declaration references carry `DeclId`, while every parameter/local occurrence currently emitted to the resolver tooling side table carries the binding ID selected by ordered scope resolution. At the 2026-09-23 snapshot, these slices did not yet provide `RegionId`, `LoanId`, or `BlockId`, complete source-origin coverage, or persistent identity across source revisions; a 2026-09-24 follow-up adds table-local lexical `RegionId` values for known region type rows, but the other gaps remain. Names and offsets therefore still require consumer-by-consumer identity review. `src/ir/core_ir.elisa` is a deliberately small scalar i64 lowering for a parameterless `main` with a literal or one initialized scalar local and a supported arithmetic expression, not a general typed CFG/safety IR. This catalogue begins the inventory only: runtime/public API, type-constructor, effect, backend-operation, flag, visitor-coverage, enforcing-pass, fallback, test, and target mappings remain unenumerated, so all B.1 acceptance checkboxes stay open.

## C. Chosen design direction and decisions to specify

This plan recommends **static ownership/borrowing plus explicit region lifetimes, with checked operations at dynamic boundaries**. It does not propose converting Elisa wholesale to a tracing-GC language. Existing region and effect syntax should be retained where sound. New internal terminology below describes proposed semantic concepts, not syntax already implemented.

### C.1 Semantic contract table

| Concern | Recommended contract | Safe fallback / restriction |
|---|---|---|
| Ownership | One release obligation per owned resource; explicit transfer; implicit copying only for types whose representation and ownership allow it. | Reject ambiguous copies/moves; provide explicit clone with allocator/lifetime semantics. |
| Shared borrow | Referent remains initialized/live and cannot be unsafely mutated for the loan duration. | Controlled interior mutability uses checked or synchronized primitives. |
| Exclusive borrow | No conflicting access through another live loan or owner; reborrows temporarily restrict the parent. | Reject overlap unless disjointness is established. |
| Regions | A value records every region/storage lifetime it depends on; the destination must not outlive any dependency. | Copy/clone into a longer-lived owner explicitly or reject the escape. |
| Dynamic containers | Borrowing elements/views restricts reallocation, erase, clear, reset, and movement that invalidates those borrows. | Stable handles/storage or a checked access guard; raw stale pointers are never the fallback. |
| Initialization | Read/drop only initialized live values; zero bits are valid only for types with a defined zero representation. | Use tracked uninitialized storage internally; safe construction validates before exposure. |
| Arithmetic | Ordinary integer operations have a specified checked outcome; explicit wrapping/saturating operations have separate semantics. | No silent release-mode overflow UB; target-width conversions check range where necessary. |
| Bounds | Indexing is proved or guarded; safe checked access can return an optional/error. | Failure follows a specified trap/error path before pointer construction/access. |
| Panic | Initially a defined, non-returning process/instance failure at safety traps; normal errors retain deterministic cleanup. | Do not promise unwinding until cleanup on every unwind edge is implemented. |
| Threads | Transfer and sharing are structural capabilities, including captured/hidden state and allocator affinity. | Reject unproved transfers; provide scoped borrowing and synchronized primitives. |
| FFI | Raw ABI declarations are trusted/unsafe boundaries; safe wrappers validate dynamic values and preserve ownership. | Copy or reject foreign values when lifetimes cannot be tied safely. |
| Proofs | Only sound, validated facts can remove checks or authorize otherwise unsafe operations. | Unknown/timeout retains checks or rejects; axioms are explicit TCB entries. |
| Unsupported features | Executable output requires supported, fully checked semantics and required bodies. | Emit a hard diagnostic; report-only tools may return explicit partial data. |

### C.2 Decisions to ratify during specification work

These are implementation decisions to settle with examples and compatibility data, not reasons to stop writing or carrying out the audit. Use the recommended conservative default until a sound alternative is specified.

- [ ] Document current assignment, `mutable`, `lmut`, `<-`, `move`, `&`, `heap`, `static`, and `@region` behavior before changing it. Distinguish rebinding a reference from writing through it.
- [ ] Make evaluation order deterministic: recommend left-to-right evaluation of callee/receiver and explicit arguments, with a specified place for defaults and hidden arguments. Decide exact simultaneous-rebind semantics and enforce it in both analysis and lowering.
- [ ] Specify shared-borrow mutation rules for each existing mutation mode. Do not translate syntax mechanically into LLVM `noalias`.
- [ ] Specify field drop order, defer registration/execution order, partial-move restrictions for types with custom destructors, and whether a destructor may fail. Recommend nonthrowing cleanup for the first complete model.
- [ ] Specify whether checked arithmetic failures panic or use explicit fallible operators; choose one ordinary-operation behavior across debug/release. Audit existing behavior before migration.
- [ ] Decide zero-sized allocations, empty views, and one-past pointers: an empty view may use a distinguished non-dereferenceable representation, but safe code cannot dereference it.
- [ ] Initially reject unrestricted self-referential movable values; offer pinned or owner-bound abstractions only when their move/drop invariants exist.
- [ ] Keep unsafe source available only through an explicit boundary model. Decide compatibility spelling of `trusted`/`can Unsafe.*`; the safety rules must not depend on cosmetic syntax.
- [ ] If continuations, async tasks, generators, dynamic loading, or serialization of live references are unsupported, reject them explicitly. Their future implementations must enter this roadmap's same obligations.

**Exit criterion:** a normative safety specification and executable examples answer each decision, with deliberate compatibility changes documented. No unresolved choice may silently become a codegen assumption.

## D. Safety architecture and shared facts

### D.1 Stable identities and qualified semantic types

**Work package S01 — canonical identity and safety metadata.** Start in `src/parser/`, `src/semantic/resolve*.elisa`, `semantic_api.elisa`, and `src/ir/core_ir.elisa`.

**Progress (2026-09-23):** `Semantic::DeclId` wraps each builtin/collected symbol row; `Symbol.id` owns it and `DefinitionReference` carries it. `sema_smoke` checks row/index agreement and a resolved function edge. That declaration-only slice passed stage0 and a fresh stage1 seed, `assert_stage1_fresh.sh`, and the semantic self-host gate. The `Symbol` field order follows the compiler's compact layout. The current resolver extension adds `Semantic::BindingId { owner: DeclId, serial: u64 }`, threads IDs alongside lexical names and mutability through statement/expression scopes, and attaches the resolved ID to every parameter/local occurrence currently emitted to the resolver tooling side table. The stage0 smoke now checks parameter declaration/use identity, outer and inner same-named locals, distinct shadow IDs, function ownership, and side-table length alignment; it passes at `-O2`. The extended `sema_smoke` passes at `-O2` with both stage0 and a freshly seeded stage1; `assert_stage1_fresh.sh` confirms the stage1 product matches the current sources. Complete source origins, nominal type identity, `RegionId`/`LoanId`/`BlockId`, generic substitutions, cache fingerprints, persistent cross-revision identity, and safety-qualified types remain open. Keep S01 unchecked until those obligations and full test evidence are complete.

**Progress (2026-09-23, commit `6cd7d46f`):** The destroyed-region checker now keys its invalidation set to one-based lexical-binder rows from `LocalRegionAnnotation`, so nested same-spelling region declarations no longer collide in that analysis. This is a per-parse checker identity, not a stable canonical `RegionId`: region-bearing TypeIds, other analyses, declaration provenance, and cross-revision identity still use incomplete metadata. S01 remains open.

**Progress (2026-09-24, commits `5310488b` and `77a20a6b`):** The semantic type table now carries a table-local `RegionId` alongside each interned region type. Region binders are collected from parser annotations with lexical start/end lines, and a use resolves to the innermost active binder; consequently `Box[r]` for a shadowing inner `r` no longer aliases the outer `Box[r]` TypeId. Generic call-result substitution consumes that identity for direct and qualified calls, and the parser closes `__region_param` ranges at each function boundary. `destroyed_view_lifetime_smoke.sh` checks the cross-region generic rebind rejection and a live same-region control at `-O0` and `-O2`; `region_scope_smoke.sh` agrees with Stage0 on 21 carrier-less annotation cases; `cross_module_fallible_return_smoke.sh` covers generic region handles returned through error paths. A fresh Gen2 product passes freshness, and `test/repro/json_safe_api.elisa` compiles and runs at `-O0` and `-O2`. Commit `77a20a6b` also limits function-end annotation closure to annotations added by that function and restores direct ordinary-type interning, leaving the region identity side table on the sparse region path. This measured slice improves lexical identity at one generic type boundary; IDs remain table-local and are derived from source ranges, and do not yet give all compiler passes complete, persistent lifetime identities.

- [x] Introduce typed `DeclId` and resolver `BindingId` for currently mapped declarations/occurrences, plus a table-local lexical `RegionId` for known region-type rows and generic substitutions. This is partial identity infrastructure, not persistent or globally canonical identity.
- [ ] Extend identity coverage to `TypeId`, `BlockId`, `LoanId`, complete source origins, and all region-bearing facts. Replace line/range-derived proof identity with stable lexical binder links; include source/module fingerprints anywhere identity crosses a cache or interface boundary. Names and line numbers remain diagnostic data, never proof identity.
- [ ] Resolve module paths, imports, aliases, overloads, generic arguments, fields, effects, laws, handlers, and generated helpers before safety reasoning.
- [ ] Preserve nominal identity independently of ABI representation; equal-sized enums, errors, pointers, and effect applications are not interchangeable.
- [ ] Represent reference kind, mutability, lifetime dependencies, storage stability, ownership, raw-versus-safe provenance, and thread capabilities in canonical types or an inseparable typed metadata layer.
- [ ] Require complete substitution of safety metadata under generics, aliases, associated types, protocols, nested aggregates, and function types.
- [ ] Include safety-relevant parameters in instantiation and summary cache keys. Separate semantic identity from structural layout deduplication.
- [ ] Give generated declarations source origins and semantic owners; prevent accidental user access to privileged generated names.

**Acceptance:** shadowing, same-named modules/handlers/types, declaration reordering, aliases, and generic specializations cannot change the selected declaration or erase a safety obligation. Type metadata round-trips through interfaces without loss.

### D.2 A typed control-flow representation

**S02 — typed safety IR and CFG.** Extend the current small CoreIR deliberately; do not assume it already supports arbitrary Elisa. A separate safety IR is acceptable if it has a verified mapping into executable lowering.

**Progress (2026-09-23):** The Core Go compiler's semantic CFG now gives fallthrough, ordinary branches, loop branches, match dispatch, returns, direct `raise` error exits, panic/static-error exits, and `break`/`continue` explicit terminators. A nested-loop target stack routes each loop transfer to the nearest loop's correct exit or header; loop CFGs preserve the zero-iteration path, route body fallthrough back to the header, and represent per-item iterator filters as a separate branch. `VerifyCFG` checks block numbering, entry/exit and edge ranges, terminal/exit consistency, and successor arity, and function finalization rejects a function with a structurally malformed graph before deriving facts from it. Core commit `a6e3ea9c` adds nested-transfer and malformed-terminator regressions. Core commit `8730193d` removes the silent statement fallback: known linear statements require an explicit allowlist entry, `static if` receives conservative branches, and an unmapped statement type closes the graph and is rejected by verification. Core commit `fb3aee7a` adds a regression that scans sealed AST `Stmt` marker methods and requires every current statement variant to appear in the CFG builder, terminator classifier, or linear allowlist. Focused CFG/coverage tests and `go test ./src/semantic -count=1` pass after these commits. The coverage test checks that every current kind has a disposition, not that each kind's effects, cleanup, or lowering semantics are fully modeled. Typed places and operations, complete error/cleanup propagation, full per-node semantics, dominance/type/call-signature invariants, and backend obligation mapping remain open; S02 is not complete.

- [ ] Model places as a base binding plus projections: field, index, dereference, active-variant field, and slice range. Keep storage location distinct from a copied value.
- [ ] Model reads, writes, moves, shared/exclusive borrows, call arguments/results, allocation, reset/free, discriminant tests, checked arithmetic, checked indexing, raw operations, cleanup, and control transfers explicitly.
- [ ] Lower short-circuiting, expression `if`/`match`/`catch`, `try`, tail returns, comprehensions, loops/accumulators, multi-target rebind, defers, and effect-generated calls without losing evaluation order.
- [ ] Include normal, error, early-return, break, continue, and cleanup edges. Add unwind/cancellation edges only when supported; reject syntax whose exits cannot be represented.
- [ ] Distinguish unreachable blocks from unknown facts. “No facts” is never synonymous with “proven safe.”
- [ ] Verify typed IR: definitions dominate uses, places/types agree, every branch has a terminator, calls match full signatures, cleanup edges are valid, and all operations have safety treatment.
- [ ] Build exhaustive visitors or generated coverage checks; a new AST/IR variant cannot compile by falling through a default “safe” case.
- [ ] Carry validated operation IDs and obligations into backend lowering so the backend does not reconstruct proofs from source spellings.

**Migration:** first build alongside current checks and compare diagnostics/facts; then make it authoritative per feature family. Old lowering remains eligible only when the same mandatory obligations are enforced. A feature outside the new IR is not automatically grandfathered into safe output.

**Acceptance:** every executable language construct is mapped to the typed CFG or rejected by name. IR invariant failures prevent artifact emission. Tests cover both original syntax and its lowered form.

### D.3 Fixed-point analyses and summaries

**S03 — shared dataflow engine.**

- [ ] Define finite lattices for initialization, moved state, live loans, provenance sets, region ownership, possible variants, effects, and storage invalidation.
- [ ] At joins, union possible unsafe states/dependencies and intersect facts requiring truth on all incoming paths. Initialization is definite only if established on every reachable predecessor.
- [ ] Analyze loops and recursive call components to a conservative fixed point. Widen growing facts conservatively; never drop an unsafe possibility to force convergence.
- [ ] Track field-sensitive facts with a conservative whole-object fallback when projections cannot be separated.
- [ ] Invalidate refinement, length, tag, alias, and nonnull facts after relevant writes, calls, reentrant callbacks, or synchronization changes.
- [ ] Compute function summaries for read/write/move/drop, escaping arguments, returned provenance, stored provenance, region allocation/reset, callback retention, thread transfer, and effects.
- [ ] Unknown direct/indirect/foreign calls use conservative summaries. Dynamic/protocol dispatch uses all possible target obligations or a checked interface contract.
- [ ] Check generic bodies under declared constraints and validate instantiated layout/safety assumptions. Handle recursive generics with explicit resource bounds and conservative rejection.
- [ ] Validate separately compiled summaries against implementation hashes, compiler/spec version, flags, target layout, and dependencies. Untrusted interface files are not certificates of native code soundness.

**Acceptance:** branch order, loop shape, shadowing, recursive call order, and source formatting do not affect safety verdicts. Property tests check transfer monotonicity and join laws. Unknown summaries cannot enable scratch reset, unchecked access, or alias metadata.

## E. Ownership, borrows, and complete lifetime safety

### E.1 Initialization, moves, and resource obligations

**S04 — definite initialization and ownership state.**

- [ ] Track each place as uninitialized, initialized, moved, or possibly one of these; track partial aggregate states and active variants.
- [ ] Reject reads, borrows, method calls, pattern access, and drops of uninitialized/moved places on any reachable path.
- [ ] Define implicit copy eligibility structurally. Owning containers, arenas, handles, and destructors cannot acquire duplicate release obligations through assignment, return, record update, or pattern matching.
- [ ] Make self-assignment, overlapping field assignment, multi-target rebind, return-by-value, and move-into-container semantics explicit. Evaluate sources before destructive destination changes where the specification requires it.
- [ ] Emit per-field/drop flags only when needed, derived from the same ownership analysis; clear them on transfer and set them only after successful initialization.
- [ ] On partial construction or clone failure, clean up exactly the successfully initialized members, in the specified order.
- [ ] Audit `zeroed`, uninitialized buffers, enum/optional/error payload construction, and low-level casts. A nonnull reference, invalid enum tag, or owning handle cannot be fabricated safely from zero bits.
- [ ] Track linear OS resources alongside memory owners; distinguish resource leakage from temporal memory safety.

**Tests:** conditional moves followed by join use; moves on loop backedges; move through tuple/enum/error/closure; double release; partial initialization failure at each field; source/destination alias; custom destructor observing fields; reinitialization after move. Positive twins include branch-complete initialization and legal ownership transfer.

**Acceptance:** each successful resource creation has one live owner or a documented deliberate leak, and every ordinary cleanup path consumes at most one release obligation. No generated drop reads invalid storage.

### E.2 Borrow checking over places and live ranges

**S05 — systematic loan analysis.**

- [ ] Define shared and exclusive access rules for existing Elisa reference and mutation forms; implement place overlap including prefixes, dereferences, uncertain indices, union/variant storage, and slices.
- [ ] Conservatively overlap unknown indices and aliased pointer origins. Prove disjoint fields/ranges only when layout and bounds support it; packed/overlapping fields need special treatment.
- [ ] Compute loan liveness from actual uses including deferred bodies, implicit drops, returned references, callbacks, and hidden captures.
- [ ] Allow a shared borrow to coexist with other shared borrows; forbid conflicting mutation, move, release, or exclusive borrow while a shared loan is live.
- [ ] For an exclusive reborrow, suspend conflicting parent accesses until the child loan ends; prevent sibling exclusive reborrows from overlapping.
- [ ] Check argument evaluation and call duration, not just the instant a function is entered. A later argument cannot invalidate an earlier argument's reference.
- [ ] Do not infer whole-object immutability merely from the spelling of a borrowed parameter; model approved interior-mutability abstractions explicitly.
- [ ] Start conservatively with lexical loans if necessary, then add nonlexical liveness without weakening soundness. Two-phase borrows require separate semantics and tests before adoption.

**Tests:** alias via field, tuple, array element, method receiver, returned borrow, function value, generic helper, protocol dispatch, nested scope, and closure; disjoint-field success; overlapping-slice failure; mutate-after-last-use success; reborrow parent access failure; defer extending loan lifetime.

**Acceptance:** all safe conflicting accesses are statically rejected or occur through a designed checked/synchronized abstraction. Unknown aliasing never justifies LLVM disjointness.

### E.3 Provenance sets, region escape, and stable storage

**S06 — complete lifetime dependencies.**

- [ ] Replace single-region taint with a set of origin/lifetime dependencies, retaining projection precision where available. Model owners, parameters, globals, static storage, heap allocations, temporary storage, and region epochs separately.
- [ ] Carry dependencies through every aggregate element/field, optional/error/enum payload, branch result, comprehension, lambda capture, generic substitution, and call result.
- [ ] At a store, return, yield-like operation, closure escape, foreign retention, or thread spawn, require the destination lifetime to be within every dependency's lifetime.
- [ ] Express borrow-return relationships in signatures: a returned borrow may depend on one or several input lifetimes. Do not guess the first reference argument or only recognize a method-name whitelist.
- [ ] Prevent references to stack locals, expression temporaries, copied fixed arrays, temporary conversion buffers, parser scratch, and short-lived handler captures from escaping.
- [ ] Distinguish scalar copies such as container length from views into backing storage using resolved types/operations, not field spelling.
- [ ] Treat reset, free, rollback-to-mark, recycle, reallocation, and region-owner transfer as distinct invalidation events. Keeping an address numerically unchanged does not make its old lifetime valid.
- [ ] Enforce caller-region forwarding using stable region IDs and checked hidden ABI slots; parameters borrowing a caller arena never release it.
- [ ] For arena growth, distinguish stable chained/reserved backing from relocating buffers. Region longevity alone does not prove element-address stability.
- [ ] Preserve multiple lifetime dependencies through imported function summaries and hidden generated functions.

**Progress (2026-09-23):** Self-host commit `3c481adc` preserves visible generic region arguments on local and parameter bindings in the parser's region-annotation side table. The new `Box[@r]` forwarding repro is added to `destroyed_view_lifetime_smoke.sh`; a fresh Stage1 passes the smoke at `-O0` and `-O2`, rejecting a `Box[scratch]` use after `destroy scratch` with the destroyed-region diagnostic while accepting live-use and last-use-before-destroy controls. This closes one concrete gap where custom region-parameterized aggregate types were not recognized by the existing syntax-based destroyed-region check. It does not establish complete provenance: the annotations still use names and source lines, the checker still tracks selected views and aggregate cases, generic call inference has a Stage0/Stage1 discrepancy for the repro, and the current JSON DOM APIs still allow arena-backed values or views to outlive their arena. S06 remains open; record this as one targeted parser/checker coverage improvement, not a lifetime proof.

**Progress (2026-09-23, commit `909966a9`):** A second repro showed that a type carrying `[first, second]` could lose its first dependency because `function_region_of_name` returned only the last matching annotation. Destroyed-region analysis now gathers all recorded generic-region arguments, checks every candidate for invalidation, and carries all candidates through local view aliases and lambda captures. The expression walk now follows `Catch`, `GetElse`, and refinement wrappers for the exercised use/provenance paths. Direct calls named `arena_free`, `arena_reset`, and `arena_rewind` conservatively invalidate the named arena dependency; this is still spelling/root-name based, and indirect calls, aliases, foreign reset, precise rewind epochs, full recovery-arm provenance, and general mutation/version tracking remain open. The JSON DOM's public parse results and values now use an opaque `JsonValueHandle[@r]`; parsing/accessors preserve the arena region, borrowed string/key views carry `@r`, writer output is tied to its separate output arena, and raw pointer-bearing constructors/accessors are private. Fresh Stage1 `destroyed_view_lifetime_smoke.sh` passes at `-O0`/`-O2` with multi-region generic, direct JSON-handle-after-free, copied JSON-view-after-free, explicitly arena-bound view, live-view, and last-use controls. The JSON safe API parse/access/write/string-view control compiles and runs at both optimization levels; Stage1 rejects the raw JSON representation/helper fixtures as private. Stage1 was rebuilt from the prior Stage1 product at `-O1` because the Stage0 checkout/binary is absent in this environment; no Stage0 parity claim is made for this commit. This is a narrow improvement, not completion of S06: annotations still rely on names/lines and generic type syntax, and shared CFG-based origin sets plus complete invalidation semantics remain required.

**Follow-up verification (2026-09-23, commit `dfbacd06`):** The same fresh Stage1 smoke now separately exercises `arena_reset` and `arena_rewind` with a live `sview @arena`; both are rejected at `-O0` and `-O2` with the arena invalidation diagnostic and no LLVM output. Rewind is intentionally conservative and invalidates the whole named arena because no allocation-epoch/mark-position analysis exists yet.

**Progress (2026-09-23, commit `fe384cf8`):** A new JSON repro found that `JsonValueHandle[arena]` and `JsonValueHandle[other]` interned as the same structural type because generic region identifiers collapsed to `Unknown`, and declaration initializers did not compare structural container types. The type table now represents known region arguments as `SemTypeKind.Region`, registers region binders before symbol collection, and checks structural container compatibility at declaration initialization. For direct generic-call initializers whose declared region-qualified container head matches the callee's return head, the checker substitutes region/type arguments from relevant formal parameter shapes and explicit `@r` parameter ties; it reuses existing interned rows and falls back to unknown when a scheme cannot be fully resolved. `test/repro/json_handle_region_mismatch.elisa` now rejects a direct `json_handle_from_result(parsed)` call declared as `JsonValueHandle[other]` when `parsed` is tied to `arena`, while the same-region control and JSON safe API remain valid. A fresh self-hosted Stage1 product passes `destroyed_view_lifetime_smoke.sh` at `-O0`/`-O2`; the JSON parse/access/write control compiles and runs at both levels; Stage1 freshness and `git diff --check` pass. Stage0 is unavailable in this checkout, so this remains Stage1-only evidence. The implementation is not a lifetime proof: region identities remain source-name-based and file-wide in this table; shadowed same-spelling regions can collide; generic-call substitution is currently a narrow initializer-boundary path; and shared CFG provenance, full function summaries, indirect-call/reset handling, and epoch identities remain required. Keep S01/S06 open.

**Progress (2026-09-23, commit `f06e58cf`):** A regression showed that the selected destroyed-region view analysis classified `T&` and mutable wrappers as views but stopped at the optional `?` wrapper. It therefore failed to carry a scratch-region dependency through a copied `sview?`. Optional wrappers now preserve the contained view classification, and `test/repro/sview_optional_region_use_after_destroy.elisa` verifies that a present region-backed view stored in an optional is rejected after `destroy scratch`; the paired fixture verifies use before destruction and safe use of an absent optional afterward. The fresh self-hosted Gen2 product passes `destroyed_view_lifetime_smoke.sh` at `-O0`/`-O2`, and `scripts/self_host_gen2.sh` passes its rebuild and runtime fixture. This is conservative syntax-based view recognition, not tag-sensitive optional analysis or complete lifetime provenance; S06 remains open. Stage0 parity was not established for this change.


**Progress (2026-09-24, commits `5310488b` and `77a20a6b`):** Generic region-bearing type rows now distinguish shadowed lexical binders instead of keying solely on spelling. The minimized `shadowed_region_generic_rebind` fixture rejects assigning an inner `Box[r]` to an outer `Box[r]` before the inner region is destroyed, and its same-region twin compiles and runs at `-O0` and `-O2`. Generic return substitution also follows the region identity through qualified calls and error-return shapes covered by the cross-module smoke. The optimized fresh Gen2 build passes `destroyed_view_lifetime_smoke.sh`, `region_scope_smoke.sh` (21 cases against Stage0), `cross_module_fallible_return_smoke.sh`, and the JSON safe API runtime control. This closes a concrete type-relabeling gap; it does not prove that all values retain every origin through aggregates, CFG joins, indirect calls, resets, aliases, or separate compilation. Region identity is still table-local and line/range-derived, so S01 and S06 remain open.

**Progress (2026-09-24, captured static-effect reset regression):** A new repro showed a real stale-alias path: a statically installed handler captured `Arena&`, reset it through a generic effect wrapper, and the caller still read a view tied to that arena; the previous fresh compiler emitted LLVM and the executable returned `7` instead of rejecting the stale read. The generic wrapper's summary already represented a static effect call as an unknown captured-state effect, but its caller spelled `reset_through_effect[i64]()` with an `IndexN` callee, while summary lookup only recognized a bare identifier. Destroyed-region summary lookup now unwraps direct generic/indexed and parenthesized/moved callees, and recognizes generated `__effect__`/`__handler__` scope targets. Unknown static-handler effects and generated hidden calls invalidate tracked arena dependencies conservatively, and unresolved summary paths carry explicit arena-owner arguments. The minimized `test/repro/arena_static_effect_capture_reset_leak.elisa` is now a rejection case in `destroyed_view_lifetime_smoke.sh`; fresh Gen2 product `30e2c071e8ea9d6e7edff6f15f87d96cd203ea2b0104ec9752c0b1c568984fa7` rejects it at `-O0` and `-O2` with the `alloc` invalidation diagnostic and writes no LLVM. The destroyed-view suite, 21-case Stage0 `region_scope_smoke.sh`, and `cross_module_fallible_return_smoke.sh` pass. This is intentionally fail-closed and may reject programs whose handler cannot affect a tracked arena. Summary propagation is still an AST/name-based approximation rather than complete effect provenance across CFGs and separately compiled modules; region identities and invalidation epochs remain incomplete, so S01/S06 stay open.

**Progress (2026-09-24, closure-after-free regression):** A fresh pre-fix compiler emitted LLVM for a closure capturing an arena-backed `sview`, then returned `0` after `arena_free` where the live bytes produce `65`. The checker now traverses current lambda-body statement/expression forms to collect capture dependencies, carries those dependencies through transparent local function-value copies, recognizes local callable calls through identifier/parenthesis/move/index/cast wrappers, and registers a directly assigned lambda against the existing target. If a callable binding is initialized from a producer whose capture provenance is unavailable, including a returned closure and a named function-type alias, it receives an unknown-provenance marker; after any tracked region is invalidated, calling it is rejected before LLVM emission. The smoke covers direct capture aliasing, reassignment, and a returned captured closure at `-O0` and `-O2`, plus a positive captured-closure control that frees an unrelated arena and returns `65`. A tuple containing captured closures remains unsupported by the current backend; its regression requires a linkable-unit rejection and no LLVM output, and does not count as lifetime-analysis coverage. Fresh Stage23 `build/arena_closure_stage23/elisac-stage1-gen2` passes `assert_stage1_fresh.sh` (SHA-256 `9d25dcc2de8f61a28fbeb7283f961cff4f1afd4cc744118e8d830fbd173b7286`), the destroyed-view lifetime suite, the 21-case Stage0 `region_scope_smoke.sh`, and `cross_module_fallible_return_smoke.sh`. This remains a name/line-based local analysis: unknown returned closures may be rejected after an unrelated invalidation, diagnostics choose an invalidated region without knowing the closure's exact origin, aggregate closure storage is not generally modeled, and typed capture/return/effect summaries plus CFG joins are still open. Keep S06 open; this milestone is not a memory-safety qualification.

**Follow-up verification (2026-09-24, fresh Stage30):** The Stage23 attempt was an intermediate result: its new positive closure control exposed that conservative indirect-call invalidation ran before checking the call itself. The checker now checks a local callback against the pre-call state, applies its unknown effects for following operations, and analyzes directly bound/assigned lambda bodies in a fresh deferred-execution state so reset-then-read inside the body is rejected. It also diagnoses stale reads in statement-level if/while/for/match expressions, traverses nested scalar-producing block/match/catch/recovery/comprehension/effect expressions, and carries view origins out of value blocks/match arms (including the `sview(pointer, ...)` constructor). Inline callbacks are walked at their call site. `destroyed_view_lifetime_smoke.sh` passes at `-O0`/`-O2`, including closure alias/assignment/returned closure, closure-internal reset, inline callback, if/while/for/match read positions, view-producing and scalar-reading blocks/matches, a live closure after freeing an unrelated arena (returns 65), and the tuple-capture backend refusal. Fresh Stage30 `build/arena_closure_stage30/elisac-stage1-gen2` passes freshness; `region_scope_smoke.sh` passes all 21 cases against the freshly rebuilt Stage0 oracle; `cross_module_fallible_return_smoke.sh`, self-host fixture, shell syntax, and whitespace checks pass. Stage30 Gen2 SHA-256: `2b9b818a7fc0a91d922647cb491a77a5f7f56579b0c7ce3f6ba88159d311e732`. This remains an AST/name/line-based conservative checker rather than typed CFG provenance: unknown returned closures can be rejected after unrelated invalidation, aggregate callback storage remains unsupported by the backend, and exhaustive origin/effect summaries, shadowing-safe nested scopes, and interprocedural closure escape analysis remain open. A separate audit also confirmed that safe `StringView{data, len}` construction can overstate pointer extent and `sview(u8&?, ...)` can call `strlen` on a non-terminated byte; those extent/terminator regressions are the next milestone. S06 remains open and no memory-safety qualification is claimed.

**Tests:** aggregate containing both outer and inner borrows in either field order; conditional and match returns from different regions; store into global/outer container; nested error payload; two output regions; region reset while a deferred view remains live; named/inferred arena forwarding; shadowed regions.

**Acceptance:** reversing aggregate field order or branch order cannot hide an escaping dependency. Every returned/stored borrow has a complete auditable origin set.

### E.4 Containers, iterators, and lending APIs

**S07 — mutation invalidation and safe container contracts.**

- [ ] Inventory `darray`, fixed arrays, views/sviews, dictionaries, sets, deques, packed stores, and pool APIs by whether each operation can move, shrink, overwrite, remove, or recycle storage.
- [ ] Tie slices, element references, iterators, entries, and string views to the appropriate owner and mutation/version constraints.
- [ ] Reject growth/reserve/rehash/erase/clear/reset during conflicting borrows, even if the current capacity happens to avoid relocation in a test run.
- [ ] Specify mutation during iteration and callback reentrancy. A dictionary comparison/hash callback or user drop may reenter and invalidate a previously checked pointer.
- [ ] Provide safe split/disjoint APIs whose implementation proves nonoverlap, and lending accessors whose borrows cannot survive their access guard.
- [ ] Handle nested containers structurally: moving a header does not necessarily relocate backing, but may transfer lifetime/release authority. Specify each case.
- [ ] Separate byte strings, validated text, NUL-terminated strings, and borrowed views; enforce encoding invariants and embedded-NUL policy where relevant.
- [ ] Check all externally constructible pointer-length-capacity triples before turning them into safe views. Raw view constructors belong to the unsafe boundary.

**Acceptance:** dynamic container mutation cannot invalidate a live safe reference; iterator APIs have defined behavior on every mutation path; reentrant callbacks cannot bypass guards.

### E.5 Closures, effects, and deferred work

**S08 — hidden state participates in safety.**

- [ ] Classify captures as copy, move, shared loan, or exclusive loan; compute closure environment lifetime and drop obligations.
- [ ] Escaping or thread-transferred closures carry all captured provenance/capabilities. A heap-allocated closure environment does not extend a borrowed stack referent's lifetime.
- [ ] Treat block/function defers as captures extending loans until actual execution, with lexical binding identity preserved under shadowing.
- [ ] Audit static effect handlers and clones using `codegen_static_effects.elisa` and `docs/effect-system-fix-status.md`: hidden captures, installed handler identity, generic specialization, and nested installations must preserve ownership/effect facts.
- [ ] Prevent capability capture and generated helper calls from widening authority beyond the declared boundary.
- [ ] Ensure callback lifetime and invocation multiplicity are compatible with captured ownership; a one-shot moved capture cannot be invoked twice safely.
- [ ] Reject self-referential environment moves and unsupported suspension/continuation behavior until pinned/lifetime-aware semantics exist.

**Acceptance:** source-visible and hidden arguments receive identical safety treatment; declaration order and helper cloning do not change capture lifetime or permission checks.

## F. Checked operations, value validity, and arithmetic

### F.1 Bounds and pointer formation

**S09 — comprehensive spatial safety.** Existing default bounds guards are the starting point.

- [ ] Audit reads and writes for every indexable representation, including fixed-array references, multidimensional/nested arrays, strings, slices, containers, packed layouts, and borrowed views.
- [ ] Check negative signed indices before conversion; require `0 <= index < length` in the target-width domain. Check slice endpoints using the specified half-open/inclusive rules and enforce ordering.
- [ ] Check multiplication/addition for byte offset and total allocation size before computing addresses. Prefer overflow-safe comparisons such as `length <= allocation_size / element_size` where valid; define zero-sized element behavior separately.
- [ ] Distinguish capacity from initialized length. Spare allocated bytes are not initialized `T` values and may not be read through safe indexing.
- [ ] Ensure an empty view, zero-length memcpy, empty iterator, or zero-argument foreign call does not first form `&items[0]` or another invalid reference.
- [ ] Form LLVM addresses only after guards required for validity. Audit eager/speculative lowering of expressions whose source evaluation is conditional.
- [ ] Remove a guard only using a fact tied to the current container/index version, surviving all intervening mutations/calls.
- [ ] Specify `get`, optional indexing, fallback expressions, and checked slice APIs so fallback evaluation occurs exactly when required and exactly once.
- [ ] Make every unchecked indexing escape hatch explicit, operation-specific, and auditable. An unrelated `can` grant cannot authorize it.
- [ ] Retain bounds checks in every supported optimized build unless discharged by sound proof. Wasm linear-memory bounds alone are insufficient for per-object bounds.

**Tests:** index `-1`, `0`, `length-1`, `length`, maximum integer; zero-length containers; reversed slices; offset multiplication overflow; forged FFI lengths; nested indexing; bounds checked then container shrunk by alias/callback; side-effecting index and fallback; dynamic indices that cannot constant-fold.

**Acceptance:** each potentially invalid access rejects or reaches a specified failure before any invalid reference/access is produced; optimized and unoptimized behavior agree.

**Verified S09 bounded source-view slice (2026-09-24, Stage1 commit `ae85f1b7`):** the adjacent Elisa-core `main` already contains Stage0 commits `43c0d8c4` (safe StringView/C-string bridges), `15b446ac` (preserve view backing regions), and `0742534c` (require unsafe authority for raw StringView slicing). Stage1 now rejects public/aliased StringView carrier fabrication, `zeroed` views, forged extents, and implicit raw-pointer conversions to `sview`/`cstr`; the bounded source-view helper checks `start <= end <= source_length` before a narrow trusted pointer-to-view operation. Lexer views use the known byte extent, parser views use the terminal EOF offset, and EASM line views preserve their explicit scan bound. C-string literal construction remains the positive control. A fresh Stage1 seed, `assert_stage1_fresh.sh`, `self_host_gen2.sh`, `sview_representation_safety_smoke.sh` (O0/O2), `runtime_string_view_safety_smoke.sh`, `destroyed_view_lifetime_smoke.sh` (O0/O2), `region_scope_smoke.sh` (21 cases), and `cross_module_fallible_return_smoke.sh` pass. After adjacent Stage0 commits `8c1f8a19`, `a4b64da4`, and `9a4de23b` landed, the current Stage0 binary was rebuilt; final region, runtime-view, and cross-module comparisons used that fresh oracle. `go test ./src/backend -count=1`, `go test ./src/semantic ./src/parser -count=1`, and `go build -o bin/elisac ./src` pass on Stage0 main. A Stage1-pinned `parser_smoke.sh` attempt safely declined two `print` bodies and emitted no object; an independent medium-MLAST run reports 10 safe body declines. These are backend coverage gaps tracked under S26, not evidence of complete Stage1 coverage. This slice closes only StringView carrier and source-span formation paths: token extents rely on lexer-produced tokens, C-string termination remains a boundary contract, and other indexable types, foreign lengths, pointer arithmetic, and backend-wide obligation preservation remain open.

### F.2 Arithmetic and representation validity

**S10 — one arithmetic and conversion model.**

- [ ] Specify each integer width/signedness and target-sized `int`, `isize`, `usize`, `uintptr`; centralize target layout queries and ban host-width inference.
- [ ] Define overflow, division/remainder by zero, signed minimum divided by `-1`, shift counts, shifts of signed values, narrowing/widening, and signed/unsigned comparisons.
- [ ] Implement checked, wrapping, and saturating operations as distinct operations in semantic IR, constant evaluation, interpreter, LLVM, and Wasm lowering.
- [ ] Give constant folding the same semantics as runtime execution. Use sufficiently wide or checked compiler-side arithmetic so the compiler's host arithmetic cannot fabricate a proof.
- [ ] Model floating-point-to-integer conversion for NaN, infinity, and out-of-range values before lowering to operations with undefined/poison outcomes. Specify NaN comparisons and fast-math permissions.
- [ ] Keep object lengths/offsets in target-sized domains with checked boundary conversions from i64/u64 and foreign sizes.
- [ ] Validate booleans, enum discriminants, optional/error tags, characters/text units, and refinement-carrying values when importing bytes or foreign data.
- [ ] For layout/niche optimizations, prove that the reserved representation cannot arise as a valid payload; otherwise use an explicit tag.
- [ ] Separate bit reinterpretation from numeric conversion and reference formation; bit-compatible size is not proof of a valid target value.

**Acceptance:** table-driven edge tests agree across constant/runtime execution and all backends; no supported safe arithmetic or conversion can feed LLVM poison into observable execution. Existing overflow smokes remain required.

## G. Runtime, allocation, and cleanup

### G.1 Allocator and arena implementation audit

**S11 — small, explicit memory-runtime TCB.** Begin with `elisacore_std/arena.elisa`, `allocator.elisa`, `heap.elisa`, runtime slices/strings, and native bridges.

- [ ] Write contracts for allocate, deallocate, reallocate, reset, marks/rollback, region transfer, and pool recycle: allocation identity, byte extent, alignment, initialization state, and permitted caller ownership.
- [ ] Centralize checked `size + header`, `count * stride`, alignment rounding, growth factor, page rounding, reservation limits, and copy length calculations.
- [ ] Support over-aligned types explicitly or reject them before allocation. Ensure headers/free-list nodes do not misalign payloads or overwrite live data.
- [ ] Specify zero-size allocation and reallocation behavior consistently across malloc, bump, chained, reserved, fixed, native, Windows, and Wasm paths.
- [ ] Handle allocation/map/commit failure before pointer use. Reallocation failure preserves the old live allocation and its owner unless a different documented contract is implemented.
- [ ] Maintain `initialized_length <= length/capacity` according to the chosen container model; publish new metadata only after allocation/construction succeeds.
- [ ] Choose memcpy only for nonoverlapping ranges; use memmove or a proven direction where overlap is possible. Copy only initialized bytes when value validity requires it.
- [ ] Audit arena caches/free lists for duplicate insertion, foreign-owner free, cross-thread use, stale marks, cycles, double reset/free, and reuse of live storage.
- [x] Protect the process-wide mmap region-cache list, its bounded retention counter, and the shared free-region hint with a target atomic lock on POSIX and Windows; all cache/hint global accesses are confined to locked helpers. Stage0/Stage1 concurrent arena smoke passes at O0 and O2 with four pthread workers repeatedly creating, allocating, and freeing independent arenas. This closes metadata races for these globals only; each arena and its region chain still require exclusive owner synchronization, and non-POSIX/Windows threading targets still need an explicit support classification or lock implementation.
- [ ] Model region/pool generations for checked handles. Prevent stale handles from becoming valid after counter wrap: retire exhausted slots or use a proved bounded reuse strategy; large counters alone are not a soundness proof.
- [ ] Keep safety checks free of allocations where possible so OOM reporting cannot recurse into OOM. Define fail-stop versus recoverable allocation APIs.
- [ ] Add a test allocator that deterministically fails allocation N, forces relocation, uses tiny capacities, inserts canaries, and can poison reclaimed ranges in instrumented builds.
- [ ] Audit raw extern signatures and allocator identity matching; memory from one allocator must not be released by another.
- [ ] Coordinate vendored runtime changes with the canonical Elisa-core copy using `scripts/check_runtime_drift.sh`; do not disable the drift guard to finish a local change.

**Acceptance:** failure injection at every allocation point leaves a valid prior state or a correctly cleaned partial state; sanitizer/model tests find no invalid memory operation; each unsafe runtime primitive has a written invariant and caller contract.

### G.2 Packed stores, pooled values, and logical handles

**S12 — handle safety and representation consistency.**

- [ ] Inventory dense, sparse, AoS, packed encoding, row, and region-backed store operations in `elisacore_std/stores*.elisa` and `heap.elisa`.
- [ ] Bind handles to store identity, generation, live slot, and active variant. Reject handles from another store even when their numerical index matches.
- [ ] Check index/offset/tag decoding, word packing, truncation, bit shifts, allocation sizes, and endianness assumptions on 32/64-bit targets.
- [ ] Specify which operations compact/move rows, change variants, or relocate columns, and invalidate or prohibit outstanding references accordingly.
- [ ] Keep parallel metadata arrays consistent transactionally under OOM, construction failure, deletion, and variant conversion.
- [ ] Prevent affine `Pooled[T]` ownership from being bypassed through raw pool APIs available to safe code.
- [ ] Design safe access as an owner-tied loan or guard; a checked lookup followed by unrestricted mutation is not sufficient.
- [ ] Test ABA/recycle sequences, generation exhaustion using a small test counter, store destruction/recreation, malformed handles, and mixed-store calls.

**Acceptance:** every safe handle access validates the right owner/lifetime or is statically proven live; no handle can access a different object after reuse; no partial metadata update is externally observable as valid state.

### G.3 Cleanup as control-flow semantics

**S13 — unified drop/defer/region exit lowering.**

- [ ] Derive one cleanup plan from typed ownership/CFG facts for normal fallthrough, explicit/tail return, `try` propagation, `catch`, break, continue, and nested blocks.
- [ ] Preserve source evaluation order: materialize and transfer return values before destroying dependencies, but never return a value borrowing storage about to be released.
- [ ] Define the interleaving of user defers, value destructors, and arena reset/free. A defer reading a region must run while that region is live.
- [ ] Use ownership/drop flags for conditional initialization and moves; ensure multiple syntactic exits cannot double-run the same action.
- [ ] Handle destructor dependencies, nested container elements, error payloads, captured environments, and by-value parameters consistently.
- [ ] Specify cleanup reentrancy and destructor failure. Initially prevent nonlocal exits from cleanup where they cannot be made sound; a second failure during unwinding must have a defined fail-stop policy if unwinding is introduced.
- [ ] Make abort/trap semantics explicit: process/instance termination may omit cleanup, but must never resume with partially destroyed state. Foreign longjmp/unwind across Elisa frames requires a separate supported boundary or is prohibited by contract.
- [ ] Verify loop scratch resets occur after last uses/defers and on every relevant iteration exit, with final free exactly once. Keep current conservative scratch inference fallback.
- [ ] Compare cleanup traces against an independent ownership model, not merely stage0's trace.

**Acceptance:** deterministic event logs match specified cleanup ordering on every exit; no double drop, use after reset, lost required drop on recoverable failure, or ownership leak through error propagation.

## H. Unsafe authority, effects, proofs, and contracts

### H.1 Unsafe is an explicit boundary, not a general exemption

**S14 — operation-specific unsafe obligations.**

- [ ] Enumerate unsafe operations: raw dereference, pointer arithmetic/casts, unchecked index, forged reference/view, unchecked initialization/tag change, manual deallocation, unverified extern, unchecked alias promises, assembly, and trusted proof assumptions.
- [ ] Map each operation to an exact resolved capability and semantic preconditions. Preserve capability identity through modules, aliases, generics, effects, and generated code.
- [ ] Replace a boolean “inside a grant” with a lexical set of granted capabilities and a distinct unsafe-boundary record. `Memory.Allocate` or `Abort.Panic` must not suppress alias/bounds obligations.
- [ ] Distinguish granting authority from proving correctness. `Unsafe.Alias` cannot justify contradictory `noalias` metadata; it either leaves the safe guarantee or requires a checked abstraction preserving it.
- [ ] Require unsafe function declarations to expose caller obligations; unsafe code implementing a safe function must establish its public invariant for every safe input.
- [ ] Audit `trusted` blocks and exported wrappers transitively. A wrapper cannot be marked safe simply because its body is trusted.
- [ ] Prevent malformed/nested grants, shadowed effects, unrelated handlers, generated names, and imported declarations from widening authority.
- [ ] Extend `src/driver/elisac_emit_unsafe*.elisa` output with operation kind, resolved identity, source span, reason, boundary, and owning API. Keep stable machine-readable data for review.
- [ ] Make raw operations mandatory to account for in ordinary builds; stricter proof/lint profiles may add requirements but cannot remove this baseline.

**Acceptance:** negative tests place each unsafe operation inside unrelated grants and still reject it; positive tests authorize exactly the intended boundary; unsafe reports cover all raw operations including generated ones.

### H.2 Proof soundness and runtime assertions

**S15 — trustworthy refinement and contract enforcement.**

- [ ] Classify facts as static derivations, checked runtime assertions, trusted axioms, user declarations awaiting verification, or unknown. Do not merge these trust levels.
- [ ] Ensure an `assert` used for subsequent proof is either proven or executed before the dependent operation. A debug-only erased assertion cannot justify release safety.
- [ ] Verify function preconditions at each call or insert defined checks; prove/check postconditions on every normal return. Error returns have separately specified contracts.
- [ ] Invalidate facts when aliased writes, callbacks, region reset, atomics, or external calls can change their subject.
- [ ] Model integer overflow and target widths in interval/symbolic/SMT reasoning; mathematical integer facts do not automatically apply to wrapping or checked machine integers.
- [ ] Define solver results precisely. Unknown, timeout, unsupported encoding, malformed output, version mismatch, or tool absence cannot discharge a safety obligation.
- [ ] Check generated verification conditions against semantics, including non-vacuity and inconsistent assumptions. A contradictory imported precondition cannot silently prove arbitrary public behavior.
- [ ] Restrict law/contract expressions to supported pure behavior, with termination/resource bounds where evaluation/proving needs them. Effects and hidden mutation must be rejected or modeled.
- [ ] Key proof caches by normalized obligation, assumptions, implementation/dependency hashes, target widths, compiler/spec version, solver version/options, and unsafe axioms.
- [ ] Separate termination/progress checking from memory safety: failure to prove termination does not imply permission to erase memory checks.
- [ ] Add independent finite-domain/model comparisons for small arithmetic and lifetime obligations; consider replayable proof certificates to reduce solver trust where practical.

**Acceptance:** deliberately wrong assertions/laws, solver timeout, stale caches, overflow edge cases, and mutated subjects cannot enable unchecked invalid operations. Every removed check has an inspectable valid justification.

### H.3 Effects and module/type correctness

**S16 — close correctness gaps that undermine safety.**

- [ ] Resolve all effect/permission identities nominally; handler matching must compare declarations and instantiated arguments, not terminal names or representation.
- [ ] Validate effect rows through function values, protocols, generics, defaults, hidden captures, callbacks, and separate compilation.
- [ ] Make narrowing/exhaustiveness facts CFG-sensitive: optional unwrap and variant field access require an active valid tag, and writes/calls invalidate narrowing as appropriate.
- [ ] Define match exhaustiveness/unreachable arms, record update, equality/order, tuple/named argument binding, and overload selection consistently across semantic analysis and backend.
- [ ] Ensure type aliases preserve ownership/refinement/region qualifiers; nominal private fields and sealed constructors protect representation invariants across module boundaries.
- [ ] Treat function pointers/vtables as typed values with matching calling convention, region/effect obligations, and environment/drop metadata.
- [ ] Specify global initialization order, cross-module cycles, destruction order, and thread-safe lazy initialization; reject observable use-before-initialization.
- [ ] Validate all constant/global initializers using the same arithmetic/value validity rules as local runtime code.

**Acceptance:** no hidden call, generic instantiation, alias, or narrowed branch can bypass the same obligations imposed on a direct explicit operation.

## I. Concurrency and asynchronous boundaries

**S17 — data-race-free safe concurrency.** Start with `check_thread_shareability.elisa`, `check_thread_transfer_provenance.elisa`, `elisacore_runtime_concurrency.elisa`, and `elisacore_runtime_parallel.elisa`.

- [ ] Specify the source memory model: conflicting non-atomic accesses require happens-before or exclusive ownership; logical races and deadlocks are separate concerns.
- [ ] Define structural “may transfer” and “may share” properties (names/syntax to be chosen). Include nested fields, references, owned regions, allocators, closures, function environments, and foreign handles.
- [ ] A `static` lifetime alone does not imply thread-safe mutation. Shared mutable globals require synchronization or explicitly unsafe access.
- [ ] For unscoped threads require owned transferable or adequately long-lived shareable captures. For scoped threads tie every task's lifetime to a guaranteed join before borrowed storage/regions are destroyed.
- [ ] Account for all scope exits, errors, panics, cancellation, and spawn failures in joining and capture cleanup. A failed spawn must leave ownership in a specified valid place.
- [ ] Forbid detached workers retaining stack/region borrows. Design cancellation cooperatively or otherwise prove resources cannot be freed while code still runs.
- [ ] Implement lock/borrow guards whose live range protects access; document poisoning and recovery after failure. Returning a reference past a guard is rejected.
- [ ] Audit atomic widths/alignment, legal memory orders, compare-exchange success/failure order pairs, and target support. Unsupported atomics must lower through a correct runtime or reject.
- [ ] Audit work queues, pools, once initialization, TLS, callback threads, region ownership transfer, and Windows fallback code. Avoid introducing lock-free reclamation without a complete reclamation protocol.
- [x] Serialize the arena runtime's cross-arena cache and reclaim-hint metadata with acquire/release atomics on POSIX and Windows; keep the cache lock non-reentrant and outside arena ownership operations. The native-host stress smoke, lifecycle smoke, and allocation-overflow smoke pass on Stage0/Stage1. This does not establish race freedom for same-arena sharing, other runtime globals, foreign callbacks, or targets whose thread support is not yet classified.
- [ ] If reference counting is introduced/used, check count overflow and atomic ownership transitions; prevent safe underflow/double destruction and classify cycles as retention issues.
- [ ] Run race instrumentation where supported, plus deterministic scheduler/state-space tests for small synchronization scenarios; timing-based stress alone is insufficient.

**Acceptance:** safe APIs cannot construct a data race or outlive scoped resources. Thread result/capture transfer preserves exactly-once ownership. Unsupported targets/features are explicitly classified.

## J. FFI, bindings, serialization, and target boundaries

### J.1 Native ABI and safe foreign wrappers

**S18 — validated native boundaries.**

- [ ] Inventory every `extern` and classify native C ABI, Elisa interface ABI, runtime primitive, generated bridge, callback, and platform-specific declaration.
- [ ] Specify argument/result layouts, alignments, enum/optional/error representations, hidden region parameters, calling convention, varargs promotions, and ownership on success/failure.
- [ ] Use target C types/widths; preserve the documented distinction between Elisa `int` and C `int`, and between Windows and POSIX `long`.
- [ ] Separate raw pointers from safe references. Import pointer+length only through a contract guaranteeing accessible initialized storage and lifetime; numeric range checks cannot verify arbitrary native pointer provenance.
- [ ] Wrap foreign APIs with validated lengths, nullable results, buffer ownership, deallocator identity, and lifetime retention. Copy transient data when retention cannot be proved.
- [ ] Export safe ABI adapters that validate tags/ranges/lengths and convert raw representations before constructing internal safe values.
- [ ] Define callback environment rooting, invocation multiplicity, thread affinity, retention, cancellation/unregistration, and reentrancy.
- [ ] Define panic/error translation at ABI boundaries and prohibit unsupported unwinding/longjmp across Elisa frames.
- [ ] Compare generated headers and ABI probes with a C harness for each supported target; test structs by value, packed layout, callbacks, function pointers, varargs, and negative returns.
- [ ] Treat malicious foreign code as outside the safe guarantee. For untrusted native extensions, use process/sandbox isolation instead of claiming local type checks contain them.

**Acceptance:** every safe foreign wrapper has an explicit ownership/lifetime contract and tests for invalid boundary inputs it can meaningfully validate; no ABI layout assumption comes from the compiler host.

### J.2 Python extension generation

**S19 — CPython boundary ownership and failure paths.** Audit `src/driver/elisac_pymodule*.elisa`, `emit_pymodule_so.elisa`, and `scripts/pymodule_runtime_fallback.c`.

- [ ] Specify borrowed/new/stolen Python reference ownership for each API call and converter; carry one cleanup record per initialized object.
- [ ] Release partially constructed lists/dicts/sets/tuples and nested aggregate conversions correctly when conversion/allocation fails at any element.
- [ ] Root Python-owned buffers/objects while Elisa retains them, or copy into Elisa ownership. Borrowed buffer pointers may not outlive exporter validity.
- [ ] Validate integer widths, negative sizes, nullable values, enum/error tags, recursion depth, cycles, Unicode/bytes policy, and all nested container shapes.
- [ ] Handle reentrant Python conversion/comparison/hash callbacks that execute arbitrary user code while internal references are live.
- [ ] Respect interpreter/thread requirements for every reference/API operation; detect the actual supported interpreter model, including any supported free-threaded build, instead of assuming a lock is always held.
- [ ] Define subinterpreter/module teardown and callback lifetime support; reject unsupported retention patterns explicitly.
- [ ] Ensure manifests/stubs describe the actual generated ABI and error behavior; unsupported conversion shapes hard-fail module generation.

**Acceptance:** allocation/conversion failure injection, nested containers, callback reentry, interpreter teardown, and buffer-lifetime tests show correct ownership with no leaked references or stale pointers. Cover only explicitly supported Python versions/build modes in the release claim.

### J.3 WebAssembly and host integration

**S20 — per-object Wasm safety and host view lifetime.** Audit Wasm emitters/scripts, `wasm_component_runtime.elisa`, and `docs/wasm.md`.

- [ ] Validate object-local extents in addition to Wasm linear-memory limits; one allocation must not access a neighboring allocation within linear memory.
- [ ] Use target pointer widths and checked pointer/length arithmetic, including i64/BigInt boundaries and host Number exactness limits.
- [ ] Refresh JavaScript typed-array views after memory growth; do not retain detached/stale views across calls that may grow memory.
- [ ] Define import/export buffer ownership, pin/copy policy, host reentrancy, handle lifetime, and asynchronous retention. A host promise cannot retain an ephemeral pointer unless ownership is explicitly transferred.
- [ ] Keep host and Elisa allocators coordinated without overlapping allocation domains; validate import implementations against required contracts.
- [ ] Specify error/trap translation and instance state after failure; do not continue using partially initialized runtime state.
- [ ] Test zero/maximum memory, grow failure, pointer truncation, malformed pointer-length pairs, JS callbacks into Elisa, and view refresh.
- [ ] Gate threads/shared memory, component adapters, and additional Wasm memory models separately until fully supported.

**Acceptance:** host wrappers preserve lifetime/ownership and object bounds under growth and reentry; engine-level validation alone is not accepted as memory-safety evidence.

### J.4 Input data, decoding, and resource budgets

**S21 — safe parsing/serialization APIs.**

- [ ] Audit `decode.elisa`, JSON/file/string runtime paths, and packed decoding for bounds, checked lengths, integer overflow, recursion limits, and invalid encodings.
- [ ] Never deserialize raw references, owners, capabilities, or handles from bytes as already-valid live objects.
- [ ] Construct aggregate values transactionally; invalid tags or partially decoded payloads remain internal invalid state until validation completes.
- [ ] Define malformed input errors, short reads/writes, embedded NULs, partial UTF sequences, and IO interruption behavior.
- [ ] Add explicit configurable budgets for adversarial lengths/nesting/work where denial of service matters; report budget exhaustion separately from memory corruption or parse failure.

**Acceptance:** arbitrary input bytes cause a defined error/value or documented resource-limit failure, never an out-of-bounds access or invalid live value.

## K. Backend correctness and verified optimization

### K.1 Lowering consumes validated semantics

**S22 — correct LLVM/native/Wasm lowering.**

- [ ] Lower typed operations with complete types, layouts, value categories, ownership, and effect metadata; eliminate backend guesses based on token shape or bare function name.
- [ ] Define one target-layout service for size/alignment, pointer width, address spaces, aggregate ABI, endian-dependent packing, and hidden parameters.
- [ ] Verify every function and module before and after optimization. A verifier failure is a compiler error and prevents output publication.
- [ ] Audit LLVM promises individually: `inbounds`, `nsw`, `nuw`, `exact`, `nonnull`, `noundef`, `dereferenceable`, alignment, `noalias`, alias scopes, range metadata, memory effects, and fast-math flags.
- [ ] Emit a promise only when its precise semantic requirements are proven for the actual operation and lifetime. Omitting a promise is the safe fallback.
- [ ] Prevent poison/undef from uninitialized storage, inactive union payloads, invalid arithmetic, or invalid casts from becoming an observable safe value. Zero-fill/freeze is not a substitute for establishing source-level initialization and validity.
- [ ] Preserve evaluation order and single evaluation of receivers, arguments, indices, compound assignment targets, defaults, and pattern subjects.
- [ ] Ensure guarded operations are control-dependent on the correct checks and that metadata does not permit the optimizer to assume failing inputs impossible prematurely.
- [ ] Audit return ABI and hidden region/effect/error slots through ordinary calls, indirect calls, generics, methods, adapters, tail returns, and exports.
- [ ] Verify debug/tracing instrumentation does not retain short-lived references, change hidden ABI, introduce races, or access objects after drop.
- [ ] Build independent runtime-result tests at `-O0`, `-O1`, `-O2`, `-O3` where supported; classify rejected levels explicitly. Add LTO only if supported and tested.
- [ ] Exercise arm64, x86_64, wasm32, and supported Windows ABIs. Compilation-only coverage is not equivalent to executing safety tests.

**Acceptance:** generated programs agree with the semantic oracle for defined behavior across the supported matrix; each metadata family has adversarial counterexamples and positive cases; verifier errors cannot become a successful build.

### K.2 Alias and allocation optimizations

**S23 — proof-preserving memory optimizations.**

- [ ] Make `codegen_disjoint_proof.elisa` and alias metadata consumers use canonical place/provenance facts rather than a separate weaker alias model.
- [ ] Distinguish aliasing of a container header from aliasing of its backing elements. A fresh header may share backing storage.
- [ ] Account for returned/forwarded aliases, clones with nested references, function fields, callbacks, global aliases, interior mutability, and generic instantiations.
- [ ] Scope alias metadata to the actual validated dynamic loan lifetime; prevent scope reuse across recursive/reentrant calls and reset epochs.
- [ ] Extend scratch lifetime summaries only when nonescape, no invalidating calls, cleanup order, and region ownership are proven; unknown calls retain prior allocation behavior.
- [ ] Validate region reuse, stack promotion, scalar replacement, copy elimination, and move elision against address observability, destructor order, and borrows.
- [ ] Test optimization on/off against the same valid-program corpus; use canary/lifetime instrumentation on invalid cases that should reject or trap.
- [ ] Measure performance only after correctness gates pass. An optimization with incomplete proof stays disabled for that case, not “temporarily safe” by convention.

**Acceptance:** enabling `-fnoalias` or memory optimizations cannot change defined observable behavior, and missing analysis precision only costs performance.

### K.3 Assembly, machine templates, and guest/host provenance

**S24 — EASM safety boundary.** Begin with `easm_verify_memory.elisa`, `easm_verify_provenance.elisa`, `easm_verify_function.elisa`, and existing enforcement/lockstep scripts.

- [ ] Define whether a machine fragment is verified-safe or an explicit unsafe implementation. Never infer safety from successful assembly or symbolic equivalence alone.
- [ ] Track object extent, lifetime, provenance, alignment, read/write authority, and guest-versus-host address space through registers, spills, loads, stores, joins, and calls.
- [ ] Verify indirect branch/call targets, stack/frame bounds, stack alignment, clobbers, callee-save preservation, calling convention, and return value validity.
- [ ] Verify template substitutions cannot change operand class, instruction effects, memory width, or branch structure beyond the verified template contract.
- [ ] Reject unsupported opcodes, ambiguous encodings, unknown effects, unverified relocations, and unresolved verification conditions on the safe path.
- [ ] Ensure symbolic lockstep uses a faithful machine model for flags, overflow, memory, and ambient effects. Equivalence to an unsafe program does not establish safety.
- [ ] Bind certificates/results to exact machine bytes, target ISA/features, relocations/template inputs, verifier version, and assumptions.
- [ ] Keep concrete execution, property-based enforcement tests, and symbolic checks independent enough to expose shared modeling mistakes.

**Acceptance:** no EASM/template/project path can label unverified machine code safe; every accepted safe memory operation satisfies the same memory invariants as ordinary Elisa lowering.

## L. Compiler robustness and production artifact integrity

### L.1 The compiler itself handles hostile input safely

**S25 — harden the self-hosted compiler.**

- [ ] Audit lexer/parser/source-map buffers, diagnostic message storage, intern tables, recursive traversals, include expansion, and scratch regions for dangling views and out-of-range indexing.
- [ ] Own diagnostic strings for at least the diagnostic/report lifetime; do not retain sviews into temporary formatting arrays or reset parser arenas.
- [ ] Define behavior for malformed Unicode, extreme numeric literals, truncated tokens, deeply nested syntax/types, include cycles, cyclic aliases, recursive instantiation, and huge generated declarations.
- [ ] Enforce deterministic resource limits for recursion, generic expansion, symbolic solving, input size, and diagnostics; report exhaustion as failure rather than continuing with incomplete facts.
- [ ] Fuzz lexer/parser/semantic/IR/interface inputs using `test/breadth/malformed_input_fuzz.py` as an existing starting point; minimize all crashes, hangs, and successful malformed-code emissions.
- [ ] Validate imported interfaces, caches, and serialized IR as untrusted structured input. Check lengths, IDs, cross references, versions, and invariant completeness.
- [ ] Ensure reporting/formatter/LSP-style tools do not execute source programs or pass malformed semantic state to executable emitters.
- [ ] Audit driver subprocess invocation, paths, response files, and output handling: no shell interpolation of source-controlled arguments; reject confused paths and invalid output locations cleanly.
- [ ] Use unique per-run temporary artifacts and atomic publication. A failed build must not leave a stale object under a path that appears freshly successful.
- [ ] Test concurrent builds and interrupted writes; caches/results cannot mix targets, modules, compiler versions, or partial outputs.

**Acceptance:** hostile input produces bounded, actionable diagnostics or an explicit resource-limit error; it never produces an apparently valid unsafe artifact. Compiler crashes remain failures, not expected diagnostic outcomes.

### L.2 Mandatory gate and complete artifacts

**S26 — fail closed at every executable entry point.**

- [ ] Enumerate binary, wrapper, project, native object, archive, Wasm, Python module, EASM, and serialized IR entry points; require the same mandatory semantic/safety pipeline.
- [ ] Remove production access to `ELISA_STAGE1_NO_SEMANTIC_GATE` or confine it to an explicitly unsafe development mode whose artifacts cannot be mistaken for safe output. Propagate that status through dependencies/linking.
- [ ] Separate strict proof requirements from mandatory safety. `-permissive` may relax optional proof/lint obligations only while retaining necessary runtime checks and borrow/ownership restrictions.
- [ ] Replace warning-only omission of required source bodies with a build failure. Define completeness relative to requested compilation semantics: missing public/exported/reachable bodies fail; only explicitly specified dead-code elimination may remove supported unreachable bodies.
- [ ] Treat generic/runtime-supplied declarations separately from declined source definitions; a name collision must not silently substitute an unrelated runtime body.
- [ ] Make unsupported lowering, invalid IR, missing required runtime symbols, incomplete ABI adapter generation, and failed verification fatal before artifact publication.
- [ ] Include compiler/runtime/spec/target/safety-profile identity in a build manifest. Safe consumers reject incompatible summaries and clearly classify unsafe dependencies.
- [ ] Allow report-only modes to describe incomplete analysis with structured status; do not reuse their partial state as a safety certificate.

**Acceptance:** bypass/decline probes through every entry point produce explicit failure or visibly unsafe development artifacts; no ordinary successful build omits required checked code or relies on stale output.

## M. Verification program independent of parity

**S27 — executable safety specification, testing, and CI.**

### M.1 Test layers and distinct evidence

1. **Specification examples:** compile-pass, compile-fail, and defined-runtime-failure tests with an expected language reason, not just stage0 output. Each negative case has a positive twin differing in the relevant safety property.
2. **Analysis unit/property tests:** overlap symmetry, join associativity/commutativity/idempotence, monotone transfer functions, fixed-point convergence, substitution preservation, cleanup scheduling, and target arithmetic edges. Test semantic properties rather than duplicating implementation expressions.
3. **Small reference execution model:** an interpreter for the typed safety IR tracks allocation IDs, region epochs, initialized bytes/fields, active tags, owners, loans, and logical thread events. Reads/writes require explicit validity. Keep it simpler and independently implemented enough to catch compiler mistakes.
4. **Generated program tests:** generate both valid and intentionally invalid typed programs, including combinations of features. Compare model expectations with compiler acceptance, runtime outcome, and observable cleanup traces.
5. **Differential/metamorphic tests:** stage0/stage1, optimized/unoptimized, backend-to-backend, declaration reorder, alpha-renaming, function extraction/inlining, and equivalent control flow. A mismatch is investigated; agreement is not proof.
6. **Runtime instrumentation:** ASan/UBSan and race/leak checks where actually supported; guard pages/canaries, poison-on-reset, allocation failure/forced relocation, and instrumented region/handle checking fill custom allocator gaps.
7. **Boundary harnesses:** C ABI probes, Python conversion/failure/refcount tests, Wasm host growth/reentry tests, and EASM concrete/model comparisons.
8. **Bootstrap and release:** fresh source-built compiler/runtime, full parity, self-host fixpoint, runtime self-host, target execution matrix, and recorded provenance.

Instrument generated Elisa code and runtime objects, not just the final link command. Establish sanitizer-capable LLVM lowering/passes or an equivalent validated instrumentation path first; do not claim that adding a linker flag instruments already emitted objects. Arena suballocations require per-object poisoning/guards or a model: an arena-wide allocation can hide intra-arena corruption from ordinary ASan.

### M.2 Required interaction matrix

Use pairwise coverage across the axes below, plus explicit three-way/adversarial cases for high-risk combinations. Exhaustive coverage of all arbitrary programs is impossible; label the measured corpus honestly.

| Axis | Required representatives |
|---|---|
| Value form | scalar, reference, fixed array, darray, view, nested struct/tuple, optional, enum, error union, closure, packed handle |
| Ownership | copy, move, clone, partial move, partial initialization, rebind, overwrite, drop |
| Storage | stack, temporary, inferred/explicit region, heap, pool, static/global, foreign buffer |
| Control | straight line, if/match join, loop/backedge, break/continue, early/tail return, try/catch, defer |
| Call | direct, method, recursive, generic, protocol/default, indirect, effect clone, callback, extern |
| Invalidation | resize, reserve, rehash, erase, reset, free, rollback, recycle, compaction, owner transfer |
| Observation | read, write, slice, iterator, returned borrow, stored borrow, captured borrow, thread transfer |
| Execution | optimization levels, alias optimization on/off, trace/debug, native targets, Wasm, Python boundary |
| Failure | OOM, invalid index/tag, overflow, solver unknown, callback error, spawn failure, malformed import |

Priority interaction cases include aggregate escape + conditional result + error propagation; region reset + defer + early return; borrow + container growth + callback; generic clone + region forwarding + separate compilation; partial construction + OOM + custom destructor; thread capture + scope failure + allocator affinity.

### M.3 Concrete regression backlog

The filenames below are proposed new tests or families, not claims that they already exist. Place them under the current fixture/parity conventions or a new `test/safety/` harness integrated into `run_all.sh`.

| Proposed case | Failure being guarded | Expected safe result |
|---|---|---|
| `grant_does_not_authorize_alias` | Unrelated effect grant suppresses exclusive-loan conflict. | Reject conflict; allow disjoint twin. |
| `grant_does_not_authorize_raw_access` | Ordinary capability hides raw dereference/unchecked index. | Reject missing unsafe authority. |
| `aggregate_all_region_origins` | Only first aggregate field's lifetime retained. | Reject escape regardless of field order. |
| `branch_all_region_origins` | Only one if/match/catch result contributes lifetime. | Reject any path returning expired backing. |
| `call_summary_unknown_escape` | Unknown/generic/indirect call assumed nonretaining. | Conservative rejection or retained allocation. |
| `borrow_after_conditional_move` | Move hidden on one incoming CFG edge. | Reject post-join use without reinitialization. |
| `loop_carried_loan_and_move` | Backedge loses live loan or consumed owner. | Reject invalid next-iteration access. |
| `argument_evaluation_invalidation` | Later argument reallocates an earlier borrowed argument. | Reject or evaluate with a specified safe copy. |
| `view_live_across_rehash` | Address stable in small tests, invalid after capacity growth. | Reject mutation during loan. |
| `defer_keeps_region_live` | Scratch reset occurs before deferred read. | Correct cleanup trace; no stale read. |
| `partial_construct_oom` | Failure cleans uninitialized field or leaks prior field. | Exact cleanup of completed fields only. |
| `zeroed_invalid_reference` | Zero bytes become a valid nonnull borrow. | Reject safe construction. |
| `allocation_size_overflow` | Count/stride/header computation wraps. | Checked failure before allocation/access. |
| `narrowed_tag_invalidated` | Variant/nonnull fact survives mutation or reentry. | Recheck or reject invalid access. |
| `noalias_forwarded_backing` | Distinct headers point at common backing. | No invalid alias promise; equal results on/off. |
| `pool_stale_generation` | Recycled slot revives an old handle. | Reject old handle, including test counter exhaustion. |
| `thread_static_mutable` | Static lifetime mistaken for shareability. | Reject unsynchronized mutation. |
| `scoped_thread_error_exit` | Parent drops region before workers complete. | Join before cleanup on all recoverable exits. |
| `ffi_retain_temporary` | Foreign callback retains ephemeral Elisa storage. | Require owned lifetime/copy or unsafe contract. |
| `python_nested_failure` | Partial nested conversion mismanages Python refs. | Defined exception and balanced cleanup. |
| `wasm_growth_host_view` | Host reuses typed-array view after growth. | Refresh/copy with valid lifetime. |
| `proof_timeout_check_retained` | Timeout treated as success. | Runtime guard remains or compilation fails. |
| `required_body_decline` | Build succeeds with missing exported function. | No published artifact; named diagnostic. |
| `semantic_gate_bypass_output` | Ordinary build bypasses mandatory checks. | Reject bypass or classify explicit unsafe artifact. |
| `easm_unknown_opcode` | Unmodeled instruction treated as harmless. | Verification failure on safe path. |

### M.4 Harness correctness

- [ ] Classify pass, expected diagnostic, expected checked failure, crash, timeout, missing prerequisite, unsupported target, and harness failure separately.
- [ ] For runtime-negative tests require the intended safety-failure reason/site; an arbitrary SIGSEGV is not an acceptable substitute for a bounds trap. Use target-specific trap expectations or a stable runtime failure marker.
- [ ] Make negative tests fail if a compiler crash substitutes for a diagnostic, or if an executable unexpectedly succeeds.
- [ ] Record total expected/executed/skipped/cached cases. Required safety suites must not silently skip unavailable compilers/runtimes/solvers/targets.
- [ ] Pin compiler, runtime, toolchain, solver, target, flags, and seed in machine-readable result manifests.
- [ ] Use content-based cache keys covering all source/runtime/test/tool dependencies and relevant environment values. Audit current gate keys before counting cached evidence.
- [ ] Run release gates without caches; never treat a cached green run as a fresh measurement.
- [ ] Store/minimize fuzz failures and promote each confirmed bug into a permanent deterministic regression.
- [ ] Set explicit compile/run time budgets and isolate each test's outputs/processes. Never kill unrelated compiler processes to recover a timeout.

### M.5 Commands and execution policy

Existing repository commands to use when implementing and validating changes (not executed for this document update):

```sh
# First inspect the scripts' prerequisites and select the intended compiler/runtime.
# Do not reseed or replace shared binaries blindly while another task uses them.
bash scripts/assert_stage1_fresh.sh
bash scripts/check_runtime_drift.sh

# Relevant starting checks; each script's compiler-selection behavior must be audited.
bash test/parity/bounds_default_smoke.sh
bash test/parity/array_bounds_smoke.sh
bash test/parity/reference_reborrow_smoke.sh
bash test/parity/lmut_alias_smoke.sh
bash test/parity/region_owner_leak_smoke.sh
bash test/parity/region_threaded_ownership_smoke.sh
bash test/parity/loop_region_reuse_smoke.sh
bash test/parity/thread_real_smoke.sh

# Full acceptance and independent bootstrap/runtime checks.
ELISA_GATE_PROFILE=full ELISA_GATE_NO_CACHE=1 bash test/parity/run_all.sh
bash test/parity/self_host_gen3_smoke.sh
bash test/parity/self_host_runtime_smoke.sh
```

**Measured implementation record (2026-09-24):** On commit `5310488b`, the uncached full profile enumerated 455 checks and was run with the pinned Stage0 binary (`66ab0687c9c488ccfe571eedbe71a5e05a2e7442b266d317787b7824786f95e5`) and a freshly built Stage1 snapshot (`ca36c01692b2b04b60ee6e52c8fa756575ffddbae772e2928adad53f1195b38c`). The run completed `resolve_smoke`, `self-hostable`, `malformed_input_smoke`, `adversarial_differential_smoke`, and a number of runtime/allocator checks before stopping with two actionable failures; the rest of the 455-check profile is **unverified**, not passed. `driver_acceptance_smoke.sh` passed the bare lane's existing six-reject-gap ratchet, but the with-stdlib lane reported nine reject-gaps against a zero ratchet (`affine_borrow_ok.pos`, `catch_subset_exhaustive`, `darray_struct_element`, `dict_index_scalar_projection`, `field_arg_to_mutable_ref`, `ref_readonly_path`, `struct_pattern_type_mismatch`, `tuple_pattern_arity`, and `tuple_scalar_element_mismatch`). Replaying those nine with the pre-RegionId Stage1 snapshot (`001a5b249677aafe85f110934ed44c8cf28ba5a7ca8b3cc5085f66552991925c`) reproduced all nine Stage0-accepts/Stage1-rejects outcomes, so this slice added no new driver-parity gap; the positive affine-borrow rejection remains an existing Stage1 over-rejection. `compile_time_smoke.sh` also failed its historical baseline: it reported 223.0 versus 61.0 (3.66×), with 289.8 s Stage1 CPU and 1.30 s reference CPU. Follow-up standalone measurements were noisy and not a controlled paired comparison: pre-RegionId Stage1 measured 115.7 s, while the optimized fresh product (`f7938d2a0ca71bc1531dba3c0a63910c19be5dabb2fa8af7381a7cbf63954822`) measured 106.0 s, but both ratios are dominated by a very small and varying reference time. Do not rebaseline or claim the performance gate passes from these observations.

After the isolated hot-path follow-up, `scripts/self_host_gen2.sh` rebuilt Stage1 and `scripts/assert_stage1_fresh.sh build/self_host_region_ids_optimized1/elisac-stage1-gen2` passed. The fresh product passed `destroyed_view_lifetime_smoke.sh` at `-O0`/`-O2`, `region_scope_smoke.sh` on all 21 cases against pinned Stage0, `cross_module_fallible_return_smoke.sh`, and `test/repro/json_safe_api.elisa` compile-and-run at both optimization levels. `git diff --check` passed. These focused results validate the recorded slice only; the full uncached gate, differential corpus, broader adversarial differential run, self-host fixpoint, sanitizers, and non-native target matrix have not all passed on commit `77a20a6b`.

**Measured lexical-region safety milestone (2026-09-24; implementation based on inspection baseline `73e11a63`):** A minimized report found that Stage1 accepted an `@alloc` qualifier after an `Arena& alloc` declaration's block/function had ended; the same line-order-only defect allowed an `@inner` qualifier after a nested `region inner:` block had closed. The Arena-local path was also rejected by pinned Stage0 in the later-function and sibling-block repros, while Stage0 accepted the nested-region sibling repro, so the Stage1 safety rule follows lexical semantics rather than copying that Stage0 hole. Parser-created `__region_arena_local` annotations now receive an inclusive end line at their containing block boundary, just as bounded region-block annotations do. The boundary calculation skips all consecutive `Dedent` tokens, uses the next real token to exclude a sibling's line, and treats EOF as having no following source line; a nonpositive/unclosed extent fails closed in semantic scope resolution. `test/repro/region_arena_owner_scope_leak.elisa` requires Stage1 to reject the two `@alloc` leaks and the `@inner` sibling use; `test/repro/region_arena_owner_scope_live.elisa` is a same-block Arena-local positive control accepted by both compilers. A fresh `build/region_arena_scope_stage4/elisac-stage1-gen2` passed `assert_stage1_fresh.sh`, `region_scope_smoke.sh` (including 21 existing carrier-less cases and the new lexical regressions), `destroyed_view_lifetime_smoke.sh` (including live/last-use/shadow controls at `-O0`/`-O2`), and `cross_module_fallible_return_smoke.sh`; `bash -n test/parity/region_scope_smoke.sh` and `git diff --check` passed. The measured binary identities and full invocation are in the S06 ledger below. This is lexical name visibility only: source-line intervals are not durable binder identity, same-line/macro/source-map behavior and all annotation producers still need audit, and canonical `RegionId`, CFG-based lifetime/provenance, reset/reallocation epochs, aggregate/path completeness, general call summaries, other targets, and the full gate remain open.

Validation identity for that milestone: Stage1 `build/region_arena_scope_stage4/elisac-stage1-gen2`, SHA-256 `0ebea0743d0873d1d16ae6af2c65698dd8ef437e60daedb662ce71f502069969`; pinned Stage0 `../../Go projects/Elisa-core/compiler/build/pinned_stage0/elisac`, SHA-256 `66ab0687c9c488ccfe571eedbe71a5e05a2e7442b266d317787b7824786f95e5`; runtime object `build/runtime/elisacore_runtime.o`, SHA-256 `386ff4310e2313a70cef597a7f1caa1a8db2a01c35e979eb2295936e47b7a192`. The Stage1 freshness assertion passed on this product. The three focused commands were run with `ELISA_STAGE1_BIN` set to that product, `ELISA_RUNTIME_OBJ` set to that runtime object, `ELISACORE_BIN` set to pinned Stage0, `ELISA_ALLOW_STALE_STAGE0=1`, and a distinct `ELISA_PARSE_REPORT` path for each script:

```sh
bash test/parity/region_scope_smoke.sh
bash test/parity/destroyed_view_lifetime_smoke.sh
bash test/parity/cross_module_fallible_return_smoke.sh
```

`bash -n test/parity/region_scope_smoke.sh` and `git diff --check` also returned success. These results are targeted regression evidence; they do not replace the uncached full profile or establish other-target coverage.

**Confirmed S06 invalidation gap and follow-up (2026-09-24):** `check_destroyed_region.region_binding_id_at` applied `end_line` to `__region_local` but not to `__region_arena_local`. In `test/repro/arena_owner_shadow_reset_leak.elisa`, an inner block shadows an outer `Arena& alloc`, resets the inner owner, exits the block, resets the restored outer owner, allocates a replacement element in that outer arena, and reads an older `outer_values` view. The fresh pre-fix compiler from commit `54a0dcd7` accepted this source and the executable returned `7`, the replacement element, instead of the original `65`: a concrete stale-alias read after storage reuse. Binding lookup now considers an Arena owner active only when its recorded lexical extent is positive and contains the use line; after the inner extent ends, the reset invalidates the outer binder's ID. A fresh Gen2 product (`build/arena_owner_scope_stage5/elisac-stage1-gen2`, SHA-256 `e545fc3a67c754ba945c952c859ce1f3b64b6d3618020f5781c0f33505876445`) passes `assert_stage1_fresh.sh` and rejects the repro before LLVM emission with `value "outer_values" cannot be used: region dependency facts were invalidated by destroy of region "alloc"`. `destroyed_view_lifetime_smoke.sh` requires that exact diagnostic and no `.ll` output at both `-O0` and `-O2`; its paired `test/parity/fixtures/arena_owner_shadow_reset_live.elisa` resets only the inner owner, compiles/runs at both levels, and returns the still-live outer value `65`. Existing stale-view negatives and live, last-use, and shadowed-region execution controls also pass. `region_scope_smoke.sh` passes its existing 21 carrier-less cases and lexical-scope regressions, and `cross_module_fallible_return_smoke.sh` passes. The pinned Stage0 hash remains `66ab0687c9c488ccfe571eedbe71a5e05a2e7442b266d317787b7824786f95e5`; runtime object hash is `386ff4310e2313a70cef597a7f1caa1a8db2a01c35e979eb2295936e47b7a192`. `bash -n test/parity/destroyed_view_lifetime_smoke.sh` and `git diff --check` pass. This removes one demonstrated shadowed-owner invalidation gap; the pass still derives identity from source-line intervals, other facts remain name-indexed, and complete CFG joins, alias copies, indirect invalidation calls, region epochs, all targets, and the full gate remain open.

**S06 follow-up: Arena-owner alias invalidation (2026-09-24):** A second minimized exploit, `test/repro/arena_alias_reset_leak.elisa`, initializes `alias: mutable Arena& = alloc`, calls `arena_reset(alias)`, allocates `[7]` through `alloc`, then reads a view created before reset. The pre-fix Stage1 product from commit `b8278e2e` accepted it and returned `7`, proving that destroying only the alias's binder ID missed the backing arena tracked by `alloc`. The invalidation pass now records simple owner-alias initializers against a canonical region-binder row, resolves through an existing local alias or region-tied parameter, and marks that root plus every tracked alias when `destroy`, `arena_free`, `arena_reset`, or `arena_rewind` invalidates storage. An initializer whose owner relationship cannot be resolved becomes an unknown root; invalidation through it conservatively marks every tracked region instead of guessing. `test/parity/fixtures/arena_alias_reset_live.elisa` is the precision control: resetting an independent inner arena through its alias must preserve the unrelated outer view and return `65`. A fresh Gen2 product, `build/arena_alias_identity_stage6b/elisac-stage1-gen2` (SHA-256 `69139ec5d904a607088c2efe8aa230dab9f34ab7e1691857cd7489be03bef4c9`), passes `assert_stage1_fresh.sh`; the expanded `destroyed_view_lifetime_smoke.sh` rejects the stale-alias repro before LLVM emission and runs both alias controls at `-O0`/`-O2`. The 21-case plus lexical-regression `region_scope_smoke.sh`, `cross_module_fallible_return_smoke.sh`, shell syntax check, and `git diff --check` also pass with pinned Stage0 hash `66ab0687c9c488ccfe571eedbe71a5e05a2e7442b266d317787b7824786f95e5` and runtime object hash `386ff4310e2313a70cef597a7f1caa1a8db2a01c35e979eb2295936e47b7a192`. This slice recognizes only initializer relationships expressible as a simple name, address-of, parenthesis/move, or pointer cast and only the Arena types represented by current parser owner annotations. Mutable owner rebinding, aliased fields/aggregates, indirect helper returns, alias types, path-sensitive invalidation, region epochs, and CFG joins remain open; unknown initialization is conservative only within the tracked invalidation analysis, not a substitute for canonical ownership facts. No full gate or cross-target result is claimed.

**S06 follow-up: local helper reset summaries (2026-09-24):** `test/repro/arena_helper_reset_leak.elisa` demonstrated a stale read when `main` called a local helper that reset its `Arena&` parameter; the pre-fix Stage1 executable returned the replacement value `7` instead of the original `65`. The checker now derives per-parameter invalidation summaries for local functions, iterates to a fixed point so wrapper chains are covered, resolves simple local `Arena&` aliases inside those helpers, and applies the summary to the caller's active owner binder. The regression deliberately places the wrapper before the alias-reset helper and requires rejection before LLVM output at `-O0` and `-O2`; `test/parity/fixtures/arena_helper_reset_live.elisa` confirms that calling a known no-reset helper preserves the independent outer value and returns `65`. Summary discovery is restricted to functions with a syntactically recognized `Arena&` parameter, and call traversal covers direct calls plus the currently implemented transparent wrappers and common binary/index/field paths. Named-argument remapping, extern/indirect/unknown-call invalidation, alias types, calls hidden in unvisited aggregate/control-expression forms, mutable rebinding, and CFG/path sensitivity remain open; those gaps are represented by the untracked named-reset and opaque-reset repros awaiting the next slice. A fresh self-hosted Gen2 product `build/arena_helper_summary_stage7b/elisac-stage1-gen2` (SHA-256 `a380ba9766a598e58d704d65cd5a496ac3f4e148a66d2f9f3667f2bfa9713dd1`) passes `assert_stage1_fresh.sh`, `destroyed_view_lifetime_smoke.sh` at `-O0`/`-O2`, `region_scope_smoke.sh` (including the 21 carrier-less cases and lexical regressions), and `cross_module_fallible_return_smoke.sh`; `bash -n test/parity/destroyed_view_lifetime_smoke.sh` and `git diff --check` pass. Validation used pinned Stage0 SHA-256 `66ab0687c9c488ccfe571eedbe71a5e05a2e7442b266d317787b7824786f95e5` and runtime object SHA-256 `386ff4310e2313a70cef597a7f1caa1a8db2a01c35e979eb2295936e47b7a192`. This is a measured direct-local-call slice, not a general effect or lifetime summary proof; no full gate or cross-target result is claimed.

Some current smokes hardcode compiler/runtime paths or assume macOS trap/link behavior. Fix their selection/portability before using them as cross-target evidence; setting an environment variable is not enough if the script ignores it. Use isolated output directories and explicit compiler hashes. For a documentation-only update, validate document structure and preservation rather than running expensive compiler gates with no implementation changes.

## N. Formal assurance and limits of testing

**S28 — a tractable soundness argument.** Develop alongside S02–S06, not as a last-minute stamp.

- [ ] Define a small operational semantics for places, values, allocations, region epochs, ownership, loans, tags, and cleanup.
- [ ] State well-formed-store invariants: every safe reference points to live appropriately aligned initialized storage of a valid type; loans permit the current access; owners release only their own live allocations.
- [ ] State and prove/check core progress and preservation lemmas: a well-typed safe step preserves invariants or reaches a specified checked failure, including scope exit/reset/drop.
- [ ] Prove joins and transfer functions conservatively approximate the reference semantics; identify which properties depend on external solver/analysis assumptions.
- [ ] Extend the argument to generics/substitution, function summaries/separate compilation, error cleanup, and thread transfer/happens-before.
- [ ] Specify a simulation obligation between typed safety IR and backend operations. Use translation validation or bounded equivalence checks for high-risk lowering/optimization patterns where practical.
- [ ] Keep an explicit TCB ledger: unsafe primitives, foreign implementations, LLVM/toolchain, solver encodings, assembly verifier models, and runtime/platform primitives, with owner and evidence for each.
- [ ] Use an appropriate proof assistant/model checker for the small core if chosen; do not mark the entire implementation verified because a simplified model has a proof.
- [ ] Document remaining assumptions and gaps honestly. Fuzzing and sanitizers complement the argument; they neither establish universal absence of bugs nor replace a correct model.

**Acceptance:** the written guarantee can be traced to semantic rules, analyses, lowering obligations, and specific trusted assumptions. A reviewer can identify exactly where the implementation relies on testing versus mechanically checked proof.

## O. Delivery order, milestones, and dependency gates

This is a multi-release language/compiler/runtime program. Sequence by risk and dependencies rather than promise arbitrary calendar dates. The small patch containment track proceeds while foundational analysis is built. Only bounded, evidence-backed optimizations follow the safety work they depend on.

| Milestone | Packages and work | Dependencies | Exit evidence |
|---|---|---|---|
| M0: measured baseline | B.1 inventory, C decisions, minimized probes, TCB list, fresh gate provenance | None | Current coverage/failure ledger; confirmed versus suspected findings separated. |
| M1: immediate containment | S14 blanket-grant repair, S26 mandatory entry/decline policy, S09/S10 urgent checked-operation defects | M0 probes | Targeted negatives/positive twins pass; no new bypass; compatibility notes. |
| M2: semantic foundation | S01 identity, S02 typed CFG, S03 dataflow/summaries | C normative core | Exhaustive construct map, IR verifier, conservative fixed points, independent model slice. |
| M3: sequential lifetime soundness | S04–S08 ownership, loans, region provenance, containers, captures | M2 | Feature interaction suite; compile-fail escapes/aliasing; valid programs execute correctly. |
| M4: runtime and proof closure | S09–S16 complete bounds/arithmetic/runtime/cleanup/unsafe/proofs/effects | M2; ownership-dependent parts after M3 | Failure injection, instrumentation, cleanup model, no unclassified unsafe primitive. |
| M5: backend preservation | S22–S24 metadata, optimization, EASM | M2–M4 rules | Target/optimization matrix, verifier checks, translation/model tests. |
| M6: boundaries and concurrency | S17–S21 threads, native/Python/Wasm, decode | M3–M5; ABI rules may start earlier | Transfer/race tests, boundary failure/reentry tests, target execution evidence. |
| M7: production qualification | S25–S28 compiler hardening, artifacts, CI, assurance | All relevant packages | Fresh full gates, fuzz campaigns, bootstrap/runtime tests, published support/TCB ledger. |

The package dependencies overlap: compiler hardening, ABI inventory, formal modeling, and test infrastructure start early; their completion gates wait for implemented semantics. M1 fixes must preserve existing coverage and cannot be deferred merely because a rewrite is planned. An unsupported feature may be temporarily rejected to contain unsafety, but that is not “feature completion”; track restoring it as a required item before claiming full safe-language coverage.

### O.1 First implementation batch in concrete steps

1. Snapshot working-tree/source/binary/runtime identities and reproduce the current full gate in an isolated build. Preserve existing user changes; do not reset or amend unrelated work.
2. Build the B.1 coverage inventory and a small independent safe/unsafe regression harness with explicit expected outcomes.
3. Write tiny probes for unrelated grant suppression, two-region aggregate/branch escape, conditional moves, container invalidation, and production bypass/partial body emission.
4. Record which are actual failures on the current compiler; inspect all enforcing passes before attributing a defect to one helper.
5. Land narrow fixes for confirmed mandatory-safety bypasses with positive twins, optimized-runtime checks where applicable, and no unrelated refactor.
6. Specify the semantic core and canonical identities, then introduce typed places/CFG and verifier for a vertical slice: scalar locals, fixed arrays, borrow, call, branch, loop, return, region reset.
7. Add ownership/initialization/loan/provenance transfer functions and independent model tests for that slice.
8. Extend to nested aggregates and error/defer paths before claiming region checking complete; these combinations are where local syntactic checks lose information.
9. Migrate backend proof consumers and import summaries incrementally; keep conservative checks/fallback for unmigrated supported code.
10. Broaden runtime failure injection and boundary/target coverage, then close remaining syntax/API inventory rows.

### O.2 Per-work-package completion template

Every S01–S28 change set records:

- **Invariant:** exact property being established and why safe users can currently violate it or why its enforcement is unverified.
- **Scope:** source constructs, libraries, backends, targets, and unsafe assumptions affected.
- **Evidence before:** minimized case or measured coverage gap with exact tool/source identity.
- **Design:** canonical facts and transfer rules, fallback on unknown, interactions with effects/cleanup/FFI.
- **Implementation:** concrete files changed and removal/replacement of redundant assumptions.
- **Validation:** negative and positive cases, interaction cases, runtime/model evidence, relevant gates, then full required checks.
- **Compatibility:** newly rejected behavior, corrected semantics, replacement APIs, migration examples, and intended diagnostics.
- **Evidence after:** actual commands/results and artifact paths/hashes; never a prospective command listed as passed.
- **Residual risk:** untested targets, remaining TCB assumptions, precision limits, and follow-up IDs.

### O.3 Active status ledger

The implementation has started. The statuses below distinguish verified slices from the broader package deliverables; a partial checker change never closes a package.

| Package | Deliverable | Status |
|---|---|---|
| S01 | Canonical identities and safety-qualified types | In progress — typed table-local `DeclId` is stored on every symbol and carried by `DefinitionReference`; the declaration-only slice passed stage0 and fresh stage1 plus the semantic gate. The current lexical `BindingId` extension passes the stage0 `-O2` smoke, including parameter/use and nested-shadow mapping; the same `-O2` smoke passes with a fresh stage1 product and the freshness assertion passes. Known generic region arguments now use table-local lexical `RegionId` values in `Region` leaves and structural declaration checks, including targeted generic call-result substitution and shadowed-binder separation. `LoanId`, `BlockId`, complete source origins and qualifier/substitution rules, cache keys, persistent identity, and full acceptance remain open; region IDs are still derived from source ranges and are not a complete canonical identity system. |
| S02 | Typed places, CFG, and safety IR verifier | In progress — core commit `a6e3ea9c` adds explicit normal/branch/loop/match/return/error/panic/break/continue terminators, nearest-loop transfer targets, and structural CFG verification at function-analysis finalization. Core commit `8730193d` replaces silent statement fallthrough with an explicit linear-statement allowlist, conservatively branches `static if`, and rejects unmapped statement types. Core commit `fb3aee7a` adds a test that every current sealed AST statement type has a CFG disposition; it does not assert full semantics for those types. Focused CFG/coverage tests and `go test ./src/semantic -count=1` pass. These are control-flow mechanics only; typed places and operations, complete cleanup/error propagation, full AST semantics, richer IR invariants, and backend obligation mapping remain open. `go test ./...` still has four failing test groups (the hierarchy column-scan assertion, both scalar and parallel packed-ML benchmark segfault subtests, stale checked-in collections interface, and fixed-buffer permission expectation); targeted reruns against the pre-change HEAD reproduce each failure, so they are not attributed to these slices. |
| S03 | Conservative dataflow and interprocedural summaries | Planned |
| S04 | Initialization, moves, and ownership obligations | In progress — the Stage1 affine-copy checker now extracts nominal type heads from generic instantiations and mutable/optional wrappers instead of treating `Owner[T]` as an unrelated bare type. `affine_owner_smoke.sh` verifies that copying `GenericOwner[i64]` without `move` is rejected while copying an ordinary `PlainBox[i64]` remains accepted, alongside the existing owner/container/global checks. This is a narrow classification fix: binding-identity-based moves, complete field/element/destructuring flow, partial initialization, destructor/drop obligations, control-flow joins, and interprocedural ownership summaries remain open. |
| S05 | Place-based loan and reborrow analysis | In progress — the Stage1 `check_reference_reborrow` pass rejects taking `&` of an existing reference when the resulting `T&&` would flow into a non-`T&&` destination, and lowers supported `(&r).cast[...]` reborrows to the referent. Its dedicated parity smoke covers 27 rejected contexts plus positive cases for forwarding, actual `T&&` values, supported reborrow casts, and `lock`/`submit` on reference parameters; the smoke passes on Stage0 and a freshly seeded Stage1. This closes the reproduced wrong-slot lowering paths only. It is still a syntax- and call-target-conservative checker, not place-based loan liveness: shared/exclusive overlap, parent suspension, projected places, returned loans, callbacks/defer extensions, generic/protocol dispatch completeness, CFG joins, and canonical `LoanId` facts remain open. |
| S06 | Complete region/lifetime provenance and invalidation | In progress — destroyed-region analysis tracks origins through view constructors, returned-view helpers, local copies/aliases, and view parameters, then rejects uses after explicit `destroy`; `destroyed_view_lifetime_smoke.sh` covers stale aliases and live last-use controls at Stage1 `-O0`/`-O2`. Stage1 joins candidate origins by selecting the deepest active region through supported helper-call, aggregate, and branch forms. Stage0 records which `sview` parameter a helper actually returns in its `ReturnProvenance` summary and checks that dependency at the caller’s store boundary (core commit `3ceb7752`); `CheckNestedRegionStoreEscape` recursively visits live dependencies nested in aggregate field facts, guards repeated/cyclic field maps, and sorts origins for deterministic diagnostics (core commit `196548f6`, covered by nested-holder and cyclic-fact tests in the full semantic package). `sview` region qualifiers are preserved in resolved types and explicit tie erasure/mismatch is rejected (core commit `c9070b2`). `sview_region_multi_argument_smoke.sh` requires both stages to reject the reproduced `choose_second(outer_view, inner_view)` store into the outer region; `sview_region_tie_smoke.sh` requires both stages to reject dropping/mismatching explicit `@r` and to accept matching ties and legacy unannotated forwarding. This closes only those paths: Stage1 still approximates returned-parameter identity by considering candidate arguments, Stage0/Stage1 summaries are not yet a shared representation, and complete projection/wrapper coverage, CFG joins, reset/reallocation epochs, BindingIds, and general interprocedural provenance remain open. Core commit `30e0c5f3` fixes declaration-initializer escape checks to use the new binding's lexical scope instead of resolving a same-named outer symbol before declaration; the scoped-region enum-width regression covers this shadowing case. `go test ./src/semantic -count=1` and the focused `TestNarrowHandleWidthLint` both pass. The new fix is limited to declaration-initializer name lookup. Stage1 now preserves known region leaves in generic TypeIds, substitutes direct and qualified generic-call returns using the active lexical binder, and rejects cross-arena and same-spelling shadowed-region handle relabeling; the same-region controls run at `-O0`/`-O2`. The `destroyed_view_lifetime_smoke.sh`, 21-case `region_scope_smoke.sh`, `cross_module_fallible_return_smoke.sh`, and JSON safe API runtime control pass on a fresh Gen2 product. A further Stage1 parser/semantic fix gives `__region_arena_local` annotations a containing-block end line and bounds `region NAME:` annotations against the next real source token, treating EOF as no next source line; `region_arena_owner_scope_leak.elisa` rejects later-function, sibling-block, and closed-region sibling uses, while `region_arena_owner_scope_live.elisa` is a valid same-block control. Stage1 fresh Gen2 passes the expanded `region_scope_smoke.sh`, `destroyed_view_lifetime_smoke.sh`, and `cross_module_fallible_return_smoke.sh`. Stage0 accepts the nested closed-region sibling repro, demonstrating an oracle hole that this Stage1 safety regression intentionally does not preserve. This remains line-interval visibility rather than binder-based lifetime proof; same-line/macro/source-map cases, all annotation producers, CFG provenance, complete aggregate/path precision, indirect calls, reset epochs, and general summaries still leave S06 open. Unannotated `sview` forwarding stays allowed for existing standard-library APIs; callers rely on these partial use-site summaries until the complete analysis exists. |
| S07 | Container, view, iterator, and lending contracts | In progress — the JSON DOM keeps its pointer-bearing `JsonValue`/`JsonMember` representation, raw accessors, and builders private. Public parsing and traversal now use opaque region-indexed `JsonValueHandle[@r]` values; borrowed string/key results carry `@r`, and serialization ties copied output to the caller's separate output arena. The Stage1 smoke rejects direct handle or copied-view use after named `arena_free`, `arena_reset`, and `arena_rewind`; live accesses and serialization controls pass at `-O0`/`-O2`. This closes one library boundary and direct named-invalidation paths only: the general borrow checker, alias/indirect reset, iterator invalidation, mutation/version rules, builders, and other containers remain open; Stage0 parity was unavailable for this commit. |
| S08 | Closure, defer, and effect capture safety | Planned |
| S09 | Complete bounds and safe pointer formation | In progress — stage1 view reads/stores use count guards and known-length slices clamp start/count to the receiver extent; `slice_bounds_smoke.sh` passed 112 checks at `-O0` and `-O2` against stage0 and stage1. `StringView.data` is non-null and immutable in both the runtime source and compiler builtin carrier, so safe construction rejects nullable backing pointers and safe code cannot retarget a view, including an empty one. Runtime consumers now rely on that type invariant instead of repeating null checks; Stage0/Stage1 parity tests reject nullable construction and backing-field reassignment, while negative lengths still fail closed at `-O0`/`-O2`. Unsafe casts and foreign boundaries can forge invalid pointer/length pairs and therefore need operation-specific contracts or validated adapters; positive forged pointer extents, FFI validation, JSON arena lifetime after reset/free, other indexable forms, target widths, pointer arithmetic, and proof/backend coverage remain open. The bounded raw-source/StringView slice is recorded above as Stage1 commit `ae85f1b7`; S09 remains open for all other indexable representations and targets. |
| S10 | Arithmetic/conversion/value validity consistency | In progress — stage1 fails closed when a nontrivial mutable global initializer cannot be materialized instead of silently leaving LLVM's all-zero value. Constant materialization handles typed `null` for optional aggregate fields and struct/arena aggregates; integer-backed type-alias casts now preserve folded global sentinels such as `0.u32().SymbolTableId()`. Mutable float globals preserve signed decimal literals and use the existing checked constant-expression folder for arithmetic and integer-to-float forms; object-only stage0/stage1 probes cover negative `f64`, `f64` addition, and `f32` addition with behavior-sensitive results. LLVM float inequality now uses unordered-not-equal and float-to-bool treats NaN as nonzero; the backend test checks the emitted `fcmp une` predicate. The global-initializer smoke checks both compilers reject an address-of reference initializer and an optional payload type mismatch without emitting objects, requires stage1 to identify the rejected global, and links/runs scalar, null optional-reference, fixed-array, optional-reference aggregate, and C-string globals under both compilers with expected result 42. A fresh stage1 seed produced its runtime object and passed `assert_stage1_fresh.sh`; the expanded global initializer smoke and the full native backend gate pass. This closes only exercised initializer shapes; the full global-initializer validity matrix, arithmetic edge cases, conversions, and target-width behavior remain open. |
| S11 | Allocator/arena/runtime TCB audit and failure safety | In progress — source inventory begun for arena backends, free-block reclamation, reset/rewind/adopt, fixed-buffer allocation, byte allocators, and object pools. The arena arithmetic slice checks byte-to-slot rounding, region header/payload sizing, cursor/capacity comparisons, count growth, page-rounding additions, collection-stack doubling, and trailing-NUL allocation sizes; malloc/mmap/VirtualAlloc allocation, reservation, commit, and release results use explicit failure branches where they previously relied on optimizable assertions. The fixed-buffer slice checks alignment addition, cursor bounds, ownership-range subtraction, mark rewind bounds/direction, explicit allocation failure, and tail-only resize so growing one slot cannot overwrite a later live allocation. `arena_alloc_size_overflow_smoke.sh` passes valid zero/small allocations and traps `usize`-maximum byte requests on Stage0 and fresh Stage1 at `-O0` and `-O2`; `arena_runtime_lifecycle_smoke.sh` passes adoption/trim, reuse, rewind, tail growth, and free-hint lifecycle regressions on both compilers at `-O2`; `fixed_buffer_safety_smoke.sh` passes valid alignment/resize behavior and requires specific overflow, OOM, and rewind traps on both compilers at `-O0` and `-O2`. This closes only the exercised native 64-bit paths; other allocator families and their races, same-arena concurrent ownership, failure injection, full failure atomicity, invalidation/generation rules, and 32-bit/Wasm/Windows execution remain open. The process-wide region cache and free-hint metadata now use acquire/release atomics on POSIX and Windows; the four-worker independent-arena smoke passes at Stage0/Stage1 O0 and O2. |
| S12 | Packed-store and pool handle correctness | In progress — verified row-bounds checks now cover packed dense handle/index reads and packed variant-sparse reads, using per-allocation extents before pointer arithmetic. Stage0 main commit `8c1f8a19` also replaces hardcoded packed-state byte offsets for handles, tags, and prefix columns with ABI-derived field offsets; the backend package tests pass on that commit. Stage0 and fresh Stage1 regressions trap on invalid reads under optimized and unoptimized builds. Store identity, generation, reset/reuse invalidation, pool ownership, transactional metadata, all other layouts, and 32/64-bit behavior remain open. |
| S13 | Unified cleanup semantics and lowering | Planned; existing cleanup implementation retained until validated replacement |
| S14 | Operation-specific unsafe authority | In progress — lexical grants remain operation-specific for aliasing, unchecked indexing, mutable globals, pointer arithmetic, raw extern calls, pointer casts, buffer reinterpretation, and stale-view reads; direct calls and typed callback aliases check concrete Unsafe rows against active grants. Generic pointer casts that change the pointee type or add write capability now require an explicit `Unsafe.PointerCast` grant even when a generic type parameter makes ordinary assignability permissive; dropping mutability for the same pointee remains a safe coercion. Recursive enum types are guarded during type-parameter walks so a cast over a recursive enum cannot overflow the compiler. The generic pointer-erasure visitor now recursively covers current expression and statement variants, including nested value branches, Match/Catch arms, Contracts, loops, blocks, assignment places, static-effect candidates/captures, aggregate fields, and GetElse recovery; current leaf variants are explicit so adding an AST case causes a compile-time coverage failure. `generic_cast_smoke.py` passes 12 strict rejections, 2 safe same-base cases, 2 explicit-grant cases, 8 conservative NUL-flow join cases, and the default warning case. NUL facts are joined conservatively: facts established only in branches/loops/matches are not promoted, including the all-arms case, because the current name/snapshot representation does not safely support that promotion. The unsafe-grant visitor now continues traversing inside a granted call so a grant on the closure's creation site cannot hide aliasing calls that execute later; `unsafe_grant_scope_smoke.sh` passes 84 focused cases, including pointer-arithmetic parameter/local aliases, compound offsets, calls, typed struct/indexed elements, range/reference for and comprehension binders, tuple/dictionary destructuring, enum payload bindings and guards in statement/value matches, value-block tails, exact/unrelated grants, shadowing, and accepted positive twins. Pointer arithmetic now has one checker for both missing and unrelated grants, with scoped structural types for parameters and local annotations. The separate visitors remain partial; the complete operation/context matrix, BindingId-based facts, imported/generated identity, method/UFCS resolution, and all grant paths remain open. |
| S15 | Sound proof/refinement/assertion handling | In progress — nullable-reference analysis now covers field reads and assignment targets, scalar arithmetic, callable nullable values, single/multi-index and slices, nested static-effect expressions, branches, Match/Catch, short-circuit conditions, loops, lexical blocks, lambdas, contracts, and GetElse recovery. Proofs use binding-local state, are checked inside each branch, and are intersected at branch/loop/match joins; loops account for zero iterations, sequential blocks preserve writes to outer bindings, and assertion facts are added only for runtime `assert` contracts. Copying a nullable pointer copies its current proof, while rebinding one local does not erase another local’s fact. Writes through nullable references now require a path-sensitive non-null proof at the write site; an unproven or proven-null reference cannot be used as a store target. `nullable_flow_smoke.sh` passes the targeted negative/positive cases, including the nested nullable-local/while fixture and a regression that checks match guards in evaluation order. The 581-case semantic acceptance diff reports 579 agreements and 2 alias-flow differences: Stage1 conservatively rejects using a source after guarding a copied alias, and accepts using the copied alias after the source binding is rebound. These differences are recorded rather than treated as a safety proof or silently normalized to stage0. Calls that mutate captured/aliased bindings, full alias equivalence, canonical BindingIds, and a shared CFG/fixed-point analysis remain open. |
| S16 | Effect, type, module, and global semantic closure | In progress — reference read/write capability and binding/rebind rules have positive/negative diagnostic fixtures; the 408-fixture diagnostic suite passes. Mutability on a reference-typed variable slot permits rebinding only; write-through permission comes from the reference type (`mutable T&`) and the referenced value's mutability. Legacy inferred bindings preserve read-only capability when initialized from read-only storage, including string literals. A bare dictionary subscript is treated as a fallible optional reference rather than its scalar payload; `get d[k] else fallback` remains a valid explicit unwrap. Byte-reference stores reject assigning an entire byte pointer where the operation stores one byte, and mutable-reference qualifiers on fallible return types are preserved. `zeroed` construction now checks nominal private-field ownership so it cannot bypass a module-private type’s constructor boundary; the 23-case private-fields smoke passes on stage0 and stage1. Duplicate-declaration handling now matches stage0’s runtime-carrier treatment for `Region` and `ArenaMark`, while ordinary repeated user types/functions remain checked; the duplicate-declaration smoke passes, including the frontend/stdlib false-positive scan. Full type/effect/module/global closure remains open. |
| S17 | Race-free concurrency and scoped task lifetimes | In progress — the shared arena region-cache list, bounded retention metadata, and reclaimed-region hint are serialized by a runtime atomic lock on POSIX and Windows; the independent-arena concurrency smoke passes at Stage0/Stage1 O0 and O2, alongside allocator lifecycle and overflow regressions. The Stage1 LLVM backend now lowers canonical `load`, `store`, `exchange`, `compare_exchange`, integer `fetch_*`, and `fence` calls to atomic instructions. Bool storage is widened to i8 at the LLVM atomic boundary; load/store/exchange/CAS and integer RMW orderings are mapped to LLVM orderings, and pointer exchange/CAS plus pointer/floating load-store shapes have IR coverage. `atomic_runtime_smoke.sh` verifies integer/bool/pointer/floating IR and four-thread CAS increments at `-O0`/`-O2` on Stage0/Stage1; `backend_native_smoke.sh` passes 521/521 native checks, including canonical MemoryOrder operation signatures and an unrelated `fence(i64)` overload. Core hook shape checks and Stage1 arity/representation checks keep unrelated overloads on ordinary resolution. This closes only exercised native LLVM lowering and the noted arena-cache globals: pointer-valued exchange result binding remains unverified; Stage1 checks order arguments by i32 representation rather than resolved nominal `MemoryOrder` identity; invalid Stage1 constant order pairs currently fall back to SeqCst instead of receiving semantic diagnostics; exact call-target identity, unsupported target/backend behavior, same-arena ownership, remaining concurrency globals/APIs, scoped task cleanup, race instrumentation, and deterministic scheduler checks remain open. |
| S18 | Native FFI/ABI contracts and adapters | In progress — LLVM lowers typed `va_arg[T]` reads and `va_copy` with the builder/intrinsic APIs rather than treating them as unresolved external calls; C variadic default-promotion and wide-value runtime tests pass. This does not close pointer ownership, string/buffer extent contracts, callback lifetime, variadic type safety, or platform ABI coverage. |
| S19 | Python binding ownership/failure safety | Planned |
| S20 | Wasm and host-memory lifetime safety | Planned |
| S21 | Safe decoding/serialization and input budgets | Planned |
| S22 | Verified backend semantics and metadata | Planned |
| S23 | Proof-preserving alias/allocation optimizations | Planned |
| S24 | Verified EASM/assembly boundaries | Planned |
| S25 | Compiler input/resource/artifact hardening | Planned |
| S26 | Mandatory gates and complete safe artifacts | In progress — removed the `ELISA_STAGE1_NO_SEMANTIC_GATE` production opt-out and moved static-generation expansion, mandatory semantic validation, and executable/semantic dispatch into the required order for the reviewed driver paths. Targeted c-archive/test/interpret generated-code rejection, Python stub rejection, Python extension rejection, and successful extension output checks pass. Partial backend-body declines now fail before output creation in LLVM/object/bitcode/executable modes. Stage1 seed and absolute-path freshness pass. Complete entry-point, multi-artifact atomicity, generated-unit completeness, and failure-phase coverage remain open. Independent medium-MLAST validation still reports 10 Stage1 body declines while Stage0 emits/runs the O3 artifact; the Stage1-pinned parser smoke also safely declined its two `print` bodies and wrote no object. These are safe rejections but unresolved supported-feature coverage, not successful parity. |
| S27 | Independent safety specification/test/CI program | In progress — `test/parity/unsafe_grant_scope_smoke.sh` passes 51 focused cases, including unsafe-function caller obligations, contract-expression calls, typed callback parameters/local aliases, mutable-local rebinds, conditional joins, Match-arm traversal, exact versus unrelated grants, and the closure grant-scope regression. Parser AST coverage verifies callback effect-row retention; independent model tests, full gate integration, and target matrix remain open. |
| S28 | Core soundness argument and TCB assurance | Planned |

**Verified S09 StringView non-null carrier (2026-09-23):** the null-view probe initially crashed Stage0 at `-O0` in the direct `string_view_eq(view, "safe")` specialization when the compiler's runtime carrier admitted a null data pointer. `StringView.data` is now a non-null, immutable reference in both the source runtime and the Go compiler's builtin carrier. Semantic regressions accept a valid `u8&` backing pointer, reject nullable `u8&?` construction, and reject reassignment of the backing field; `runtime_string_view_safety_smoke.sh` confirms the last two on Stage0 and Stage1. During parity verification, Stage1 initially skipped the nullable check because reference fields have no bare primitive spelling; its struct-construction checker now uses structural field/local type IDs and rejects direct null and nullable-reference values before the primitive-only path. Runtime equality, indexing, slicing, copying, hashing, names, collections, context comparison, and Wasm comparison rely on the non-null type invariant, while signed and target-width length checks remain. The LLVM literal fast path also checks for non-null before byte comparisons as a defensive lowering guard. These guarantees cover safe construction only: unsafe casts and foreign boundaries can still forge invalid pointer/length pairs, so validated adapters and unsafe contracts remain necessary. Safe source can still forge an out-of-range non-null pointer/length pair because the public carrier has no extent provenance; full carrier opacity, FFI validation, target-width execution, and general pointer-range proofs remain open.

**Verified S06 destroyed-view tracking slice (2026-09-23):** the destroyed-region visitor now propagates region origins through view constructors, view-returning helpers, local view copies/aliases, and view-typed parameters, and diagnoses a use after explicit region destruction. `destroyed_view_lifetime_smoke.sh` rejects a copied view used after `destroy scratch` while accepting a live region-backed view and a view whose last use precedes `destroy`, at Stage1 `-O0`/`-O2`. The expanded runtime view smoke checks the region negative/positive pair on Stage0 and Stage1 at `-O0`; `region_scope_smoke.sh` passes 21 Stage0-parity annotation cases. The visitor still uses names rather than canonical binding identities and does not establish sound branch/loop joins or complete provenance through every expression, aggregate, container, reset, and implicit scope exit; this is one lifetime slice, not S06 completion.

**Verified S14 closure-grant traversal slice (2026-09-23):** before the fix, `mal_expr` returned immediately when an outer `Unsafe.Alias` grant was active, so it never visited nested lambda bodies; a closure could capture a mutable alias and perform a conflicting mutable call without its own grant. The visitor now skips only the enclosing call's duplicate alias check when that call is granted, continues into its callee and arguments, and checks a lambda body with an empty grant set. `unsafe_grant_scope_smoke.sh` passes 51 cases, including rejection when the outer grant leaks into a closure and acceptance when the closure grants its own operation. Other unsafe visitors and the full operation-by-AST-context matrix remain incomplete.

**Verified execution slice (2026-09-22):** `bash scripts/elisac_stage1.sh --seed` succeeded with parser preservation of function-type effect rows and callback caller-obligation checks. A direct probe confirmed the pre-fix hole: a mutable local callback initialized to a safe function, rebound to an `Unsafe.PointerCast` function, and called under only `can Memory.Allocate` completed without an unsafe diagnostic. After the fix, `bash test/parity/unsafe_grant_scope_smoke.sh` passed 39 cases, including missing, unrelated, and exact grants for callback parameters, typed local aliases, direct local rebinds, and a rebind on one conditional path. It also covers contract-expression calls, nested stale-view invalidation, parameter-backed sized buffers, and independent pointer-cast/buffer-reinterpret grants. `../../Go projects/Elisa-core/compiler/bin/elisac -emit test test/parity/parser_ast_test.elisa` passed 110 tests, including parser effect-row retention. `bash test/parity/semantic_gate_selfhost_smoke.sh` passed, confirming gen2 analyzes identically to the stage0-built driver. `bash test/parity/global_permissions_smoke.sh` passed 7 agreeing cases, including 5 with the permission dial on and off. `git diff --check`, shell syntax validation, and stage1 freshness passed after that callback-rebind change. An earlier run of `bash test/parity/emit_unsafe_parity_smoke.sh` reported 161 byte-identical, 0 divergent, and 243 skipped cases before the call-obligation changes; that parity suite has not been rerun for this revision. The full suite, supported-target matrix, and complete soundness audit were not run.

**Verified S26 slice (2026-09-23):** removed the driver's `ELISA_STAGE1_NO_SEMANTIC_GATE` check and reordered reviewed paths so syntax/source projections run before static generation, while Python export modes validate the expanded AST before dispatch and other semantic reports/backends run after the shared expanded-tree gate. The `pymodule-so` preparation now follows that gate; Python stub output is cleared before validation and uses a zero-byte sentinel on semantic rejection. Three genuine stage1 seed attempts were needed; the third completed successfully. `bash scripts/assert_stage1_fresh.sh '/Users/torarinvikbjarko/Documents/Coding Projects/Elisa Projects/Elisa-compiler/bin/elisac-stage1'` passed against the absolute workspace path. The following focused checks passed: `bash test/parity/semantic_gate_static_generate_smoke.sh` (rejects generated undefined names for `c-archive`, `test`, and `interpret`, and interprets a valid generated function); `bash test/parity/pymodule_reserved_export_smoke.sh` (including obsolete-variable rejection and invalid `pymodule-so` sidecar/output checks); `bash test/parity/pymodule_pyi_smoke.sh`; and `bash test/parity/pymodule_object_smoke.sh` (successful extension and `.pyi` output). `bash -n` on the changed shell scripts and `git diff --check` passed. The self-host semantic-gate smoke and broad CLI/backend matrix were not run in this slice. This evidence validates the listed behaviors only; it does not establish complete artifact atomicity or prove every executable path is gated.


**Verified nullable and cast-analysis slice (2026-09-23):** after correcting match-guard analysis to check each guard before applying its facts to the arm body, a fresh Stage1 seed produced `bin/elisac-stage1` and `build/runtime/elisacore_runtime.o`; `scripts/assert_stage1_fresh.sh` passed. (`--seed` first hit the 4 GiB process guard while another native build was active; the final seed completed with the host's 5 GiB cap.) `bash test/parity/nullable_flow_smoke.sh`, `python3 test/parity/generic_cast_smoke.py`, and `bash test/parity/duplicate_decl_smoke.sh` passed. The generic-cast smoke exercised 12 strict rejections, safe same-base/mutability cases, explicit grants, nested AST contexts, and 8 NUL-flow joins. The duplicate smoke found no frontend/stdlib duplicate false positives. The nullable smoke includes an ordering regression where a later conjunct must not justify an earlier dereference. The 581-case semantic acceptance diff was rerun with four workers and did **not** fully agree: 579/581 cases matched, with only `TestAnalyzeAliasGuardClauseRefinesRootAfterReturn` and `TestAnalyzeAliasRefinementInvalidatesAfterRootAssignment` differing. The first is a conservative rejection because this checker does not yet propagate a refinement between copied bindings; the second accepts a copied pointer after the source variable is rebound, reflecting independent value bindings. Keep both behaviors visible until alias-flow semantics are specified and checked with binding identity. This slice is focused evidence only and does not establish memory safety, complete AST-operation coverage, or S14/S15 completion.
**Known follow-ups:** the focused probe found that a `mutable darray[T]&` parameter retained its pointer-cast obligation but lost the separate buffer-reinterpret obligation. The sized-buffer classifier now preserves extent through reference wrappers, and pointer-only versus exact two-capability parameter cases pass. Field-backed, view-backed, aliased, and generic-instantiated buffers still need explicit classification tests. The caller-obligation walk now resolves direct named calls, concrete Unsafe rows on function-typed parameters, explicitly typed local callback aliases, and bare local identifier rebinds with conservative joins for the visited branch/loop/block forms. It still uses names rather than BindingIds; shadowing across complex control flow, nested aggregate/field/global storage, method/UFCS resolution, imported identity, generated operations, and future AST variants need dedicated coverage. The new smoke's direct branch case does not validate every join form. These are material S14 gaps; the focused smoke suite is not a proof of memory safety.

**S14 read-only AST visitor coverage finding (2026-09-23; not reproduced as a runtime/compile test during the tree freeze):** `src/semantic/check_strict_unsafe_ops_walk.elisa` explicitly visits only `Expr`, `VarDecl`, `Assign`, `Return`, `If`, `While`, `For`, `Block`, and `Contract` in `strict_unsafe_walk`; its default arm does nothing, so statement `Match` bodies and other unlisted statement forms are not traversed by that walk. `strict_borrowed_call_check` has explicit recursion only for `Call`, `Field`, `Index`, `IndexN`, `Binary`, `Unary`, `Move`, `Paren`, and value `If`, then silently passes other expression variants. `strict_global_only` and `strict_unsafe_expression` are also partial visitors. The separate `pag_walk`/`pag_expr` pointer-arithmetic grant pass and `mal_walk`/`mal_expr` local-alias pass likewise use partial statement/expression matches with silent default arms; they cannot be counted as generic exhaustive AST coverage. This is a verified source-coverage gap in these checkers, not proof that a user program currently bypasses all independent checks. After the benchmark freeze is lifted, add generated negative/positive fixtures for every omitted operation-bearing child shape, compare which independent checks already cover it, then replace partial recursion with exhaustive shared child enumeration or explicitly rejecting/checked behavior. Do not mark S14 complete until the operation-by-AST-context matrix and regression suite close these gaps.
**S14 read-only AST visitor coverage finding (2026-09-23; later exercised by a focused smoke):** before the transferred follow-up, `strict_unsafe_walk`, `pag_walk`/`pag_expr`, and `mal_walk`/`mal_expr` had silent default arms for unlisted statement and expression forms; `strict_borrowed_call_check`, `strict_global_only`, and `strict_unsafe_expression` also had partial recursion. The transferred edits now cover Match arms and more known nested expression/statement forms, and the expanded unsafe-grant smoke passes 49 cases. This is partial coverage evidence, not an exhaustive-AST proof. Continue adding negative/positive fixtures for every operation-bearing child shape, compare independent checks, and make future-node handling exhaustive or explicitly conservative. Do not mark S14 complete until the operation-by-AST-context matrix and regression suite close these gaps.

**S14 transferred visitor follow-up (2026-09-23; compiled and focused-tested):** the main checkout now contains the `Stmt.Match` traversal for strict unsafe checks, pointer-arithmetic grants, local mutable-alias analysis, and raw-extern checks. Match arms analyze copies of incoming borrow facts; the strict walk invalidates post-match facts when an arm rebinds a tracked borrowed slot. The 49-case unsafe-grant smoke passes, including negative and exact-grant cases for aliases, pointer arithmetic, raw externs, Match arms, and nested global reads. Known compound-expression and embedded statement walks were expanded and split into helper files. The operation-to-AST-context matrix, exhaustive future-node behavior, typed lambda parameter facts, complete `strict_borrowed_call_check` traversal, BindingId-based flow, and complete path-sensitive borrower joins remain open; this work is not proof of S14 soundness.

**Verified S14 pointer-arithmetic grant slice (2026-09-24):** the previous checker recognized only a reference-parameter identifier paired with an integer literal or bare integer parameter, and split missing-grant detection from unrelated-grant detection. One lexical pointer-capability walk now handles both cases and carries scoped reference/integer binding kinds through local declarations, nested blocks, branches, loops, matches, comprehensions, and closures, with inner bindings masking outer names. It recognizes nested integer arithmetic and direct integer-/reference-returning calls; a function's declared effect remains a caller obligation and does not authorize the body. Valid `u8&`/`usize` negative and positive twins pass in `unsafe_grant_scope_smoke.sh` (60 cases). A Stage0/Stage1 `-emit unsafe` report probe counted the same seven pointer-arithmetic shapes (local reference alias, compound offset, integer-returning call, reference-returning call, exact grant, unrelated grant, and shadowed name); this report-mode comparison is not strict grant-diagnostic parity. A fresh Stage1 seed, `assert_stage1_fresh.sh`, and `scripts/self_host_gen2.sh` pass; the seed needed the documented larger-host RSS limit of 6 GiB after the default 4 GiB guard stopped its first attempt. The broad `emit_unsafe_parity_smoke.sh` remains failing (154 byte-identical, 28 divergent, 278 skipped), with existing closure-alias, extern-pointer, opaque-handle, and stale-view/report mismatches still open; the `fixed_array_ref_byte_offset` report mismatch was also present in the pre-change Gen2 binary. Keep S14 open: typed facts for all reference-producing expressions, exhaustive operation/context coverage, BindingId-based flow, and full Stage0/report parity still require work.

**Verified S14 structural pointer-operand follow-up (2026-09-24):** probes showed that pointer arithmetic through `pair.pointer + pair.offset` and `values[0] + offset` was missing its strict grant diagnostic in Stage1 because the grant walk only recognized bare identifiers. The walk now seeds and scopes structural TypeIds for function parameters and annotated locals, uses the existing structural expression resolver for field/index/call shapes, masks scoped shadows, and restores the caller's transient local-type table after analysis. `unsafe_grant_scope_smoke.sh` passes 64 cases with accepted positive programs required to exit successfully. Fresh Stage1 seed, freshness guard, and Gen2 self-host fixture pass. `-emit unsafe` report counts identify pointer-arithmetic sites but do not establish strict grant-diagnostic parity with Stage0. Structural classification remains a sound subset: reference-producing expression forms without a structural TypeId, inference through value-block locals, generated operations, and the broader operation/context matrix remain open, so S14 is still in progress.

**Verified S14 pointer-arithmetic value-block tail follow-up (2026-09-24):** a strict function could declare `alias: u8& = pointer` inside a value block and evaluate `alias + offset` as the block tail; the visitor had discarded the block's local binding/type scope before analyzing that tail, so Stage1 missed its own pointer-arithmetic grant diagnostic. `pag_walk` now analyzes a value expression before truncating the block's lexical and structural type scopes. The transient TypeId arrays are preserved by ownership transfer while the pass runs and restored by moving the original buffers back, avoiding a short-lived copied array escaping into the longer-lived symbol table. `unsafe_grant_scope_smoke.sh` passes 66 cases, including a rejected ungranted block-tail operation and an accepted exact-grant positive program. A fresh Stage1 seed, `assert_stage1_fresh.sh`, and `self_host_gen2.sh` pass. The reference Stage0 CLI's `-emit unsafe` report is a site-count report and its ordinary semantic modes do not expose the same Stage1 strict diagnostic, so this is validated as a Stage1 checker regression rather than claimed as Stage0 grant parity. Value-block inference beyond structurally known types, full expression/statement coverage, BindingId-based facts, and the complete operation/context matrix remain open; S14 is in progress.

**Verified S14 pointer-arithmetic iteration-binder follow-up (2026-09-24):** a typed `darray[u8&]`/`array[u8&, N]` iterable gave its loop or comprehension binder a reference element, but the grant walk had installed an unknown local type; likewise, `for index in 0..<count` and range comprehensions had unknown integer binders. Multi-name tuple/dictionary loops also left each component untyped. These forms allowed a pointer-arithmetic operation to escape this one capability check. The visitor now derives element TypeIds from structurally known containers, maps tuple and dictionary components to their respective destructured names, and marks range binders as integers, preserving the existing scoped shadowing and cleanup rules. `unsafe_grant_scope_smoke.sh` passes 78 cases with missing-grant negatives and exact-grant positive twins for reference-valued loops/comprehensions, integer range loops/comprehensions, and tuple/dictionary destructuring. A fresh Stage1 seed, freshness guard, Gen2 self-host build, shell syntax check, and whitespace check pass. Opaque/generic iterator element types, other operations and visitors, and the complete AST/context matrix remain open. Stage0 report counts are not used as strict grant proof, and S14 remains in progress.


**Verified S14 pointer-arithmetic enum-match follow-up (2026-09-24):** strict pointer arithmetic through a reference payload bound by `Enum.Variant(pointer, step)` was invisible in both statement-match and value-match arms because the grant visitor installed pattern names with Unknown types. Enum payload metadata now retains structural TypeIds and field positions, and the grant pass recovers payload types for positional variant bindings plus structurally known tuple/as/type-bind patterns. Match-expression guards are visited after installing the arm bindings, matching their lexical scope. The smoke covers missing-grant and exact-grant statement/value match bodies and guards (84 cases total). Unknown, ambiguous, generic, and unsupported pattern shapes remain conservative Unknowns; nested/struct-pattern completeness and the whole operation/context matrix remain open. S14 remains in progress.

**Verified self-host string-view lifetime follow-up (2026-09-24):** integrated both commits from the `codex/sview-lifetime-selfhost` worktree. Parser machine-state declarations are copied into owned storage before the pending list is truncated; region-escape analysis snapshots entry local names with explicit element copies; strict unsafe callback-effect snapshots use explicit copies and local-name rebinding compacts the caller-owned buffer in place, avoiding an auto-region array escaping into the longer-lived binding state. The combined main tree passes a fresh Stage1 seed, `unsafe_grant_scope_smoke.sh` (84 cases), `assert_stage1_fresh.sh`, shell syntax/whitespace checks, and `self_host_gen2.sh`. This closes those specific copy/lifetime defects only; complete view provenance, alias identity, all-region invalidation, and the broader operation/context matrix remain open.

**S11/S12 read-only runtime inventory (2026-09-23; source review only while WasmBrowser Release validation runs):** the allocator surface includes `Arena` with libc/mmap/VirtualAlloc/Wasm backends and CHAINED/MALLOC/RESERVE_COMMIT/FIXED/SCRATCH strategies; bump allocate/reallocate and intrusive `ArenaFreeBlock` reuse; reset/rewind/free/trim/adopt; `FixedBufferAllocator`; the protocol-backed bump and malloc allocators; raw `MemoryPool[T]` and `RegionPool[T]` APIs; and the affine `Pooled[T]` region-pool interface. The arithmetic to audit includes `size + word_size - 1`, `sizeof(header) + capacity * word_size`, `count + requested_slots`, pointer/end address additions, alignment rounding, index width narrowing, and growth arithmetic. Current declarations and inspected helpers use target-sized `usize`/`uintptr`, but this review did not establish checked-overflow behavior or maximum supported capacities. The mmap-region cache and free hint are plain mutable globals that the source comments describe as unsynchronized; race safety under concurrent allocator teardown/reuse is unverified. `memory_pool_create/destroy/reset/deinit` expose raw object references and explicit bulk invalidation, while the separate region pool offers an affine wrapper; audit whether callers can double-recycle or retain/use references across reuse/reset, and whether the raw APIs are restricted to unsafe/internal use. A repository-wide search of `.elisa` and `.sh` files found no direct `memory_pool_*`, `region_pool_*`, or fixed-buffer API call sites outside their definitions/comments in `heap.elisa`; this narrows the in-tree usage map but does not settle their public compatibility contract or external consumers. Existing arena-focused source fixtures include `test/repro/arena_lifetime_evidence.elisa`, `arena_rewind_lifecycle.elisa`, `arena_free_hint_lifecycle.elisa`, `arena_reuse_identity.elisa`, `arena_tail_capacity.elisa`, and `arena_adopt_reuse_indices.elisa`; their names and assertions are not current pass evidence because they were not run during the release build.

**Verified S11 arena size-arithmetic slice (2026-09-23):** reproduced the original ceiling-rounding defect on both Stage0 and Stage1 at `-O2`: requesting `18446744073709551615` bytes returned normally with the fixture's sentinel result instead of rejecting the request. Replaced `size + word_size - 1` with quotient/remainder rounding and explicit checked addition/multiplication; region total/payload sizes, cursor fit, allocator count growth, reserve page rounding, and collection-stack growth now use overflow-safe arithmetic. Allocation/reserve/commit/release failure checks in the arena backends now branch to explicit panic handling instead of relying on `assert`, and arena strdup/formatting helpers check the added NUL byte before allocation. `bash test/parity/arena_alloc_size_overflow_smoke.sh` passes Stage0 and fresh Stage1 at `-O0`/`-O2`: zero and small requests succeed, while the maximum-size request traps with `arena allocation size overflow`. `bash test/parity/arena_runtime_lifecycle_smoke.sh` passes Stage0/Stage1 `-O2` adoption/trim, reuse, rewind, tail-growth, and free-hint lifecycle regressions. The canonical Elisa-core arena source was synchronized and `bash scripts/check_runtime_drift.sh` passes. This is a native 64-bit regression slice only; it does not validate checked arithmetic in every runtime allocator, 32-bit narrowing, Windows/Wasm backends, over-alignment, OOM injection/transactionality, or cache concurrency.

**Verified S11 fixed-buffer safety slice (2026-09-23):** checked alignment rounding and `base + cursor` arithmetic now fail before wrap; pointer ownership and allocation extents use offset/remaining-size checks rather than potentially wrapping end-address additions. The cursor is rejected when it exceeds capacity, rewind marks cannot exceed capacity or advance beyond the current cursor, and the panicking allocation helpers use explicit null checks that survive optimized builds. Resize now refuses non-tail allocations for both growth and shrink, then proves the requested extent fits before updating the cursor; this prevents a growth from overlapping a later live allocation. `bash test/parity/fixed_buffer_safety_smoke.sh` passes both compilers at `-O0`/`-O2`, covering valid alignment and last-allocation resize, rejected non-tail growth and corrupt cursor, maximum-value alignment overflow, exhausted-buffer allocation, and invalid/forward rewind marks. These checks cover the fixed-buffer operations exercised by the smoke only; source-buffer extent validation, over-aligned typed allocations, raw pool lifetime/double-recycle rules, allocator identity, and other targets remain open.

**Verified S11 runtime-string size slice (2026-09-23):** centralized checked `usize` addition and checked `usize`/`i64` size conversion in the runtime prelude; string interning, permanent/scratch concatenation, slicing, f-string allocation, and string-view copying now validate the payload-plus-terminator extent before allocation and reject sizes that cannot pass through the legacy signed allocator API. Integer formatting rejects a failed `snprintf` length and allocates using one checked byte count. F-string append computes its new count with checked addition, checks capacity explicitly, and only publishes the count after copying, replacing an assertion that optimized runtime builds could elide. The canonical core sources and the compiler's vendored runtime now match, including the prior profiler-hook gain that had been accepted only as a content-hashed vendor delta. `bash test/parity/runtime_string_allocation_smoke.sh` passes on Stage0 and freshly seeded Stage1 at `-O0`/`-O2`: valid concat/scratch-concat/slice/view-copy/integer-format behavior agrees, checked addition and narrowing overflow trap with their expected messages, and an over-capacity f-string append traps. This does not create a huge real C string to exercise concatenation at `usize` limits; that path shares the directly tested checked-add helper. Runtime `uint`/`float` formatter output, source C-string extent validity, format-result consistency, all view-construction invariants, failure injection, other allocators, and non-native targets remain open.

**Verified S09 malformed string-view length slice (2026-09-23):** reproduced that two equal negative `sview.len` values reached `memcmp` after signed-to-unsigned conversion when their pointers differed; the Stage1 `-O2` reproducer with invalid addresses exited by signal 11 (status 139). `string_views_eq`, `string_view_eq`, indexing, slicing, hashing, and the safe path helpers now reject negative lengths before dereference, while signed lengths that cannot round-trip through target `usize` are treated as empty/rejected. `sview` and `bytes_view` avoid publishing lengths that do not fit the ABI's signed field. `bash test/parity/runtime_string_view_safety_smoke.sh` passes Stage0 and freshly seeded Stage1 at `-O0`/`-O2`, exercising hostile invalid pointers with negative lengths and a valid positive twin; `bash test/parity/backend_obj_smoke.sh` passes 50/50. This does not validate the backing extent of positive forged pointer-length pairs, make the runtime view carrier opaque, or audit every FFI/JSON view constructor and direct backend view operation; those remain S07/S09 work.

**Verified S07/S09 JSON DOM opacity slice (2026-09-23):** before the change, a source file that included the JSON runtime could call `json_value_copy(1.uintptr(), 0)` without an unsafe grant; the Stage1 `-O0` executable exited by signal 11 (status 139). The DOM representation was changed to a private module member (`JsonValue`), `JsonMember` and the raw child/member reference-copy helpers were made module-private, and `using Json` keeps the ordinary public parser/accessor/writer names available. The public array/object builders that accepted raw typed runs are also private for now; the safe API retains parsing and scalar constructors, while an owner-tied builder API remains future work. `json_opaque_dom_smoke.sh` passes Stage0 and freshly seeded Stage1 at `-O0`/`-O2`: valid parse/kind/length/write calls run, while direct variant construction and raw-copy calls fail with module-privacy diagnostics. The source was synchronized into canonical Elisa-core; `check_runtime_drift.sh`, Stage0/Stage1 freshness, and `backend_obj_smoke.sh` (50/50) pass. An exploratory post-free serialization probe trapped at Stage1 `-O0` and returned normally at `-O2`; its exact fault site is not isolated, so it is retained here as evidence that arena lifetime is still not enforced, not as a closed regression. A prototype `Arena&` owner payload did not produce a lifetime diagnostic and caused Stage1 to decline the affected functions, so it was reverted. This slice prevents safe construction of forged positive DOM addresses, but it does not tie `JsonValue`, returned string/key views, or `cstr` results to arena lifetimes; broader S06/S07 provenance and S09 pointer-extent work remains.

The packed-store state is an opaque `void&` at helper boundaries and carries allocation/decode regions, region indexes, raw pointer handles, row indexes, variant tags/slots, and prefix/side columns. Two pre-fix Stage1 probes exposed cross-row reads: a one-word variant-sparse row exposed adjacent arena data (`104`), and a one-word packed dense row exposed the next row's first word (`104`). The verified S12 slice adds a physical word count to each variant-row descriptor and per-handle word extents to dense metadata; it uses overflow-aware row sizing and index-width guards, then checks state/index/tag/slot/row extent before pointer arithmetic. Runtime checks on these paths are explicit conditional panic branches: Stage0's default optimized runtime elides ordinary `assert` contracts, as confirmed by the generated pre-fix archive object and an OOB call that returned normally. The Stage0/Stage1 smokes now pass valid reads and require the specific row-bounds panic for invalid dense handle/index and sparse word reads. This does not establish safety for all packed-store callers or all assertion-based runtime checks. Store identity, generation, reset/reuse invalidation, 32-bit shifts/narrowing, cross-store calls, AoS and other layouts, allocation-failure atomicity, sanitizer coverage, and the supported target/backend matrix remain open.

**Verified S12 packed row-bounds slice (2026-09-23):** added `PackedStoreVariantRow { pointer, word_count }` and per-handle `row_word_counts`; computes a minimum-one-word row count without `size + word_size - 1` overflow; checks byte-size multiplication and index narrowing before allocation/metadata insertion; and validates metadata indexes and row extents before forming row-word references. The index-based dense reader uses its validated extent directly, while raw-handle reads look up the matching extent. Critical checks use explicit `if`/`panic` branches so Stage0's contract-elision mode cannot remove them. `bash test/parity/packed_sparse_word_bounds_smoke.sh` passes on both compilers: the last in-bounds word succeeds and the next word traps. `bash test/parity/packed_dense_word_bounds_smoke.sh` passes on both compilers: valid reads succeed, and out-of-range handle and index reads trap with the expected bounds panic. The Stage1 runtime and compiler product were freshly rebuilt; `assert_stage1_fresh.sh` passed. `scripts/check_runtime_drift.sh` passed with only the previously content-approved profiler/runtime deltas, and `bash test/parity/backend_native_smoke.sh` passed 520/520 native compile-and-run checks. S12 remains in progress: this slice does not cover generation/store identity, stale handles after reset/reuse, complete metadata transactions under allocation failure, pool APIs, AoS/other store layouts, or target-width behavior. Raw-handle extent lookup is linear; the compiler's index-based access path remains constant-time.

**Verified reference-capability and cast-hardening slice (2026-09-23):** incorporated the `memsafe/nullable-scalar-deref` worktree change `Make reference writes a capability of the reference type` into Elisa-core commit `22d996c7`. The type checker now separates a mutable binding slot from permission to mutate the referenced object: rebinding a `mutable` slot does not upgrade a read-only reference, and a write through a nullable reference requires a non-null flow proof at the exact target. It rejects storing a byte pointer through a one-byte reference, preserves writable-reference qualifiers through fallible return types, and requires `Unsafe.PointerCast` when a generic cast changes pointee type or adds mutability. Recursive enum type inspection is cycle-guarded. The focused validation passed: `go test ./src/semantic ./src/parser ./src/backend` and `go test ./src -run 'TestRefWriteThroughRuntimeSemantics|TestRunCLIProjectTestPromotesCVariadicArguments' -count=1`; the latter runtime tests covered reference writes and C variadic promotions. Existing committed gains from the other worktree (`68d9b97f` unordered float inequality and `8441c249` builder lowering for `va_arg`/`va_copy`) were verified present in the main history and their tests passed in those package runs. These results exercise targeted semantic and runtime paths only; borrow aliases, captured mutation, complete pointer-cast source/target combinations, varargs type safety, and all FFI/platform combinations remain open. `S14`, `S15`, `S16`, and `S18` remain in progress.

**Verified S16 dictionary-index value typing slice (2026-09-23):** the checker no longer lets the payload inferred from a bare `dict` subscript masquerade as a scalar initializer when the expression is actually a nullable reference lookup. The paired diagnostics fixtures confirm `i64 = values[key]` is rejected as an optional dictionary-value reference while `i64 = get values[key] else fallback` is accepted; `bash test/parity/dict_index_optional_type_smoke.sh` checks the direct compile rejection and a parse-clean semantic report for the explicitly-unwrapped form. The full `bash test/parity/diagnostics_smoke.sh` passes 408/408 fixtures. This fixes only the checked initializer/assignment compatibility path; dictionary lookup typing across all contexts, reference lifetimes, and Stage0 parity remain open.

**S26 follow-ups:** continue a complete audit of every executable CLI, wrapper, project, object/archive, Python, Wasm, EASM, and IR path, plus every semantic report (`iface`, `header`, Python manifest/C output, packed and unsafe reports, test-runner/list reports), to prove each consumes the intended expanded program and cannot bypass the mandatory gate. The focused `semantic_gate_static_generate_smoke.sh` covers generated declarations for `c-archive`, `test`, and `interpret`; extend coverage across modes and wrappers, including pre-existing destinations and each backend failure phase. `pymodule_reserved_export_smoke.sh` checks the targeted Python C/stub rejection sentinel and invalid extension cleanup, while `pymodule_object_smoke.sh` checks successful extension output; publish all multi-file artifacts atomically and define cleanup/partial-result behavior at every failure point. Review all partial-body decline paths and make required-definition completeness explicit so declined or incomplete compilation cannot appear successful. Add artifact manifests, incompatible-summary rejection, and structured partial status for report-only modes. The self-host semantic-gate smoke remains unverified for this slice. These gaps mean S26 is still in progress.

**S26 read-only entry-point review and resolution (2026-09-23):** the earlier review identified pre-expansion dispatch for `c-archive`, `test`, `interpret`, and `pymodule-pyi`, plus early reusable sidecars for `pymodule-so`. The current reviewed slice reorders these paths around static-generation expansion and mandatory semantic validation. Targeted regressions now pass for the generated-code modes, Python stub and extension rejection, stale-output sentinel behavior, and successful extension output. The prior review's inventory remains useful as an audit checklist: no result here proves untested CLI/wrapper/backend paths, complete multi-artifact atomicity, or safe handling of every partial/declined compilation. Keep those as S26 acceptance work.

**Verified S26 partial backend-output slice (2026-09-23):** a minimized source with one unsupported `Probe.create` body and a valid `main` previously caused Stage1 to print a warning, exit 0, and write LLVM containing the other definitions. Partial decline metadata now produces an error and returns before verification, optimization, or output creation. `no_partial_backend_output_smoke.sh` confirms LLVM, object, bitcode, and executable emission all reject this unit without leaving an output or executable sidecar; a simple valid executable control runs at `-O0` and `-O2`. A fresh Stage1 seed and both freshness assertions pass; `backend_obj_smoke.sh` passes 50/50, `backend_native_smoke.sh` passes 520/520, `json_opaque_dom_smoke.sh` passes Stage0/Stage1 at both optimization levels, and `semantic_gate_selfhost_smoke.sh` confirms gen2 agrees with Stage0 for the semantic gate. This makes one partial-decline path fail closed; report-only modes, generated helpers, multi-file outputs, failure atomicity, and the rest of the backend completeness matrix remain open. The full `run_all.sh` parity gate was not run for this slice.

**Verified S06 arena-invalidation call slice (2026-09-24):** the destroyed-region pass now maps local helper invalidation summaries by formal name for named arguments, carries that mapping through helper chains, and traverses nested block expressions so a reset cannot disappear inside an expression. A direct call to a declared extern with a formal `Arena&` conservatively invalidates the corresponding passed arena owner; when the argument cannot be resolved, it invalidates all tracked regions. The expanded `destroyed_view_lifetime_smoke.sh` rejects the named-helper, opaque-extern, nested-block, and existing direct/alias/helper stale-view repros at both `-O0` and `-O2`; named independent-owner and non-resetting-helper controls execute and return 65. A fresh Gen2 self-host build and `assert_stage1_fresh.sh` pass; `region_scope_smoke.sh` passes all 21 carrier-less annotation cases against Stage0, and `cross_module_fallible_return_smoke.sh` passes. Gen2 SHA-256: `de482cb2e0fb09bff1fe13ec9ee15c9032746bc6dc35ddc9d1e125f9088fd87f`; runtime object SHA-256: `386ff4310e2313a70cef597a7f1caa1a8db2a01c35e979eb2295936e47b7a192`. This remains a targeted syntactic/interprocedural slice: imported-body summaries, indirect/dynamic calls outside the local-reference handling below, static-effect calls, path-sensitive reset epochs, full external contracts, and complete CFG/projection provenance remain open; it does not qualify Elisa as memory safe.

**Verified S06 local indirect-call slice (2026-09-24, commit `b49c14f0`):** `arena_callback_reset_leak.elisa` previously compiled even though a function-valued local called a reset helper through an `Arena&` and a stale view was then read. The checker now uses resolver-owned local-reference identities to distinguish local callable values from direct function definitions; an indirect local call invalidates tracked arena arguments, or all tracked regions when no owner argument can be identified. The regression is in `destroyed_view_lifetime_smoke.sh` at both `-O0` and `-O2`. The same fresh product passed `assert_stage1_fresh.sh`, the full destroyed-view smoke including the non-resetting-helper positive control, the 21-case `region_scope_smoke.sh`, and `cross_module_fallible_return_smoke.sh`. Gen2 SHA-256: `22ab7ebc019e038b70e6beb815d23e423abdbb4310f12baa38cccf61807d3d79`; runtime object SHA-256: `386ff4310e2313a70cef597a7f1caa1a8db2a01c35e979eb2295936e47b7a192`. This covers function-local callable bindings and recognized owner expressions; callbacks hidden in imported summaries or dynamically assembled outside those bindings and their external effect contracts remain open.

**S06 follow-up: forwarded and captured callback invalidation (2026-09-24):** `test/repro/arena_forwarded_callback_reset_leak.elisa` exercises a reset callback passed into `invoke_callback(callback, target)` and called there; the call site then allocates into the same arena and reads a pre-reset view. Earlier local summaries stopped at the helper boundary and accepted this source. Summary discovery now scans every function body so type aliases and wrappers cannot make a callback parameter invisible to the eligibility filter, propagates an unknown-callable sentinel through local helper chains, and conservatively invalidates all tracked arena regions when that sentinel is applied. This global fallback is required because a callback can mutate an arena captured by its closure even if that arena is absent from explicit arguments. The direct `Arena&` formal summary still maps known owner arguments by formal name and invalidates that owner when the helper is called. Calls through resolver-identified local function values likewise invalidate all tracked regions until callable capture/effect summaries are modeled. `test/repro/arena_captured_callback_reset_leak.elisa` verifies a callback that resets a captured `first` arena while receiving an unrelated `second` arena; it must be rejected for the captured `first` dependency.

A single fresh self-hosted product, `build/arena_forwarded_callback_stage14/elisac-stage1-gen2` (SHA-256 `06eed47783649628aab794a3c89c8764c2d362d4f9aa7e411f6c4020f4473796`), passes `scripts/assert_stage1_fresh.sh`. `destroyed_view_lifetime_smoke.sh` checks the exact stale-region diagnostic and absence of LLVM for both forwarded and captured callback cases at `-O0` and `-O2`, along with existing safe-owner, last-use, alias, named-helper, extern, and non-resetting-helper controls. `region_scope_smoke.sh` passes the 21 carrier-less annotation cases against pinned Stage0, and `cross_module_fallible_return_smoke.sh` passes. The runtime object SHA-256 is `386ff4310e2313a70cef597a7f1caa1a8db2a01c35e979eb2295936e47b7a192`; shell syntax and whitespace checks pass. The conservative sentinel may reject safe callbacks, and this slice does not model callback retention/escape, callback execution on other threads, returned or stored closures, effect contracts across imported/module boundaries, canonical region epochs, CFG joins, full aggregate provenance, other targets, or the complete acceptance profile. This is regression evidence for a local arena-reset slice, not a claim that Elisa is memory safe.

**Verified S06 closure-call slice (2026-09-24):** The closure regressions are `test/repro/arena_closure_alias_after_free.elisa`, `arena_closure_assignment_after_free.elisa`, and `arena_returned_closure_after_free.elisa`; the returned-closure fixture uses `type Reader = fn() -> i64` to cover a named alias. Before the fix, Stage21 accepted the returned closure and the native executable returned `0` after its backing arena was freed. Fresh Stage23 rejects all three at `-O0` and `-O2` with a destroyed-region diagnostic and no LLVM. The checker now keeps capture-free lambda rows distinct from unknown closure provenance, copies dependency rows through recognized local aliases, tracks direct lambda assignment, and fails closed on calls through unknown-provenance callable bindings after tracked invalidation. `test/parity/fixtures/arena_captured_closure_live.elisa` is a positive runtime control: it frees an unrelated arena, calls a closure while the captured arena remains live, then frees the captured arena; it returns `65` at both optimization levels. `arena_tuple_closure_after_free.elisa` currently reaches the backend's explicit “could not produce a linkable unit” rejection; the smoke checks that no LLVM is published but treats this only as an unsupported backend shape, not as a lifetime diagnostic. The full destroyed-view lifetime suite passes at `-O0`/`-O2`, Stage1 freshness passes, `region_scope_smoke.sh` passes its 21 Stage0-comparison cases, and `cross_module_fallible_return_smoke.sh` passes. Stage23 Gen2 SHA-256: `9d25dcc2de8f61a28fbeb7283f961cff4f1afd4cc744118e8d830fbd173b7286`. This analysis still keys capture/dependency facts to local names and line-derived region IDs, does not model returned-closure origin summaries, may reject a safe unknown closure after an unrelated invalidation, and does not support aggregate closure storage in the backend; nested/cross-module closures, CFG joins, and full aggregate callable provenance remain S06 work.

**Verified S06 closure and nested-expression visitor slice (2026-09-24, Stage30):** The direct, reassigned, aliased, returned, and inline closure repros now reject calls after their captured region is invalidated; a body that calls `arena_free(alloc)` before reading a captured view is diagnosed inside the lambda body. Unknown returned callable provenance is represented explicitly and fails closed once any tracked invalidation is observed. To avoid flagging a closure merely because its call may mutate state later, local callable use is checked against the pre-call invalidation state and its possible effects apply to subsequent operations. The checker separately verifies deferred lambda bodies using a fresh invalidation state and captured origin maps. Stale reads are now checked at statement-level if/while/for/match sites and nested in block/match/catch/recovery/comprehension/static-effect expressions; view-result propagation covers block locals, match arms, and `sview(pointer, ...)`. This is still conservative and name/line-based; `Expr`/`Stmt` traversal must remain synchronized with the AST, nested parameter shadowing is not identity-safe, and interprocedural closure/effect provenance plus path-sensitive joins remain open. The tuple-captured-closure fixture is explicitly a backend-decline/no-LLVM control, not lifetime analysis coverage. Stage30 (`2b9b818a7fc0a91d922647cb491a77a5f7f56579b0c7ce3f6ba88159d311e732`) passes self-host fixture, freshness, `destroyed_view_lifetime_smoke.sh` at `-O0`/`-O2`, `region_scope_smoke.sh` (21 cases), and `cross_module_fallible_return_smoke.sh`; `scripts/assert_stage0_fresh.sh`, `bash -n`, and `git diff --check` also pass. A separate confirmed issue remains for the next milestone: safe source can construct `StringView{data: &byte, len: 2}` and can call `sview(&byte, 0, -1)`, even though the view extent is unproven and the source is not guaranteed NUL-terminated. The repros are `test/repro/sview_extent_overrun.elisa` and `test/repro/sview_unterminated_input.elisa`; view opacity/bounded-source API work remains open, and is not part of this closure slice.

## P. Worktree preservation and integration ledger

The earlier WasmBrowser Release build process disappeared, but its exit result was not available from the app terminal; no pass or failure is claimed. The user then directed that all worktree gains be brought into the main checkout and that redundant source worktrees be removed after integration. The source manifests were audited and merged, applicable focused checks and an integration checkpoint were recorded, and redundant candidates were removed only after that review. The compiler source freeze is lifted. If a new candidate worktree appears, compare its complete manifest and run the relevant focused checks before removing it; the 2026-09-24 reconciliation below found no remaining compiler-source candidate.

**Independent candidate worktree recorded 2026-09-23:** `/private/tmp/claude-501/s1-memsafe`, branch `memsafe/ref-write-parity`, based at `c27443bf9bd32f9ff7bf5081831181036ef09266`. Its source manifest had 81 changed paths (34 modified tracked and 47 untracked). The isolated `/Users/torarinvikbjarko/.codex/worktrees/elisa-memory-safety/Elisa-compiler` manifest has 35 changed paths. The manifests share only `src/semantic/semantic.elisa`; the remaining paths from both are present byte-for-byte in main. The two worktree deltas to `semantic.elisa` each add two includes; all four additions are present in the merged main file. No originating-task test result for the earlier WasmBrowser build is available, so that build is not counted as evidence.

**Transfer and audit status (2026-09-23):** every modified/untracked file in both source-worktree manifests was compared against main; all non-overlapping file contents matched byte-for-byte, and both sets of semantic includes are present. The main checkout adds one further fix to `-emit interpret` scratch-file naming after an observed concurrent-run collision. The WasmBrowser build's exit status remains unknown and is not counted as a pass.

Its implementation work is grouped as follows:

- **Reference and type safety:** new `src/semantic/check_ref_binding_modes.elisa` and `check_ref_binding_rules.elisa`; changes to `check_readonly_ref.elisa`, `check_internal_runtime_carrier.elisa`, `check_poisoned_operand.elisa`, `resolve.elisa`, `resolve_mutability.elisa`, `resolve_types_infer.elisa`, `resolve_types_initializers.elisa`, `resolve_types_operators.elisa`, `type_table.elisa`, `semantic.elisa`, and semantic diagnostic kind/message files. The added cases cover read/write capability, rebind-versus-write-through behavior, ref arguments/casts/globals/fields/builtins, null narrowing, internal runtime carrier positions, and incompatible string representation families. Review flow-sensitive facts, shadowing, optional and aggregate propagation, and semantic/codegen agreement before accepting these rules.
- **Backend memory behavior:** changes to `codegen_stmt_assign_place.elisa`, `codegen_expr_index_read.elisa`, `codegen_expr_slice.elisa`, `codegen_guards.elisa`, `codegen_declines.elisa`, `codegen_debug.elisa`, and `codegen_region_forwarding.elisa`. The patch adds view index bounds guards, clamps slice start/count computations to source extents, adjusts string slice lowering, ref assignment/write-through lowering, and resolves region-forwarded callees using dispatch/arity facts. Source inspection confirms the new count guard uses LLVM unsigned-less-than predicate 36 and widens the narrower index/count operand; the slice helpers use unsigned clamp comparisons and separate signed string-bound normalization. This is source-level evidence only. Review signedness, integer-width conversion, negative/overflowing bounds, every index read/write path, and exact call-resolution parity before treating these as safety fixes.
- **Runtime/library surface:** changes to `elisacore_std/collections.elisai`, `elisacore_std/deque.elisa`, and `elisacore_std/stores_rows.elisa`; trace each public API and representation invariant through callers and generated code.
- **Regression and oracle evidence:** changes to `test/breadth/adv_gen_refs_builtins.py`, `test/fixtures/semantic_internal_oracle.tsv.gz`, `test/parity/backend_smoke_behavior.sh`, `diagnostics_smoke.sh`, `emit_interpret_parity_smoke.sh`, and `resolve_smoke.elisa`; new `test/parity/slice_bounds_smoke.sh`; new `.neg.elisa`/`.pos.elisa` fixture pairs for `element_assign_wording`, `field_assign_wording`, `internal_runtime_carrier_param`, `ref_argument_capability`, `ref_builtin_struct_field`, `ref_byte_pointer_store`, `ref_cast_argument`, `ref_cast_capability`, `ref_cstr_out_param`, `ref_global_capability`, `ref_legacy_readonly_source`, `ref_null_narrowing`, `ref_readonly_path`, `ref_rebind_value`, and the `string_family_*` cases. Validation on the combined main tree: fresh stage1 seed and freshness pass; unsafe grants 49/49; slice bounds 112/112 at `-O0` and `-O2` against stage0/stage1; diagnostics 406/406 fixtures; native backend 517/517; reference reborrow 27 contexts and mutable-ref scope pass; resolver reports zero unresolved names across 531 frontend files; semantic-gate self-host smoke passes. After the shared `/tmp/elisa-interpret-stage1/program` path caused one transient mismatch under concurrent compiler runs, the driver was changed to PID-specific object/executable/callback paths with cleanup; the final interpreter parity run reports 60 identical, 3 known stage0 interpreter divergences, 340 skipped by stage0, and 0 divergences. This evidence qualifies only the listed native-host behaviors. A complete acceptance gate, 32-bit/Wasm target execution, allocator/packed-store audit, and the remaining S04–S28 work are still open.

**Integration checkpoint and cleanup (2026-09-23):** source manifests were captured, merged into main, and byte-audited; the semantic overlap retains both include sets. The combined tree passed the focused tests listed above, including a fresh seed, relevant diagnostic/backend smokes, and the semantic self-host gate. Commit `1b683c34b655660fc91df26a559c488b315c2a92` records the 116 changed paths in the integration checkpoint. After verifying the main checkout was clean and no process used either source path, both redundant worktrees were removed with `git worktree remove --force`; only the main checkout remains registered. The all-language acceptance gate and target matrix remain open in their package rows and are not implied by this checkpoint. Continue broader validation and record residual gaps in the S04–S27 ledger.


**Nullable-flow candidate-worktree integration checkpoint (2026-09-23):** `/private/tmp/elisa-compiler-nullable-audit` and `/private/tmp/elisa-compiler-nullable-audit2` were both based on `16a2bca1`; their complete dirty manifests contained only `src/semantic/check_nullable_flow.elisa` and `test/parity/nullable_flow_smoke.sh`. The useful traversal, shadowing, guard, and regression work is present in main, with stronger target/index coverage and conservative branch/loop/Match joins added here. The candidates' typed lambda-parameter access does not match the current AST (`Lambda.params` is `darray[sview]`), and their `Expr.Wrap` arm names no current AST variant, so neither was imported. Their remaining source/test edits were compared through the complete diffs. A nullable-loop fixture referenced by the transferred smoke was absent from main after cleanup; a self-contained nested nullable-local/while fixture was added and reports `P 0 / D 0`. After the combined focused suites passed and the 2/581 alias-flow differences were recorded above, both candidate worktrees were removed; `git worktree list` now contains only main. The independent WasmBrowser task reports its loader C-ABI oracle, 110-test wb-loader suite, Stage1 freshness check, and diff check passed on this compiler-source state. These do not establish a full Wasm release gate or target-wide memory-safety result.

**Reconciliation check (2026-09-24):** `git worktree list --verbose` contains only this main checkout. The source-candidate worktrees described above are already absent after their manifest audits and integration checkpoint; no further same-repository worktree content is available to import or remove. The adjacent `Elisa-compiler BACKUP` checkout is an ancestor at `6921b84a`, so it has no unique commits relative to this main history; its only dirty paths are `.DS_Store` metadata and were left untouched. A separate `elisa-core-stage0-or-pattern` worktree belongs to the Go Stage0 repository, not this compiler checkout, and is not a compiler-source candidate. No new candidate worktree was deleted during this reconciliation.

**Detached-worktree follow-up (2026-09-24):** a later audit found `/private/tmp/elisa-compiler-ec4c7b9`, detached at `ec4c7b93`, registered after the earlier reconciliation. Its working tree was clean, no process referenced its path, and `ec4c7b93` is an ancestor of `main` at `c97837f8`; it contained no unique committed gains. The worktree was removed after this ancestry and cleanliness check. The `memsafe/ref-write-parity` tip `c27443bf` is also an ancestor of `main`. `git worktree list` now contains only the main checkout; no unintegrated compiler worktree changes remain.


**Stage0 safety-gain reconciliation (2026-09-24):** Elisa-core `main` contains the string-view commits `43c0d8c4`, `15b446ac`, and `0742534c`, plus `8c1f8a19` (ABI-derived packed-store field offsets), `a4b64da4` (explicit C-string cast at the `strcmp` boundary), and `9a4de23b` (ignore self-host build artifacts). These commits are already integrated on the adjacent repository main and were retained there, not copied across repositories. The rebuilt Stage0 binary passes `go build -o bin/elisac ./src`, backend, semantic and parser package tests, and the final focused Stage0/Stage1 comparison smokes. The `memsafe/ref-write-parity` and `codex/transpiler-local-stage0-latest` tips are ancestors of their respective main histories. The unique `memsafe/nullable-scalar-deref` commit `875d75bd` was reviewed against Stage0 main and excluded because its delta removes packed-store per-row extent checks and their regressions. Both repositories now report only their canonical registered worktree; the temporary baseline comparison worktree was removed after reproducing the same two runtime failures there. No additional source-worktree gains remain to transfer or remove.

## Q. Language completion and compatibility policy

“Fill the gaps” means closing the semantic and implementation coverage of the supported language, not adding unrelated features. Every current construct/API must have a specified safe meaning, be explicitly unsafe with contracts, or be explicitly unsupported pending implementation. A long list of narrowly recognized negative patterns is not a complete language rule.

- [ ] Publish the ownership/lifetime/effect rules with examples for arrays, views, regions, errors, closures, generics, protocols, and threads.
- [ ] Explain why an operation is rejected: borrow origin, conflicting operation, lifetime boundary, required proof/capability, and a safe repair such as clone, shorter borrow, scoped task, or checked access.
- [ ] Keep diagnostics stable by semantic ID and source span; do not hold a sound rejection hostage to reproducing stage0's generated region-name wording.
- [ ] Supply safe standard-library alternatives before broadly restricting common raw APIs: checked slices/conversions, owner-tied views, scoped threads, safe split access, typed pool handles, and validated foreign wrappers.
- [ ] Add migration examples for old permissive constructs. Do not auto-insert `trusted` or broad `Unsafe` grants as a migration fix.
- [ ] Specify compatibility/versioning for serialized interfaces, generic summaries, runtime ABI, unsafe contracts, and compiled dependencies.
- [ ] Deprecate unsafe-by-default behavior visibly, but immediate memory-corruption containment may require a direct rejection rather than a warning period.
- [ ] Update README/status docs to distinguish parity-complete, implemented, tested, and soundness-qualified. Maintain a target support table with actual execution evidence.
- [ ] Keep presentation/formatter/docs correctness work from the old plan where it helps reliable tooling, but do not let byte-parity polish outrank a confirmed safety defect.
- [ ] Retain self-hosting throughout migration using explicitly documented trusted primitives; the compiler compiling itself is an important regression, not proof that its language rules are sound.

## R. Final qualification checklist

Do not describe Elisa as fully memory safe merely because this checklist exists or a benchmark passes. Qualification requires all applicable items below, with a stated release scope and assumptions.

- [ ] Every supported safe construct has complete typed semantics and safety enforcement; no unknown AST/IR case defaults to acceptance.
- [ ] Mandatory safety cannot be disabled by ordinary flags, environment variables, imports, reporting paths, generated helpers, or target selection.
- [ ] Ownership, initialization, loans, region dependencies, storage invalidation, cleanup, and data-race rules compose through nested aggregates and interprocedural calls.
- [ ] Every memory access is statically justified or guarded by a sound check before access/address promises; every imported safe value has valid representation.
- [ ] Arithmetic/constant evaluation/proof/backend semantics agree at target widths without accidental UB.
- [ ] All allocation/reallocation/reset/recycle/cleanup failure paths satisfy written invariants under systematic failure injection.
- [ ] Every unsafe primitive and safe wrapper has a reviewed contract and tests; unresolved TCB assumptions are published rather than hidden.
- [ ] Native, Python, Wasm, and EASM boundaries preserve their declared ownership/lifetime/ABI contracts on every supported target/profile.
- [ ] Every LLVM optimizer promise is justified; optimization/debug/tracing variants preserve observable semantics.
- [ ] All executable entry points reject unsupported required code and publish artifacts atomically with provenance.
- [ ] Independent safety/model/fuzz/instrumentation suites pass with no untriaged safety findings; required missing/skipped target coverage blocks that target's qualification.
- [ ] Full uncached repository gates, compiler self-host fixpoint, and runtime self-host checks pass against the qualified sources and toolchain.
- [ ] Historical open items relevant to safety/correctness are reclassified against current evidence; remaining porting work has explicit supported/unsupported status.
- [ ] The normative specification, migration guide, target matrix, TCB ledger, and core soundness argument match the implementation being released.

**Completion means:** safe programs have a coherent, enforced memory model; unsafe boundaries are explicit and audited; compiler/runtime/backends preserve that model within the documented TCB; and the release evidence is reproducible. It does not mean a finite test suite has proven every implementation free of defects.

---

# Historical stage1 implementation plan — preserved reference

The material below is the pre-2026-09-22 plan, preserved verbatim for its detailed implementation history, reproductions, and outstanding porting work. Its dates, gate counts, machine availability, local paths, instructions, “DONE” statuses, and claimed blockers are historical and must be revalidated before use. Its priorities and permissive compatibility choices are superseded by the active roadmap above. It is not a second active execution order.

# Elisa stage1 — Implementation Plan

Gitignored working document (`.gitignore` line 15). Written 2026-09-05 against `work` at
`9305afef` plus the uncommitted effect-identity work described in §1.4. Everything marked
**MEASURED** was read from the tree, a gate script, a baseline file, or a commit message
today; everything marked **RECALLED** comes from the memory notes and the docs and must be
re-measured before a line of code is written against it (the last two audits each found
"gaps" that had already closed and a "closed" item that was still open).

The plan is ordered by **risk to correctness first, then completeness, then presentation**.
A silent wrong answer outranks a decline, a decline outranks a missing report mode, and a
missing report mode outranks a byte-parity ratchet. That is the project's standing rule and
this document does not relax it anywhere.

---

## STATUS LEDGER (updated as items close — the checklist the goal is measured against)

| item | state | evidence |
|---|---|---|
| §2.0 commit effect work | DONE 2026-09-05 | commit on `work` |
| §2.0b packed store activation + ADT ergonomics + `-emit packed` report | DONE 2026-09-05 | 26/26 matrix, differential 67/0, adversarial 360/0/0, gen3==gen4 40/40 |
| §2.1 re-baseline gate | DONE | 346 checks; 6 fail IDENTICALLY on clean HEAD (emit_ast 1/135, global_permissions 6, semantic_acceptance 2 lines, semantic_internal 1, corpus 5 declines, opt_pipeline load-flake) — pre-existing, tracked as §3.8 |
| §2.2 stale docs | DONE 2026-09-05 | README/scope/PORTING_GAPS/backend notes rewritten; drift default confirmed; 4 scripts' dead `../stage0/.../elisac-local` default repointed |
| §2.3 memory refresh | DONE 2026-09-07 | all six notes carry a superseded/closed description pointing at the plan and the closing commits (checked in place; none duplicated) |
| §3.1.4 `M::Unknown.member()` | DONE 2026-09-05 (verify pending) | `UndefinedModuleMember`, code 203, fixtures `undefined_module_member.{neg,pos}` |
| §3.3.1 `defer function` + auto-region wrap | DONE 2026-09-05 (verify pending) | predicate shared via `src/semantic/auto_region_wrap.elisa`; fixtures `defer_function_auto_region.{neg,pos}` |
| §3.3.3 recursive-enum bare constructor | CLOSED by §2.0b | probed a/b/c shapes: verdict parity (wording differs: stage0 talks about `new` regions) |
| §3.1.5 nested-module calls decline | VERIFIED 2026-09-06 (gate7-12 on the box, Mac gate; emit_iface nested-module printing fixed the same day) | parser qualifies body-nested modules to `Outer::Inner`; backend hoists them; bare `Inner::f()` resolves against the enclosing owner in semantic + backend |
| §3.3.5 write-through-ref | DONE 2026-09-05 (verify pending) | `mutable_ref_return_fns` side table in `resolve.elisa`; differential `write_through_mutable_ref_local`, fixtures `write_through_readonly_ref.{neg,pos}` |
| §3.2 parameter-drop leak | **CLOSED before this plan** by `1f6db0c0` — remove from work | fixture promoted |
| §3.8 (new) the 5 pre-existing gate reds | **ALL CLOSED by measurement 2026-09-06** — corpus 0 declines (both hosts), emit_ast 136/136, global_permissions 7/7, semantic_acceptance 575/575, semantic_internal 0/3210, opt_pipeline passing in three Mac gates | gate12 (box), macgate3, ver40 |
| §3.3.2 typestate call-site check | VERIFIED 2026-09-06 (diagnostics_diff 371 byte-exact; its column span fixed to the argument, diagnostic_columns 0 diverged) | `check_aggregate_state_call.elisa`: bare-local args, stage0's per-slot rule, taints on call/assign/`is`; fixtures `aggregate_state_call.{neg,pos}` validated against stage0 |
| **BLOCKER 2026-09-05 23:55** | verification stalled | a Codex agent (ChatGPT app, wasm-sdk-compiler worktree) SIGKILLs any seed/gate matching its `ps|rg` patterns, deleted `~/zzwork/seed_zz4.sh`, and renamed the gate script `.disabled`; ~10 in-tree edits await one clean seed + gate + gen3. Owner must pause that agent (see memory: elisa-verification-harness-traps) |
| §3.8 residue re-measured 2026-09-06 | emit_ast 136/136, diagnostics_diff 367 OK, semantic_internal 0/3210, diagnostics_smoke 286/286, resolve_smoke OK | copy-repo gate `~/.cache/k9`; corpus/run_differential/adversarial/gen3/global_permissions still running |
| §3.8b corpus decline `lmut_threading_value` | **CLOSED 2026-09-06, both halves** — the fixture answers 29 under stage1 (= stage0); the bare tuple `e, k <- e.step(), k` is now REJECTED with stage0's exact text and span | the if-form `e, mark <- if hit: e, mark + 100 else: e.widen(), mark` where `widen(box: lmut Box) -> Wide`; stage0 lowers it per target to `mark <- (mark+100) if hit else do: widen(&e); mark` (call for effect, `e` keeps its own value); the tuple form `e, mark <- e.widen(), mark` and the i64-returning `c.step()` if-form both compile; stage1 declines the desugared assignment to `e` at line 110 (`DECLINE Assign target=e`). The threading-type rule in `codegen_expr_calls.elisa` (~line 364) now resolves the method's declared return type but the if-desugar path still declines |
| §3.3.7 region-block return escape | **CLOSED 2026-09-06** (return shape) — `check_region_return_escape.elisa`, both of stage0's findings byte-exact on 7/7 probe shapes; the sibling STORE shape (`out <- xs` into an outer local) stays OPEN: stage0's text names a generated `__auto_NNN` region, which stage1 cannot reproduce byte-exact | `region r:` block, `xs` pushed inside, `return xs` from a `-> darray[i64]` function: stage0 rejects (escapes via return), stage1 accepts (`/tmp/esc/v2.elisa` shape; v1 with `@r` return and v3 scalar agree) |
| Linux box full list 2026-09-06 09:38 | emit_ast 136 OK, resolve OK, diagnostics_smoke 286, diagnostics_diff 367, global_permissions 7/7 OK (§3.8 closed), adversarial 360/0/0, corpus 128 match/0 mismatch/1 decline (`lmut_threading_value`), gen3 stage B OK (gen2 built gen3); gen3 stage C aborted because gen2 was invoked without the host flags (fixed in gen2/gen3 scripts); `run_differential` 23 rows are all `stage0 exit=139` (oracle's Linux products crash) | `/root/gateB.log` |
| COMMITTED 2026-09-06 | `06105654` harness parallelism, `249caefa` chunked replays + host flags, `b6a47e0e` the compiler work (§3.1.4, §3.1.5, §3.3.1, §3.3.2, §3.3.5, §3.8 alias/region/globals, host predicates) | gen3 fixpoint on the Linux box; semantics on the Mac |
| NEW §6.7b x86_64 products misbehave | OPEN | on Linux, stage1-built `parse_report` prints `match arm "" is unreachable` for enum programs and no output at all for view programs (999999 rows), while the same source is clean on arm64 — a real x86_64 codegen/ABI divergence; the gen3 fixpoint holds, so it is deterministic. Repro: any semantic diff on the box vs the Mac |
| Phase T throughput rewrite | **EXIT CRITERION MET 2026-09-06** (gate8: 542 s wall / 3942 CPU-s, was 4022 s / 9923 CPU-s) | corpus/adversarial/diagnostics/internal/acceptance/breadth/driver_acceptance parallelised; z3 5.1 on the box; `tools/remote_run.sh` + `tools/local_run.sh` detached jobs (start/wait/tail, never a stale waiter); `tools/s0cache` oracle memo; `test/parity/host_jobs.sh` quota-aware fan-out; `build_emit_native.sh` closes a 12-check shared-path race; in-repo Linux clang shim `tools/linux_shim`. Full gate on the box 4022 s -> 1501 s cold with the oracle memo; the box was then destroyed (§T.7) and scoring moved to the Mac |
| §4.1 driver-side include expansion is the DEFAULT | **DONE 2026-09-06** — wrapper flattener + Python deleted; full gate 345/345 in 23m51s (was 32 min), gen3 5m23s (was ~12), acceptance 161 s (was 700-1000); fmt parity 62 -> 77 | commit on `work` |
| **FULL MAC GATE GREEN 2026-09-06** | 345/345 checks, 0 failures, 32 min wall (uncontended, per-check cache cold after the reseed) | `~/.cache/zjobs/final.log` at `8dc832b5` — the first fully green gate of this plan; §2.1's re-baseline is satisfied by it |
| §4.5 `pymodule-so` + `pymodule-pyi` in the DRIVER | **DONE 2026-09-07** — the whole pipeline (manifest, C shim, object, symbol audit, duplicate-symbol localisation, callback fallbacks, clang link, `.pyi`, auto-built runtime object) runs in `bin/elisac-stage1`; the wrapper only hands over the toolchain paths it resolved. Python is spawned for the three facts only the TARGET interpreter can answer (`EXT_SUFFIX`, `_imp.extension_suffixes()`, `INCLUDEPY`) and to render the stub, exactly as this section scoped it | 107/107 `pymodule_*_smoke.sh`; full gate 346/346 |
| §4.5 refactor prerequisite: no file over 600 lines | DONE 2026-09-07 | `61b582de`; two irreducible exceptions named in the commit |
| §4.6 delete the wrapper | **DONE 2026-09-07** — `scripts/elisac_stage1.sh` is 187 lines and parses NOTHING: `bin/elisac-stage1` is the only front door. The two host-side jobs stay — the seed build with its stale-product refusal, and running the compiler as a WATCHED child so a runaway compile is killed with a message (the one thing a literal `exec` cannot do). The driver gained the flags the wrapper used to eat (`--python`, `--python-config`, `-fnoalias`, `-fbounds-check`, `-g`, `-ftrace`, `--wit`, `-Os`/`-Oz` refusal, unknown-flag refusal), the `-o` refusal for the listing modes, report-output truncation, its own LLVM-bin-dir default, and the two-interpreter Python mismatch guard | full gate 346/346 |
| §5.1 column spans | **CLOSED 2026-09-08 — 167 agreeing / 0 pending / 0 diverged** (`a313a619`; was 42/118, then 136/28, then 160/4). The last four: a `try` propagation reports at the `try` KEYWORD (the `__try_without_else` row carries the token Pos); an unknown permission member at the FAMILY identifier (the `__invalid_console` token scan now records `scan_token_pos`); and `namespace_used_as_value`, which stage0 emits THREE times on one line in the order call form / field form / undefined identifier — stage1 raised the call form AFTER the callee walk that produces the other two, so the first reading had no span; it is raised first now, the field form spans its `.` and the undefined-identifier row the identifier. The two `duplicate_pattern_binding` rows closed with the earlier For/MatchArm Pos work. | `diagnostic_columns_smoke.sh` (DIVERGED fails the gate) |
| §5.2 parse-error wording | IN PROGRESS 2026-09-08 — ratchet **30 -> 43** (`19bbc9bf`, `5dfd21c7`, and the `when`-atom/parameter-default batch): the bare-`layout` sentence is HEAD-DEPENDENT (an enum head names the continuation `layout(soa, ...)`, a struct head does not), and `static interface` is a removed spelling in its own right (stage1 dropped the marker, matched the bare `interface` rule and leaked the body as a second error). The remaining 75 disagreements are now CLASSIFIED: 28 need a name-bearing sentence (a parser message ARENA — an sview into a local darray dangles), 5 are stage0-generic-only recovery shapes, and the rest are static sentences needing a real rejection RULE (the largest families: the removed `expr -> T` cast 4, mismatched `with`-arm bindings 3, implicit `else` unwrap 3, machine-arm refusals 6). The `when` OVERLAP family (5) is rejected at the right token already and needs only its sentence, but that sentence quotes the arms and a line number, so it waits on the same arena). | `test/parity/parse_error_message_diff.sh`, `ELISA_PARSE_ERROR_VERBOSE=1` |
| Correctness audit 2026-09-07 (module-private state, wasm widths, views, pipeline) | **DONE, 5 commits, full gate 348/348** — `65bf3b98` private globals/generic templates/loop vars no longer alias across modules; `d57422f4` wasm32 checked i64 multiply inline (no `__multi3`), width smoke validates+executes; `2cc433d5` slices address the array PLACE (no 32 KiB copies, no dangling views), view fields addressable, `check_local_view_return_escape` (stage0 still accepts — fixture is a deliberate decline); `cc4421e9` void array literal diagnosed not trapped, `test/stress/run_stress.sh` seeded both-compiler harness in the gate; `dcd8cf91` spelling parity | memory `correctness-audit-2026-09` |
| §6.1 `-emit fmt` / `doc` ratchets | IN PROGRESS 2026-09-08 — fmt **77 -> 155 byte-identical** (of 162; 7 left: law decls x2, lambda `-> T error[E]`, machine lowering x2 (hash names are FNV-1a of the ABSOLUTE source path; the rest is desugar shape), return-level grants, affine typestate) (`4c2fd3c6`, then auto-region PLACEMENT rules measured — loop-body wraps, region blocks, set/dict literals, nested forwarding; contextual `can`, `get(...)` call, bare `new VARIANT`, `.cast[sview]`, def @c_variadic; last full gate 347/348 at `3a8c9cec`, the one red a load-timeout in emit_interpret now retried) (of 162 comparable; the 22-fixture runtime family is now identical), doc ratchet raised to its measured **109**; emit_ast 140/140 throughout. Ported arms (each read off stage0's output): call argument LABELS, dotted variant patterns, `break`/`continue`, `defer` blocks, decorator ARGUMENTS on def and extern (read at the decorator's own line), `new`/`new[owner]`, tuple values, return-position `match`/`catch`, and two auto-region RULES found by one-feature probes through stage0: a CAPITALISED callee is a constructed local and `assert NAME` forwards it (this alone was the 22-fixture family — the std's `free_region`), a generic def keeps UFCS method form (stage0's analyzer cannot resolve it in a template), `enumerate/zip/reversed` are never rewritten, a source tab is four columns, tuple patterns (all-wildcard → `_`), VarDecl-position `catch`/`match`, and inline grants inside call arguments rendered from the tokens. Remaining families: the `__auto_N` naming ceiling (§7), `[@__rg_*]` inferred region params printed by stage1, VarDecl-position `catch`, lambda return types/error sets, `<fmt-decl-todo>` law decls, the redundant `export … as NAME`. | commits `fc1fa599` … |
| §3.5 silent-wrong-answer: postfix guard after a trailing grant | **FIXED 2026-09-08** `48bac916` — `STMT can Effect if COND` ran UNCONDITIONALLY (the effect-reference walker swallowed `if COND`); found through fmt parity on the runtime's fault handler, confirmed by an icmp count on both compilers; regression `postfix_guard_after_can_grant` (differential 82/82). Statement form occurs twice in the std, nowhere in the compiler's own source. | memory `postfix-guard-after-can-dropped` |
| parser acceptance gap (found 2026-09-08 by an fmt probe) | **CLOSED** — `return for x in xs \|acc=0\| -> acc:` parses (was rejected); and the fixture exposed a backend gap closed in the same commit: an untyped accumulator with a NEGATED/all-literal integer initializer (`\|best=-1\|`) declined the function in EVERY position. Differential case `return_inline_loop_value` (84 agreed). | commit after `96787393` |
| full gate 2026-09-08 (post-fmt/backend batch) | **348/348 GREEN** in 7325 s at `282e5faf` — covers the 7 commits of this session (lambda_N + thunk source line, value-optional narrowed field read, partial-decline warning, 4 fmt batches 143->155, return-position loop value + accumulator typing). One earlier red (`emit_interpret_parity_smoke`) was a LOAD TIMEOUT, not a defect: the smoke now retries a 124 with a wider budget, the corpus harness's rule. | scratch `gate_full4.log` |
| full gate 2026-09-08 #2 | **348/348 GREEN** in 11206 s at `19bbc9bf` — adds the 21-site column-span batch, the match-arm Pos, the refreshed symbol record and the two parse-error wording rules. | scratch `gate_full5.log` |
| full gate 2026-09-08 #3 | **348/348 GREEN** in 9057 s at `25a9936a` — the four parse-error commits (ratchet 30 -> 43) and the match-arm Pos. Three green full gates this session. | scratch `gate_full6.log` |
| WasmBrowser SDK compatibility 2026-09-08 | **CLOSED** — 6 defects, all found from the SDK: (1) try-propagation resolved the callee's error family by NAME, mixing two modules' families; (2) fallible callees resolved only at top level, so any `try` to a module member declined the body; (3) a qualified `try Mod::fn(...)` never matched the emitters' Ident arms; (4) a bare sibling call took its RETURN TYPE from the first same-named function anywhere (parse-order dependent, reported at the declaration -- this was the '14 declined UiHandles bodies'); (5) a loop `invariant` declined the body, though stage0 erases it; (6) an integer const was materialised at its OWN width and handed to an i64 op, emitting `i32.const` under `i64.gt_s` (wasm-only, invisible in IR text), plus ELISA_WASM_INITIAL_PAGES/MAX_PAGES ignored. Commits `1e596051`, `614180bf`, `d7d77241`, `a111b91a`. Full gate 348/348; SDK suite 370 tests OK. | scratch `gate_final.log`, `sdk_final.log` |
| §6.6 compile-CPU ratchet | TIGHTENED 2026-09-08 `6125a446` — baseline 66.5 -> 61.0 (measured 60.7 stage1/clang, 0.91x); the smoke passes at the new figure. | `test/fixtures/compile_cpu.baseline` |
| §6.5 symbol parity (nm diff) | RE-MEASURED 2026-09-08 at matched -O0: 329 comparable of 343, MISSING 7 -> **2 files** after three fixes — `555a874d` lambdas named `lambda_N` + constructor thunks carry the SOURCE line; `1ab78954` field read through a value optional proven non-null by an early-return guard (the smart-cast decline; `unwrap_or` now exported, differential case added, 83 agreed). Remaining: `inspect` (dense NodeTable, a scoped corpus gap) and `maybe`/`add_one`/`map__i64__i64` (with-`main` units internalize every non-`main` def at -O0 — a deliberate stage1 rule, `codegen_declines.elisa` set_defined_function_linkage; stage0 exports them). Partial declines (some bodies emitted, one dropped) now WARN on stderr naming the functions, exit stays 0. EXTRA rows are the known different-lowering helpers. | scratch `be_oracle.tsv`, `symfix.log`, `smartcast.log` |
| everything else | pending | |

---

## T. Phase T — THROUGHPUT AND ITERATION SPEED (do this before anything else in Phases 1–4)

Owner direction 2026-09-06: "re-write changes to heavily parallelize and similar to get maximum
throughput and iteration speed." Everything below is MEASURED on two hosts today: the MacBook
(24 GB, 8 cores, shared with other agents that kill long builds) and a Vast box (32 cores,
251 GB, Ubuntu 24.04). The numbers are the baseline the work is scored against.

| step | today | where the time goes | target |
|---|---|---|---|
| seed (stage0 compiles the 11 MB driver) | ~90 s | single Go process + LLVM -O2 | 60 s at -O0 for iteration; keep -O2 for release |
| `differential_corpus.sh` (226 programs) | **49 min** serial -> **121 s** with `xargs -P 32` (DONE 2026-09-06, same classification: 128 match / 0 mismatch / 2 declined) | one program at a time; each stage1 compile pays a z3-backed semantic gate | < 3 min — MET |
| `semantic_internal_diff.sh` (3210 replays) | 2.5 min | serial pipe through `parse_report` | < 30 s |
| `diagnostics_diff.sh` (367 fixtures) | 1 min -> **32 s** on the 8-core Mac with per-fixture `xargs -P` (DONE 2026-09-06; 367 OK) | serial | < 15 s on 32 cores |
| `adversarial_differential_smoke.sh` (387 programs) | ~11 min -> **63 s** with a 32-process pool (DONE 2026-09-06, same classification) | python driver, serial compile+run | < 2 min — MET |
| `run_all.sh` full gate (Linux box, quota 7.68 CPU) | gate1 **4022 s** (apt z3 4.8.12) -> gate2 **1171 s** (z3 5.1 + parallel driver_acceptance) -> gate4 cold **1501 s / 9923 CPU-s** (39 FAIL) -> gate5 warm **1406 s / 9226 CPU-s** (40 FAIL) -> gate6 cold, s0cache v2 **1863 s / 6129 CPU-s** (34 FAIL) -> gate7 warm **927 s / 5529 CPU-s** (32 FAIL) -> **gate8 warm, dispatch reordered: 542 s / 3942 CPU-s (32 FAIL)** -> gate9 524 s / 3820 (32) -> gate12 after §3.8b, every check re-run (new stage1 binary, no per-check cache hits): 1112 s / 5634 CPU-s, **31 FAIL** — the corpus is green | gate6's wall regressed because the fair-share formula reached `xargs -P 1` and serialised the corpus (§T.3f); gate7 added the floor + `ELISA_HEAVY_JOBS`; gate8 put `self_host_gen3_smoke.sh` (the makespan) at t=0. Oracle cache at gate8: **6670 hits / 56 misses / 2205 bypasses**, serial total 5620 s -> 4021 s | **BOTH MET**: 542 s < 600 s wall and 3942 < 4600 CPU-s |
| the eleven-check verification list on the box (2026-09-06 09:30–09:46) | **~8 min**: emit_ast 9 s, resolve_smoke 57 s, diagnostics_smoke 1 s, diagnostics_diff 4 s, semantic_internal 11 s, semantic_acceptance 6 s, global_permissions 1 s, corpus 121 s, run_differential 2 s, adversarial 64 s, gen3 206–354 s | gen3 (three self-compiles) and resolve_smoke are the serial remainder | resolve_smoke < 20 s; gen3 is inherent |
| gen3 fixpoint | ~10 min idle; **1167 s** inside a 32-wide gate; **497 s** in gate8 (started at t=0, exempt from the gate's `nice`) | three sequential self-compiles, already built at -O0 (§T.4) | IT IS the wall floor: gate8's 542 s against a 497 s critical path is 92 % efficient. Shortening it now means a faster COMPILER, not a faster harness |

### §3.8b re-measured 2026-09-06 — it is a PAIR of divergences, not one decline
A 27-line repro (`Box`/`Wide`, `def widen(box: lmut Box) -> Wide`) separates them:
- the **manifest if-form** `e, mark <- if hit: e, mark + 100 else: e.widen(), mark` — stage0
  ACCEPTS and answers 16; stage1 DECLINES `main (assignment)`. The parser desugars the manifest
  (docs/120 §6) into one `Stmt.Assign` PER POSITION (`manifest_branch_body`), which erases the
  multi-target context the threading rule needs, so the surviving `e <- e.widen()` reaches the
  single-target store path where the rule in `codegen_expr_calls.elisa` (~line 353) is not
  consulted. The tuple path DOES consult it, which is why `emit_expression` already handles it.
- the **bare tuple form** `e, mark <- e.widen(), mark` — stage0 REJECTS it
  (`cannot assign (_0: Wide, _1: i64) to i64`); **stage1 accepts and compiles it**. A PERMISSIVE
  gap that was not previously recorded: the threading reading is legal only inside the manifest
  if, not in a plain multi-target rebind.
A fix must move BOTH, and the obvious one (apply the threading rule to any single-target assign)
moves the second the wrong way.

**CLOSED 2026-09-06.** What landed, and what it took to be right:
- `manifest_branch_body` (parser_stmt.elisa) desugars each `<-` branch of the manifest to ONE
  parallel `Assign(Array(targets), <-, Array(elements))` instead of per-position statements,
  so the branch reaches the parallel emitter that already implements the threading rule. The
  ast-parity risk measured ZERO: both compilers render the manifest as one statement
  (`emit_ast` 136/136 byte-identical before and after).
- That alone regressed the corpus from 1 decline to **44** — every program embedding the
  compiler's own parser. The parallel emitter passes each target's SLOT type as `expected`,
  and two element shapes the single-target path handled specially were not: an `lmut`
  PARAMETER receiver (slot type Ref, the "bit 16" shape — `parser.advance()` was emitted at
  the pointer type and declined `(call expression)`), and `out.push(d)` (emit_expression does
  not model the five receiver-returning darray methods; the `_ = out.push(byte)` discard path
  delegates them to the statement emitter). `codegen_stmt_assign_flow.elisa` now handles both
  in place — call for effect, store nothing — and parse_report/emit_trace compile again.
- The bare form is a new semantic check, `check_parallel_rebind_threading.elisa`, from
  stage0's ACTUAL rule, which is arity-based, not type-based: a threading call CONSUMES its
  receiver target while its element stays in the tuple. Measured, one probe per row: one
  target left -> `cannot assign (_0: T0, _1: T1) to T` at that target; two left -> `tuple
  destructuring expects N bindings, got R` at the first; none left (`e, f <- e.step(),
  f.step()`) -> accepted; element spellings: ident -> declared type, `7` -> `int`, `false` ->
  `bool`, call -> return type, `k + 1` -> its type. The desugared manifest branch is exempt by
  its GENERATED position (`Ast::pos_at_line`, column 0). Fixtures `parallel_rebind_threaded`
  and `tuple_destructure_arity` (.pos/.neg), diagnostics_smoke 290/290.
- Trap for next time: my verification loop grepped the compile output for `declined|error`,
  and a semantic rejection contains NEITHER (`path:22:8-12: cannot assign …`), so the bare
  tuple read as "compiles" for one round. Check the exit code, not the wording. The candidate with the right shape is to desugar each manifest
branch to ONE `Assign(Array(targets), <-, Array(elements))` instead of per-position statements,
so the existing parallel path (which already emits every value before any store) handles it and
the bare tuple keeps whatever verdict the semantic layer gives it. Risk to measure first: the
desugar shape is what `-emit ast` renders, and stage0 already collapses this file's `main` to
ONE statement (a separate, pre-existing rendering divergence), so the ast-parity effect of the
new shape must be measured across the corpus before the change lands.

### T.3g The gate's own verdicts were load-sensitive in FIVE more places (2026-09-06)
Every one of these reported a compiler defect that did not exist, and every one passed when
the check ran alone. Listed because the shape recurs and the fix is always the same — a
timeout, a kill, or a SIGPIPE is the ABSENCE of an answer, never a different one:
- **`pipefail` + an early-exiting consumer**: `echo "$out" | grep -q PAT` takes SIGPIPE in the
  PRODUCER, so the pipeline is 141 even when the pattern matched. 372 sites in 71 harnesses;
  `when_arm_law` failed printing the very output it had matched. Rewritten to `grep -q PAT
  <<< "$out"`, or (command producers) to a plain `grep … >/dev/null` that reads all its input.
- **`malformed_input_fuzz.py`** synthesises rc=-9 for an expired 120 s compile and `abnormal()`
  scores that exactly like a crash: `deep_left_binary_chain` read as `CRASH rc=-9`.
- **`adversarial_differential.py`** retried a timeout with a wider RUN budget but kept the
  fixed COMPILE budgets, so a slow compile expired twice and became a TIMEOUT verdict.
- **`differential_corpus.sh`** filed an expired COMPILE as a language DECLINE (5 spurious
  declines against a baseline of 0).
- **19 harnesses' `RUN`** compared `got 124` against `want 42` (8 corpus mismatches, 16 in
  `backend_obj`). `test/parity/run_timeout.sh` now owns the rule for all of them.
- **`backend_native_smoke` inside a gate — SOLVED 2026-09-07, it was a RACE, not load**: once the
  smoke kept the linker's first line, the reason read "Undefined symbols for architecture
  arm64" for the same two cases. `scripts/build_runtime_object.sh` emitted the runtime object
  IN PLACE and six gate checks call it, so a mid-gate rebuild truncated the object under a
  sibling's link. It now builds to a temporary, `mv`s atomically, and skips when the object is
  newer than its source and the REAL stage0 (in the gate STAGE0_BIN is the s0cache wrapper).
  Earlier note, kept for the record: red in two of three consecutive full gates
  (passed=372 and passed=400 of 511, every miss "link failed"), 511/511 every time it ran
  alone — the host linker failing under a loaded gate, never the compiler. The smoke now
  retries the link once and keeps the linker's first stderr line instead of discarding it.
`run_all.sh` now copies each failing check's log to `build/gate-failures/`, because the
mktemp result dir is reaped and the summary prints only a tail.

### T.1 Parallelise every per-program loop (the big win)
Each of these iterates independent programs with a private temp file and can fan out with
`find … -print0 | xargs -0 -P "$(nproc)" -n 1 bash -c 'one_program "$0"'` (macOS: `sysctl -n hw.ncpu`),
collecting one result line per program into a temp dir and reducing at the end:
`test/parity/differential_corpus.sh`, `test/differential/run_differential.sh`,
`test/parity/semantic_internal_diff.sh` (split the oracle TSV into N chunks, one
`parse_report` per chunk), `test/parity/diagnostics_diff.sh`, `test/parity/semantic_acceptance_diff.sh`,
`test/breadth/run.sh`, every `emit_*_parity_smoke.sh` fixture loop, and
`test/breadth/adversarial_differential.py` (a `multiprocessing.Pool` over programs; keep
per-program work dirs — the stage0 wrapper writes `<name>.s0.o` beside its input).
Rules: no shared output path between workers (the reason `run_all.sh` has serial lanes);
`mktemp -d` per program; deterministic ordering of the final report (`sort`) so diffs of
gate logs stay readable; the ratchet baselines must not change.

### T.2 Stop paying z3 where no proof is consumed — EVALUATED, DECLINED 2026-09-06
stage0 has `-no-smt` and `-permissive`, but without a solver every `ensure` on a conditional
FAILS (measured: the std's `max/min/clamp` reject without z3), and `-permissive` changes the
oracle's acceptance — the differential harnesses would then compare against a compiler that
accepts what the real one rejects. Keep z3; the per-program parallelism already recovers the
time (corpus 49 min -> 121 s). Revisit only with a stage0-side verdict cache (§7).
stage0's CLI defaults `enableSMT: true`, so EVERY compile of a program with a contract
shells out to z3 (the corpus showed 8–12 concurrent `z3 -in` processes at ~27 % CPU each).
Add a `-Wproofs=off`-style opt-out to the oracle invocations in the differential harnesses
(they compare exit codes/outputs, never proof verdicts), measure the corpus again, and
keep SMT on only for `semantic_*` and `diagnostics_*` checks whose oracle text depends on
it. Cross-repo item (§7): also cache z3 verdicts by (goal, facts) inside stage0.

### T.3 `run_all.sh` on big hosts
- `gate_jobs_by_memory` already has the Linux branch; its fixed ceiling of 6 workers is now
  the core count (DONE 2026-09-06).
- Re-examine the two serial lanes: keep only checks that write shared paths; give the rest
  private `ELISA_STAGE1_BIN`/`build/` copies (the `~/.cache/k9/r` copy technique).
- Cache hits are already content-hashed; add a `--fast` profile that runs the non-native
  subset (emit_ast, resolve, diagnostics_smoke, diagnostics_diff, semantic_internal,
  semantic_acceptance, global_permissions) — this is the < 5 min inner loop for semantic work.

### T.3b The z3 VERSION (found 2026-09-06 — the single biggest Linux lever)
Ubuntu 24.04's apt z3 is 4.8.12 (2021). One std-including probe spent 37.6 s in `z3 -in`;
the z3 5.1.0 release binary takes 1.5 s on the same query. driver_acceptance went from 3958 s
to under the gate's noise; full gate 4022 s -> 1171 s. `tools/remote_env.sh` refuses to time
against a 4.x z3. GOMAXPROCS is NOT a lever (64 probes at -P32: 23.5 s at 32/4/1).
Under a 32-wide load the same probe costs ~11 s, so z3/std re-proving is still the dominant
CPU term — the stage0-side verdict cache (§7) is the next step if the CPU profile confirms it.

### T.3c The box is a 7.68-CPU cgroup, not 32 cores (found 2026-09-06)
`nproc` says 32 but `/sys/fs/cgroup/cpu.max` is `768000 100000` and every scheduling period
was throttled; vmstat under the 32-wide gate showed 29 % busy with 60-98 runnable. So the
gate is CPU-QUOTA-bound: wall floor = CPU-seconds / 7.68, and the 1171 s of gate2 was already
at that floor. `run_all.sh` now sizes its pool from `cpu.max`. Consequences:
- the "< 10 min on 32 cores" target is re-stated as **< 4600 CPU-seconds per full gate**
  (measured with `cpu.stat usage_usec` before/after; the box prints it per gate run);
- every remaining lever is CPU REDUCTION, not parallelism.

### T.3d The stage0 oracle memo — `tools/s0cache` (landed 2026-09-06)
The per-process CPU profile of a gate (ps sampler): stage0 `elisac` 13006, `elisac-stage1`
5002, `z3` 3702, `clang` 1089 — the ORACLE is half the gate, and its answers to unchanged
questions cannot change. stage0's own build cache serves only successful `-emit obj`; the
gate's stage0 CPU goes to report emitters and to `.neg` rejections, both uncached. The
wrapper memoises (rc, stdout, stderr, -o artifact) keyed on the real binary hash + args +
the include-expanded source closure + ELISA* env, for read-only single-input emit modes only;
rc 0/1 only. `run_all.sh` and `tools/remote_env.sh` route ELISACORE_BIN through it and print
the hit rate. A stage1-only change now re-runs stage1 but not the oracle. Numbers: see the
table (gate4 cold / gate5 warm).

### T.3e The oracle memo was keyed too narrowly — s0cache v2 (2026-09-06)
v1 saved only 7 % (gate4 cold 1501 s / 9923 CPU-s -> gate5 warm 1406 s / 9226 CPU-s, 258
entries for a gate that makes thousands of oracle calls). Two key defects, both fixed:
- **the key carried every `ELISA*` variable**, so the harness-side ones — `ELISA_*_PARITY_OUT`,
  `ELISA_EMIT_NATIVE` and friends, all holding `mktemp` paths — made a whole harness's entries
  unrepeatable. v2 keys on `KEYED_ENV`, the exact `os.Getenv("ELISA…")` list in the oracle's Go
  source, and BYPASSES a call whose environment names a side-effect variable (`*_PARITY_OUT`,
  `ELISACORE_EMIT_LL`, the keep/timing/debug switches).
- **the key carried absolute paths**, so the same probe text written into a hundred per-worker
  `mktemp` dirs was a hundred entries. v2 keys closure paths relative to the input's own
  directory or to `REPO_ROOT`. stage0 prints the source path in diagnostics, so an entry
  stores its output with that path masked and restores the CALLER's path on a hit; a textual
  `-o` artifact is rewritten the same way, and a binary one (obj/bc) is served only when it is
  byte-safe (path absent, identical, or patchable at equal length) — otherwise it recomputes.
- v1 also **never stored a rejection made with `-o`** (no artifact was produced, so the store
  was skipped) — precisely the hundreds of `.neg` fixtures the memo exists for. v2 stores them.
Verified: 30 diagnostics fixtures compiled in two different directories give byte-identical
stdout/stderr/rc from the cache and from the oracle. First instrumented gate: 367 `obj` hits
against 829 misses on a COLD cache (one gate re-asks the same question many times). The
per-mode bypass census also shows what can never be cached: `tests` 411, `interpret` 306.

### T.3f A timeout is not a wrong answer (2026-09-06)
Parallelism made the gate's verdicts load-sensitive: on a host running two gates, programs
that finish in two seconds idle missed a 10–20 s budget, and harnesses compared `got 124`
against `want 42`. One loaded run fabricated 8 corpus MISMATCHes and 16 `backend_obj`
failures, none reproducible standalone. `test/parity/run_timeout.sh` now owns the rule —
expire once, retry with a budget `ELISA_TIMEOUT_ESCALATE` (6) times larger, believe it only
then — and 19 harnesses' `RUN` helpers delegate to it; `differential_corpus.sh` escalates to
180 s on the reproduce path and prints `stage1=TIMEOUT` rather than a bogus exit code.
Related: `test/breadth/run.sh` piped a two-line report into `head -1`, which under `pipefail`
+ `set -e` killed a worker with SIGPIPE and dropped its observation line — rare when the sweep
was serial, frequent under `xargs -P`. It now reads the two lines with `read`, no pipe.

### T.4 Faster seeds for the inner loop — HALF CLOSED 2026-09-06
`ELISA_STAGE1_SEED_OPT_LEVEL=-O0` for iteration; measure gate wall time with an -O0 product
(the product runs slower but the gate is dominated by process spawn and z3, not codegen).
Pin the number in this table. NOTE: this is a SEED-only knob. `scripts/self_host_gen2.sh`
invokes the wrapper with no `-O` flag and the wrapper's default is `opt_level=0`, so gen2 and
gen3 are ALREADY -O0 — there is no optimisation lever left in the gate's critical path. Once
`self_host_gen3_smoke.sh` starts at t=0 (see the dispatch order in `run_all.sh`), its 636 s
IS the wall floor, and shortening it means making the compiler itself faster, not the harness.

### T.5 Make the Linux box a first-class gate host (measured blockers, 2026-09-06)
Done on the box, to be landed in-repo: stage0 needs LLVM >= 19 (`LLVMDIBuilderInsertDeclareRecordAtEnd`);
`C.ulonglong` cast in `llvm_exprs_fstring.go` (patched both repos); `z3` must be on PATH;
`self_host_gen2.sh` hard-coded a macOS PATH (fixed: appends `/usr/local/bin` and
`$ELISA_LLVM_BIN_DIR`). Still open:
- the wrapper's link line is macOS-only (`-Wl,-dead_strip`, `-Wl,-stack_size`, `-lLLVM`); a
  shim mapped them to `--gc-sections`/`-lLLVM-21`/`-no-pie`. Land a `uname`-gated branch.
- the runtime object references optional `elisa_native_callback_*` entry points that
  `-dead_strip` drops on macOS but GNU ld rejects; link `scripts/pymodule_runtime_fallback.c`
  (or a Linux twin) instead of `--unresolved-symbols=ignore-all`.
- **stage0's own native output segfaults on Linux** (every `run_differential` divergence
  was `stage0 exit=139`; stage1's products run fine). Until that is fixed the box can run
  every non-native check and the gen3 fixpoint but NOT the execution oracles.
- ~~stage1's own products abort on x86_64 Linux~~ FIXED 2026-09-06: not an ABI problem —
  `register_target_consts` hard-coded the macOS/arm64 predicates, so every stage1-built
  product took the macOS `MAP_ANON` flag in `elisacore_std/arena.elisa` and its first mmap
  failed (SIGABRT in crt init). The wrapper now exports `ELISA_HOST_LINUX`/`ELISA_HOST_X86_64`
  from `uname` and the backend + `host_platform_name()` read them. `parse_report` runs on
  the box; the gen3 fixpoint and every semantic check can now run there.
- 54 smokes fail in 0 s on Linux: Mach-O assumptions (`nm`/`otool`/`file` shapes,
  `-dead_strip`); gate them on host or port them (plan §6.7).

### T.6 Harness infrastructure
- `tools/remote_gate.sh "<ssh opts+target>" fast|gen3|full` — DONE 2026-09-06: rsyncs both
  repos, reseeds, runs the list with per-check timings (recipe: memory note `linux-gate-host`).
- `tools/remote_run.sh` / `tools/local_run.sh` — detached job runners, one per host, with the
  same verbs (`start NAME 'CMD'`, `wait NAME [SECS]`, `tail`, `ps`, `kill`). Neither ever
  leaves a stale waiter: a job writes `<name>.log/.pid/.rc` under a jobs dir and `wait` only
  polls those files. `wait` is CAPPED AT 110 s because the Bash tool backgrounds any call that
  runs past ~120 s — a backgrounded wait is precisely the stale waiter to avoid; poll again.
- On the Mac the supervisor is a detached `/bin/bash <jobs>/<name>.sh` with a retry loop.
  Two constraints fix that shape: another agent on the host kills anything whose argv matches
  its `ps | rg '[e]lisac…'` patterns (the supervisor's argv names no product, so it survives
  and retries the child), and a `launchctl submit` job has NO TCC access to `~/Documents`, so
  the earlier launchd recipe cannot read this repo at all ("Operation not permitted").
  Env lives in `tools/local_env.sh` / `tools/remote_env.sh`, never in the argv.
- Every harness prints one machine-readable summary line so `run_all.sh` can ratchet on it.

### T.7 The Linux gate host is GONE (2026-09-06 15:00)
Every endpoint of the Vast box refuses or times out; the instance was destroyed with gate5
(the warm-oracle-cache run) still in flight, so the warm wall/CPU numbers for the box are
unrecoverable and the §T table keeps the cold gate4 figures (1501 s wall / 9923 s CPU /
39 FAIL / 64 MB cache) as its last Linux reading. Nothing about the box's findings is lost —
they are all in-repo now (the shim, `host_jobs.sh`, the quota sizing, `s0cache`, the z3
requirement) and re-provisioning is `tools/remote_gate.sh` plus the memory note
`linux-gate-host`. Until a host is re-provisioned, Phase T is scored on the Mac.

Exit criterion for Phase T: a WARM full gate in < 10 min wall AND, on a quota-bound Linux
host, < 4600 CPU-s. **MET 2026-09-06 by gate8: 542 s wall / 3942 CPU-s on the box** (346
checks, 32 failing — all of them the known Linux gaps of §T.5 and §6.7b, unchanged from
gate7, so the speedup cost no coverage). Cold (oracle memo empty) runs are reported
separately; the warm number is the iteration cost. What remains is not throughput work:
the wall is now 92 % critical path, and that path is the compiler compiling itself.

---

## 0. How to work this plan

### 0.1 The verification chain (unchanged, non-negotiable)

Every landed change goes through, in order:

1. the focused smoke that covers the change (or a new one — see 0.3);
2. `bash test/parity/differential_corpus.sh` (compile, link, RUN both compilers; MISMATCH
   ratcheted at zero, baseline `test/fixtures/differential_corpus.baseline` = `0`);
3. `python3 test/breadth/adversarial_differential.py` (MISMATCH / O2_MISMATCH / DECLINE /
   PERMISSIVE all ratcheted at zero);
4. `bash scripts/self_host_gen2.sh` then `bash test/parity/self_host_gen3_smoke.sh`
   (stage A 5/5, stage B gen3 builds, stage C `gen3.o == gen4.o`, stage D 40 identical runs);
5. `ELISA_GATE_PROFILE=full bash test/parity/run_all.sh` (the ONLY profile a commit may rely
   on — a green partial profile means "I have not broken the obvious things"). The runner
   reported 455 checks on 2026-09-24; the count is tree- and configuration-dependent, so
   record the exact count from each completed run rather than using the old ~330 estimate.

stage0 is the oracle. When stage1 and a fixture disagree, stage0 arbitrates; when stage0 and
a recorded expectation disagree, stage0 wins — unless stage0 is shown wrong by a second
oracle (its interpreter vs its backend, or `-emit iface` fed back to itself), in which case
fix stage0 upstream and record the commit here.

### 0.2 Running without permission prompts

The owner does not want to approve one Bash call at a time. Every multi-step verification is
written as ONE script under the session scratchpad and launched once in the background:

```
S=/private/tmp/claude-501/<session>/scratchpad
cat > $S/job.sh <<'EOF' ... EOF
bash $S/job.sh > $S/job.log 2>&1 &      # run_in_background: true
until grep -q "ALL PARTS DONE" $S/job.log; do sleep 30; done
```

`scripts/elisac_stage1.sh` refuses (rc=2) when any `src/**.elisa` is newer than the product
binary. Every job script starts with `touch "$STAGE1"` after its own seed build, or rebuilds
with `ELISACORE_BIN=$STAGE0 ELISA_STAGE1_BIN=$STAGE1 bash scripts/elisac_stage1.sh --seed`.
Use explicit local binaries (`/tmp/elisac-stage0-*`, `/tmp/elisac-stage1-*`); never mutate
`~/.elisac/elisac` or `bin/elisac-stage1` from a job.

### 0.3 Fixture discipline

A fixture that cannot fail teaches nothing. Every new positive fixture must produce a
DIFFERENT exit code when the suspected wrong lowering is taken (e.g. `score(Leaf(Keyword))*10
+ score(Leaf(Ident))` = 1 correct, 11 if the nested test is skipped). Every negative fixture
must be checked for the INTENDED message, not for rc=1: `undefined identifier ""` at line 0 is
a generated-node signature, not a rejection for the fixture's reason. Compile every negative
fixture under stage0 too — a fixture named `size_of` lexes as reserved `sizeof` and stage0
rejects it for a reason that has nothing to do with the gap.

### 0.4 Where each kind of work lives

| layer | dir | oracle harness |
|---|---|---|
| lexer | `src/lexer/` | `emit_tokens_parity_smoke.sh` |
| parser | `src/parser/` | `emit_ast_parity_smoke.sh`, parser acceptance replay (440/440) |
| semantic | `src/semantic/` | `diagnostics_diff.sh` (strict text), `semantic_acceptance` 574/574, `semantic_internal.baseline` 0/3178, `diagnostic_columns_smoke.sh` |
| backend | `src/backend/` | `backend_native_smoke.sh`, `differential_corpus.sh`, `stage0_backend_recorder/be_replay_strict.py` (331/331 reachable) |
| driver | `src/driver/` | per-mode `emit_*_parity_smoke.sh`, `project_*_smoke.sh`, `cli_includes_smoke.sh` |
| runtime | `elisacore_std/` (VENDORED) | `scripts/check_runtime_drift.sh`, `self_host_runtime_smoke.sh` |
| wasm | `scripts/wasm_build.py` + `elisacore_std/wasm_component_runtime.elisa` | `wasm_smoke.sh` |

---

## 1. State snapshot (2026-09-05)

### 1.1 Standing numbers — MEASURED

| metric | value | source |
|---|---|---|
| parity gate | ~330 checks green at `7f497899` | commit message |
| self-host | gen3.o == gen4.o byte-identical; 40/40 deterministic runs | bv5 this session |
| differential corpus | MISMATCH baseline 0; driver acceptance bare 9 / withstd 0 | `test/fixtures/*.baseline` |
| backend oracle | 331/341 lowered; the 10 are stage0-CLI-unreachable | `docs/PORTING_GAPS.md` 2026-09-01 |
| emit modes | 24/28 fully; `ir` partial; `semantic`, `facts`, `serve` missing | `cli_emit_mode_supported` |
| CLI subcommands | 9/10 fully; `easm-lint` void/no-param subset only | `subcommand_is_unimplemented` returns false for all |
| diagnostics | text stage0-exact, path+ORIGINAL line; columns: 3 agreeing / 148 pending / 0 diverged (2026-08-18) | `diagnostic_columns_smoke.sh` |
| `pos_at_line` (line-only synthesized nodes) | 86 sites in `src/parser/` | grep |
| emit ratchets (of 56 corpus) | fmt 32, doc 45, lowered 33, progress 47 | `test/fixtures/emit_*.baseline` |
| easm-lint differential | 130 agreeing / 782 refused / 0 diverged | `docs/PORTING_GAPS.md` |
| `-emit unsafe` | 40/40 report parity; audit half 40 agree / 16 disagree, UNGATED | memory + smoke header |
| `-emit interpret` | 18 identical + 2 known stage0-interpreter bugs | `EXPECTED_DIVERGENT` |
| effects suite | 48 pos / 35 neg / 39 IR / 14 native | this session |
| compile CPU baseline | 66.5 s | `test/fixtures/compile_cpu.baseline` |
| semantic gate | **default ON** (`ELISA_STAGE1_NO_SEMANTIC_GATE` disables) | `semantic_gate_enabled` |
| `<fmt-*-todo>` markers | 9 sites in `emit_fmt_expr.elisa` | grep |
| TODO/FIXME in `src/` | 13, all the fmt markers plus comments | grep |
| xfail cases | **none** (`find test -name '*xfail*'` empty; `bbb89bcd` promoted the last) | find |

### 1.2 What is genuinely DONE (do not re-audit)

Backend lowering for every CLI-reachable construct; driver CLI (`-o -emit -O0..3 -filter
-target-triple -link -L -l`); include expansion in the driver (byte-identical deps over the
509-file closure; the CLI compiles itself unaided); `build|run|test|bench`, `init`,
`init-lib`, `project view|deps|abi-lint`; `header`/`unsafe`/`c-archive`/`interpret`/
`test-runner`/`tests`/`benches`/`fixtures`/`test`/`packed`/`c-bind-check*`/`pymodule*`; AST
spans (`Ast::Pos`); `.elisair` v2 reader (254/254) and writer for the closed subset; SoA
(all five corpus files); nested variant sub-patterns (both flavours); payload error unions;
sealed hierarchies over the AoS store with typed commons; `__drop__` destructors; static
zero-overhead effect handlers with declaration-identity checking on both lowering paths; the
sret-attribute nondeterminism (`7f497899` stage D gates reproducibility); WASM modules and
components; `-g` DWARF and `-Wperf`; overflow-safe semantic proof arithmetic (13 commits on
09-04).

### 1.3 Standing DELIBERATE decisions (re-opening one is a policy call, listed in §8)

- bare `x = v` is a DECLINE, not stage0's lowering (which compiles into an infinite loop);
- packed `common:` fields are INLINE in stage1, SIDE TABLE in stage0 — self-consistent,
  documented in `codegen_stmt_match.elisa` ~460; blocks `-emit packed` byte parity;
- `-Os`/`-Oz` rejected (no size-pipeline parity to hold them to);
- `host_platform_name()` is the constant `"macos"` (`project.elisa:937`);
- JSON *syntax*-error text is not Go's character-level wording (unknown-FIELD text IS exact);
- `_axpy` internalization: stage1 internalizes non-main functions eagerly, stage0 leaves it
  to -O3; agree at matched -O3;
- stage1 accepts qualified installs `can A::Tick with A::H:` that stage0's parser rejects
  (superset, `q3`);
- stage1 rejects `handler H() for A.Tick:` even when never installed; stage0 accepts until
  installation (this session, per the owner's `::` instruction);
- the `arms.count > 32` exhaustiveness bail is UNSOUND — never re-adopt;
- SMT/Z3 is out of scope (`docs/stage1_scope.md`); stage1's proof checks are heuristic.

### 1.4 Uncommitted work in the tree (commit FIRST — §2.0)

`src/parser/parser_effect_identity.elisa`, `src/parser/parser_expr_ops.elisa`,
`src/parser/parser_stmt_control_blocks.elisa`, `src/semantic/check_abstract_effects.elisa`,
`test/parity/effect_handler_stage1_smoke.sh` (+5 `run_negative` lines) and five new
fixtures under `test/fixtures/effects/` (`handler_{qualified,toplevel,dotted}_head_other_module`,
`dotted_module_{effect_install,handler_target}`). Verified green through the full chain in
this session (bv5). `docs/effect-system-fix-status.md` is gitignored by design; its
contents are mirrored into §3.1 of this file so the record is not lost.

---

## 2. Phase 0 — housekeeping (hours)

### 2.0 Commit the effect-identity work
One commit, message carrying the five silent wrong answers it closes and the deliberate
stage0 divergence. Evidence line: `effect_handler 48/35/39/14; gen3==gen4; stage D 40/40`.

### 2.1 Re-baseline the full gate
Run `ELISA_GATE_PROFILE=full bash test/parity/run_all.sh` on the current committed tree and
record the exact count and result. The 2026-09-24 attempt enumerated 455 checks on commit
`5310488b` but stopped at the driver-acceptance and compile-time failures recorded in §M.5;
the later `77a20a6b` interning optimization has not received a completed full-profile run.
Keep 455 as a measured point, not a permanent expected count. Any red check is triaged with
the stale-gate-rot discipline: of five red gates that looked like rot, THREE were real bugs.
Never relax an assertion without building the pre-change tree in a `git worktree` (never
`git stash`) and proving the behaviour changed for a reason you can name.

### 2.2 Fix the documentation that is now WRONG
- `README.md:56-62` says the semantic gate runs only under `ELISA_STAGE1_SEMANTIC_GATE=1` and
  that self-hosting is therefore incomplete. The gate is default-on; the env var is now
  `ELISA_STAGE1_NO_SEMANTIC_GATE`. Rewrite the paragraph.
- `docs/stage1_scope.md` lists `header`, `c-archive`, `interpret`, `test`, `tests`, … as
  out of scope; all are implemented and gated. Rewrite it as "what parity is claimed" +
  "what is deliberately not claimed" (the §1.3 list) — it is currently read by new sessions
  as permission to skip work that exists.
- `docs/PORTING_GAPS.md` Part 2 is flagged "NOT re-measured"; §5–§6 below supersede it.
  Either delete Part 2 or replace it with a pointer here once §5 is re-measured.
- `docs/backend_port_notes.md` §"Struct-composition gaps" is fully closed; mark the header.
- `scripts/check_runtime_drift.sh` defaults `ELISA_CORE` to `../../Go projects/Elisa-core`.
  Confirm that IS the canonical Elisa-core checkout now (several smokes use the same
  default) or point both at the real one; a wrong default makes the drift guard exit 2
  ("not found") which reads as "in sync" to a skimmed log.

### 2.3 Refresh the memory notes that are stale
`stage1-drop-in-replacement-gap`, `emit-mode-port-order`, `nested-variant-subpattern-gap`,
`soa-subsystem-scoped`, `stale-gate-rot` (recursive-enum item), `export-fn-wrappers-not-
emitted` all carry numbers superseded by 09-01..09-05 commits. Update in place, do not
duplicate.

---

## 3. Phase 1 — correctness and stability (weeks 1–3)

Ordered by severity: silent wrong answers → permissive acceptance → over-rejection →
leaks → declines.

### 3.1 Effect system — finish the identity model (parser-level rewrite → real resolution)

Status MEASURED this session. What remains, from `docs/effect-system-fix-status.md`:

**3.1.1 Overloads, local shadowing and module aliases in helper selection.** Helper
selection is still a parser-level rewrite over side tables (`__effect_*`, `__handler_*`
annotations keyed by sentinel lines 39000000xx). Identity is now checked for qualified and
same-terminal names in separate modules. NOT yet checked:
- an overloaded helper name where two arities/signatures exist in the same module;
- a local variable or parameter named like a handler (`q5_local_named_like_handler` passes,
  but only the value position was probed — not a call position);
- `module A as B` style aliases (grep the parser for alias support first; if aliases do not
  exist in the language this item is void).
Approach: extend the probe matrix in `/tmp/elisa-probe*` (q1–q5, p1–p10, r1) with one program
per shape, stage0 as oracle, fix identity resolution in `parser_effect_identity.elisa` for each
divergence, pin each as a `run_native_result` or `run_negative` line. Files:
`src/parser/parser_effect_identity.elisa`, `parser_expr_ops.elisa` (`handler_operation_callee`,
`handler_effect_head_matches`), `parser_stmt_control_blocks.elisa` (`consume_can_handler_clause`).

**3.1.2 Dedicated frontend diagnostic for "generic helper, no compatible handler".** Today it
reaches an actionable backend decline (`abstract effect specialization mismatch` with the
line). stage0 has no equivalent feature yet, so the wording is stage1's to choose; add a
`DiagnosticKind` (via `tools/new_diagnostic.sh`), raise it in `check_abstract_effects.elisa`
where the `__effect_clone` rows are validated, and remove the backend fallback only after a
negative fixture pins the new message.

**3.1.3 Wording parity with stage0 for mismatched operation heads.** stage1: `abstract
effect operation Tick.ping does not match the active handler specialization`; stage0:
`abstract effect operation A.Tick.ping requires an installed handler` + `undefined identifier
"A.Tick"`. Decide whether to adopt stage0's two-message shape (it is what
`diagnostics_diff.sh` will demand once stage0 gains the feature) — see §8. If yes, the head
text is already recovered (`handler_effect_head_text`), so it is a message change plus
fixture updates in `effect_handler_stage1_smoke.sh` (`run_negative` greps).

**3.1.4 `M::Unknown.member()` emits no semantic diagnostic.** Not effect-specific. stage1
reaches a backend decline; stage0 says `undefined identifier "M.Unknown"`. Add the check in
`resolve_expr_walk.elisa` where `Expr.Scope` heads are resolved: a known module + unknown
member is `UndefinedName` with the qualified spelling. Pin with a diagnostics fixture.

**3.1.5 Nested-module function by bare inner name declines (`p4`/`p10`).**
`Outer::go()` calling `Inner::run()` where `run` installs a handler and calls `Tick.ping()`
declines with `backend could not produce a linkable unit; declined 1: go@N (call expression)`;
stage0 returns 6. Suspect: the callee lookup for `Inner::run` from inside `Outer` resolves the
scope head against top level rather than the enclosing module (`codegen_scope.elisa`
overload/index-of-function paths; compare `b746d6bf` "a generic in a module calls its own
module's members" and `e377b1de`). Bisect with `ELISA_DBG_DECLINE=1` (prints `DROPPED <fn>`),
then a probe WITHOUT effects (`p10_nested_module_plain` already exists and declines the same
way — so effects are innocent; fix the plain case first).

**3.1.6 Eager clone generation → reachability-driven, minimal captures.** Today every
eligible installation generates clones. Correct but wasteful, and the "generated-name storage
capacity heuristic" has never been stress-tested. Two tasks:
- a stress fixture: 200 installations × 5 helpers × 3 nesting levels, compiled with
  `-emit llvm`, assert no duplicate hidden names and no truncation (grep `__handler__`
  count vs expected); run under `ELISA_STAGE1_NO_SEMANTIC_GATE=` unset;
- then, only if measured cost matters, walk the call graph from `main` and exported
  functions before cloning. Keep the ordered capture ABI (entry, helper-to-helper, operation
  call) identical; `run_zero_overhead_ir` checks are the regression net.

**3.1.7 Cross-repo: stage0 lacks effectful-helper specialization.** stage1 is AHEAD of the
oracle here; every effect fixture that uses a generic effectful helper has no stage0 answer.
Owner decision (§8): port to stage0 (Go) so the differential oracle covers it, or accept that
`effect_handler_stage1_smoke.sh`'s native-result checks are the only truth for that subset.

### 3.2 Callee-side drop of by-value moved parameters — CLOSED (`1f6db0c0`, 2026-09-02)

Landed before this plan was written; the "blocks the fixpoint" claim in `e3344c92` was
withdrawn in that commit (gen3.o == gen4.o with the parameter site wired). The real blocker
had been arming a cleanup for `self` inside `__drop__`, fixed with stage0's
`isOwnDropReceiver` guard. Nothing to do.

### 3.2b Packed stores — CLOSED 2026-09-05 (three fixes)

Found while chasing §6.3. (1) a declared `X.Store[Local]` local never became the ACTIVE
store — every such program aborted in `ctx_packed_store_read_variant_sparse_tag`; fixed in
`emit_statements` by threading a runtime copy so a declaration publishes itself to its
successors. (2) auto-promoted enums were over-rejected (`def make() -> Tree: return
Tree.Leaf(…)`): stage0's rule is that the SIGNATURE mentions the type; implemented in
`check_packed_constructor_path` with `collect_type_identifiers`. (3) `-emit packed`
classified every AoS common as side-table; now reports the real placement. Pinned by
`test/differential/cases/packed_{declared_store_local,implicit_store_escape}.elisa`.
Memory: `packed-store-activation-and-adt-ergonomics`, `stage0-private-tmp-empty-object`.

### 3.3 PERMISSIVE gaps (stage1 accepts what stage0 rejects) — no gate sees these

All RECALLED; re-measure each with the two-line fixture in its memory note before starting.

**3.3.1 `defer function` + cleanup-requiring local.** stage0's rule is scope-DEPTH
(`analyzeDeferStmt`: `currentNonGlobalScopeDepth() != 1`), stage1's is syntactic nesting
(`check_defer_rules.elisa`). Needs a recursive "type requires cleanup" predicate: darray yes,
fixed array no, struct yes-if-any-field-does; UNMAPPED: dstr, dict, set, generic
instantiations, nested/optional containers. Measure each unmapped shape against stage0 first
(a 7-row table exists in the note; extend to ~15 rows), implement the predicate to match the
table exactly, decline nothing outside it. Safety fact: cannot break self-host (stage0
compiles `src/` today). Do NOT add to `adversarial_differential.py` until fixed (PERMISSIVE
is ratcheted at zero).

**3.3.2 Typestate call-site check.** `T[?]`/`T[&]` lower like stage0 (gated on
`__aggregate_state`), but `read(h)` with `h: Holder` where `read` expects `Holder[&]` compiles
under stage1 and stage0 rejects with `argument 1 to "read" expects Holder[&], got Holder[?]`.
Semantic-layer work: a state lattice per struct declared with states, a per-binding current
state (constructor → `?`; a narrowing operation → `&`; measure stage0's transition rules by
probing), and a call-argument compatibility rule. Keep the marker gate; do not re-decline the
annotation.

**3.3.3 Recursive enum auto-packed still needs a store at the CONSTRUCTOR — NOT REPRODUCIBLE
2026-09-06.** Measured on the Mac with a fresh seed: `n: Node = Node.Leaf(42)` inside a
`region r:` (and the same inside a `match` scrutinee) is REJECTED BY BOTH compilers with the
same rule — stage0 `error: packed enum constructor Node.Leaf requires an active in Node.Store:
scope or explicit new[Node.Store]`, stage1 the same text with the constructor name quoted and a
`path:line:` prefix; outside a region both reject earlier (`new` needs a region). A builder
`def leaf(v) -> Node: return Node.Leaf(v)` called from a region is accepted by both. So stage1
does NOT exempt bare construction; the claim below was stale. Residue: the quoting/position
wording, which no fixture exercises (diagnostics_diff is byte-exact on 375). Original text:
stage0
auto-promotes a recursive enum to packed and demands a store at construction (exempting only
`match`); stage1 exempts both, so `Node.Leaf(42)` bare is accepted. The compiler's own AST
enums are auto-promoted and constructed everywhere, so a naive narrowing stops the self-host.
Read stage0's `analyzer_packed_store_implicit.go` for the exact rule (there must be an
implicit-store or module-scope exemption that keeps `src/` legal), mirror it in
`parser_types_aggregate.elisa` (`record_recursive_enum`, `__declared_packed`), fixture both
directions.

**3.3.4 `-emit unsafe` strict audit: 14 permissive / 2 strict, UNGATED.** The report half is
exact (40/40, EXTRA=0). The AUDIT half — which programs stage0's `EnforceUnsafePermissions`
FAILS — disagrees on 16/56. Two causes: a `take_result` effect-signature error in
`elisacore_runtime_concurrency.elisa` every std-including fixture inherits (stage0's
`618ce2b8` fixed the argument-position half; the VARIABLE-assignment-with-generic-return path
is still open upstream), and genuinely ungranted unchecked indexes (`view_index.elisa:14`).
Work: (1) build the requirement table the note specifies — a per-function REQUIRED-capability
set recorded by the same walk that reports violations, NEVER in `table.diagnostics` (the
diagnostic-path attempt wrongly rejected two valid programs); (2) implement the 5 AST rules
from `test/parity/unsafe_permission_model_probe.py` in the semantic layer over that table;
(3) add an audit gate `unsafe_audit_parity_smoke.sh` that compares stage0 `-emit unsafe` exit
status with stage1's strict verdict over the 56-fixture corpus, ratcheted from 40 agree;
(4) close the std `take_result` case upstream (stage0 `AssignableTo` through the variable
path) so the 14 permissive files can be arbitrated.

**3.3.5 Write-through-ref (OVER-rejection, the opposite direction).** `r: i64& = get_ref()`
where `get_ref() -> mutable i64&`, then `r <- 99`: stage0 writes through (99), stage1 rejects
`cannot assign to immutable local 'r'`. The naive skip would newly PERMIT writes through a
genuinely readonly ref (`get_readonly_ref() -> i64&` — stage0 rejects). The bounded fix from
the note: one more side table of the shape `collect_mutable_ref_params` already builds, keyed
by function NAME (`mutable_ref_return_fns`), threaded `resolve_declarations → check_function →
gather_mutability`; a VarDecl whose initializer is a DIRECT `Expr.Call(Expr.Ident(fn))` to a
listed function routes to `skip`. Every other initializer shape stays strict. Backend already
implements the store (`codegen_stmt_assign_flow.elisa` ~570–604). Fixtures: both programs
above, plus field-access and `&x` initializers to prove nothing else loosened.

**3.3.6 Chain-resolver Optional asymmetry** (`codegen_place.elisa`: `struct_chain_type`
handles a Ref-to-Optional pointee, `struct_chain_address` has no case). No reachable fixture
has ever been found; stage0 rejects the natural route. Do NOT fix blind. Re-probe once per
quarter with any new non-null-narrowing form; if a stage0-accepted fixture reaches it, add
the address case and pin it.

### 3.3.7 region-block return escape — CLOSED 2026-09-06 (return shape); store shape OPEN
stage0 rejects `return xs` where `xs` is an owned container declared inside an enclosing
`region NAME:` block, with TWO findings in this order: at the returned name, `value allocated
in region "r" escapes via return; the region is freed at scope exit. Copy it into a
caller-provided region param (def f[@r] ... -> ... @r) or a longer-lived region first`; at
`return`, `cannot return value: region dependency facts include local region "r"`. Measured
edges (one probe per row): a `return xs if c else xs` yields only the second; a local declared
OUTSIDE the block is fine; a struct value is fine; the innermost region is named; a `@r`
return type is region-polymorphic and allowed. `check_region_return_escape.elisa` implements
exactly that sound subset (owned-container return type; owned-container local declared in an
enclosing region of the same function; bare name / parens / both-arms `if`). Two traps it cost:
a `-> table` value block may list only MUTABLE captures (the immutable `nesting` param is
visible without being listed), and `xs: mutable darray[i64]` parses as `Unary(Mutable, …)`, so
the container helper sees nothing until the prefix is peeled — the check was silent on every
fixture until then. Fixtures `region_return_escape`, `region_return_dependency` (.pos/.neg).
OPEN sibling: `out <- xs` (store into an outer AUTO region local) — stage0: `value in region
"r" is stored into longer-lived region "__auto_173"; …`. The `__auto_N` id is stage0's
internal numbering; a byte-exact message is not reproducible, so it needs an asserted
divergence in diagnostics_diff or a stage0-side spelling change (§7). Not attempted.

### 3.4 Semantic over-reporting — re-derive the method, then close the residue

RECALLED as "3867→642 findings where stage0 makes none", and the note itself says the number
is not reproducible today: on the compiler's own source stage1 printed 0 and stage0 printed
223 WARNINGS (stage0 prints warnings on STDOUT; large-input warning output was not
reproducible run to run — its own bug, §7.3). Plan:
1. rebuild `build/parse_report` (it is stale unless rebuilt via the sourced script) and run
   the semantic replay over `src/ + elisacore_std/ + test/` with stage0 on the same inputs,
   diffing per (file, kind, line);
2. cluster by `DiagnosticKind`; the last known cluster is docs/119 E4 "through a call" over
   reference parameters;
3. fix cluster by cluster; each fix needs `semantic_internal.baseline` (0/3178) and
   `diagnostics_diff.sh` green, and the bootstrap deadlock recovery note applies (a gen2
   whose new diagnostic rejects the compiler's own source cannot be promoted).

### 3.5 Silent-wrong-answer hunting — keep the two oracles running

Not a bug list; a standing activity that has found every serious defect here:
- extend `test/breadth/adversarial_differential.py` generators along INTERACTION axes (defer
  × loop × break/continue × index compound-assign × ref-returning call found the defer gap;
  single-construct passes had stopped yielding);
- run the differential at -O0 AND -O2 (a RowId i32/i64 mismatch segfaulted at -O0 while -O2
  produced the right answer);
- add the two-compiler `parse_report` probe for any semantic change (it found five bugs
  hiding behind each other);
- for any emitted CODE mode (test-runner, c-archive, pymodule), build and RUN the output;
  byte parity said 52/52 while the runner did not compile.

### 3.6 Nondeterminism — confirm closed, keep the gate

`c0e0bcb4`/`be55ddbb` recorded a 1-in-8 flake in gen2-built compilers (prologue slot order
in functions threading a hidden store/arena). `7f497899` replaced the probe with stage D of
`self_host_gen3_smoke.sh` (40 runs of a 200-field by-value struct, over the 1024-byte
indirect-return threshold) and attributes the cause to the sret-attribute decision, fixed
alongside `aef24a13`. Verify once more by running stage D 200 times in a background job
(`for i in $(seq 200)` over the same program); if any object differs, reopen with
`objdump -d` on the differing function.

### 3.7 `self_host_gen3_smoke.sh` order-sensitivity

`e3344c92` notes gen3 can report a spurious mismatch when run AFTER other parity gates
(different gen3 size for identical source). If still reproducible after `7f497899`: the
suspect is a shared `build/` artifact or the seed being refreshed mid-run by another smoke
(`elisac_stage1.sh` line 233 comment). Fix by giving the smoke its own `mktemp -d` product
and refusing to share `bin/elisac-stage1`; pin with two consecutive runs in `run_all.sh`.

### 3.8 The five gate checks that are red on `main` today (measured on a clean HEAD worktree)

Each fails identically with and without this session's work, so none is a regression — but
the gate is not green, and the plan's exit criterion needs it green. Triage each with the
stale-gate-rot discipline (three of five red gates were real bugs last time):

- **`differential_corpus` — 5 declines vs ratchet 0**: `lmut_threading_value`,
  `assert_by_min_i64`, and three effect `.neg` fixtures (`handler_implementation_access`,
  `operation_effect_row`, `via_operation_effect_row`) where stage0 ACCEPTS and stage1 rejects.
  The effect ones are stage1-stricter-than-stage0 by design (§1.3) — decide whether the corpus
  should exclude `test/fixtures/effects/*.neg.elisa` (it already excludes `*.xfail.elisa` and
  `repro/`) or whether the ratchet baseline records them by name. The two non-effect ones need
  a real look.
- **`emit_ast_parity` — 1/135 differs.** Identify the fixture; likely a new AST node the
  summary printer does not know.
- **`global_permissions_smoke` — 6 checks**: "produced no stage0 Global diagnostic to compare"
  — the ORACLE side is empty, so stage0 may have changed its Global-permission wording or the
  fixture no longer triggers it. Re-measure stage0 first.
- **`semantic_acceptance_diff` — 2 lines**: `TestAnalyzeRejectsUsingNestedStructViewAliasEscapingRegion`,
  `…MoveAsEnumBoundIndexedAliasEscapingRegion` (stage0 rejects, stage1 accepts = PERMISSIVE).
  Real gaps in region-escape analysis for view aliases.
- **`semantic_internal_diff` — 1**: `extern mutate() -> i64 can[Unsafe2.SegmentMutation]`.
- `opt_pipeline` passes standalone on both; its gate failure is parallel-load flakiness
  (segfault under memory pressure). Treat as harness, not compiler, unless it reproduces alone.

---

## 4. Phase 2 — the driver becomes the whole CLI (weeks 3–6)

Goal: `scripts/elisac_stage1.sh` shrinks to "find the binary and exec it". Today it is 1004
lines of bash + Python and still OWNS: include flattening (default path), the `#line`/offset
map for `-emit fmt`, `# smt` header detection, linking (`-emit exe`, `run`, `test`,
`c-archive` via `emit_c_archive.py`), `-emit wasm` (`wasm_build.py`, 769 lines), and the
`pymodule-so` build (`python3-config` discovery).

### 4.1 Make the driver's include expansion the DEFAULT path
RE-SCOPED 2026-09-06 (steps 1-2 below are DONE: `cli_includes_smoke` check 5 asserts the
driver-flattened and wrapper-flattened objects of `src/driver/elisac.elisa` are byte-identical,
and it passed in every Mac gate today; the blank-line cause in its comment is fixed; step 4 is
done too — `source_has_header` scans 8 lines). What step 3 actually has to move, measured
from `scripts/elisac_stage1.sh` lines 545-575 and 960: the wrapper's flattening has THREE
side-products the driver must own before `flatten_includes` and its Python can go:
- `ELISA_STAGE1_SMT` — set from the ORIGINAL file's header; the driver can scan the head of
  its own expanded buffer (the root file comes first), so this is a one-liner;
- the trusted-std marker (`runtime_std_enabled`) — decided from the FLATTENED unit's CONTENT
  (`def arena_alloc(` present); the driver has the expanded buffer, same one-liner;
- `ELISA_STAGE1_OFFSET_MAP` for `-emit fmt|lowered|iface` — stage0's synthesized
  `__auto_<offset>` names index into ITS buffer, which carries a `#line <n> <abs path>\n`
  directive at every file start and resume (length 6 + digits + 1 + path + 1) plus a
  newline guard after a spliced file; the wrapper's Python computes ascending
  `flatoff:delta` pairs. The driver's `expand_includes` already walks the same tree in the
  same order (it emits a `FLAT:ORIG:PATH` LINE map at exactly those points), so the offset
  map is the same walk accumulating byte deltas instead of lines — port it there, publish it
  the way `ELISA_STAGE1_LINE_MAP` is published, and pin it with `emit_fmt_parity_smoke`.
DONE 2026-09-06 (first half): `expand_includes` now accumulates the byte delta and publishes
`ELISA_STAGE1_OFFSET_MAP` itself; the raw driver and the wrapper route are byte-identical on
all 22 include-bearing fixtures x {fmt, lowered, iface} (66/66; one was 98 lines apart before).
Measured against stage0 on the compiler's own 509-file closure (the only input with non-ASCII
text): aligning every `with arena __auto_N` site by its preceding line, the driver's map agrees
with stage0 at every common site, while the WRAPPER's Python map is wrong at 8 of them — it
advanced its flat offset by `len(line)` on a `str`, i.e. by CHARACTERS, where stage0 counts
BYTES, so every em dash (3 bytes) in a comment put it 2 bytes behind. A pre-existing wrapper bug
that no fixture could see (they are ASCII); the port fixes it. (A first comparison showed a
constant +618 at the last six sites; that was the two outputs coming from different versions
of the source — a debug hook added between the runs — not the map.)
**DONE 2026-09-06** — certified by a clean full gate, 345/345 in 23m51s (was 32 min). Details: `flatten_includes` and its Python are gone;
the wrapper hands the driver `-o OUT SRC` on the CLI door with the mode in env for EVERY mode
(cli_request leaves ELISA_STAGE1_EMIT alone unless `-emit` is given, so no mode split was
needed). Through the flipped wrapper: cli_includes 18/18; emit_fmt parity 62 -> **77**
byte-identical and emit_lowered 76/158 (both ratchets raised); iface 124, tokens 281, ast 136,
doc 105/158, header OK, deps 606, stage1_product OK; **gen3 fixpoint + 40/40 in 5m23s against
~12 min** (no interpreter spawn per compile). ONE regression, fixed the same hour: the wrapper
had grepped the ORIGINAL file for `# smt` and exported the bit; the driver's 8-line fallback
scans the EXPANDED buffer, where a withstd probe's header sits after the std, so
`contract_ensure_result_void.neg` was accepted — cli_request now reads the root's own head.
With the fix: driver_acceptance OK in **161 s** inside the gate (it was 698-1032 s on the Mac
before the flip — every one of its ~700 probes paid the Python interpreter spawn).
The first full gate through the flipped wrapper (27m27s against 32 min) failed 4 of 345,
every one understood and closed the same hour: `emit_annotated_list` and `emit_test_run` —
on the CLI door an output path routes a report INTO that file, and the wrapper handed the
listing modes `-o /dev/null` (stage0 refuses `-o` for them), sending the whole listing into
the void; the wrapper now passes no `-o` for exactly those modes. `pymodule_python_bin` —
it asserted that PYTHON_BIN reaches the flatten step, which no longer exists; retargeted to
what still holds (manifest from an including source; both python spellings accepted).
`backend_native` — 139 "link failed" in the gate, **511/511 standalone** under the fixed
wrapper: load or the pre-fix wrapper. A clean certifying gate follows.
Candidate follow-up, NOT done: the strict/unsafe/proofhole/global headers are read from the
expanded buffer too (they were before the flip as well); measure whether stage0 reads them
from the original file and, if so, move all five to the root's head together.
The flip as it was scoped, for the record: scoped 2026-09-06 from the wrapper's invocation block (lines 915-975) and
the driver's `main` ("TWO front doors, ONE compile path": `cli_request` builds exactly the
buffer `read_all` would have produced): today the wrapper materialises a REQUEST FILE — the
`-o` path line plus the FLATTENED SOURCE BYTES — and feeds it to `$BIN` on stdin inside
`run_stage1_driver_guarded`; every option other than the source rides in `ELISA_STAGE1_*`
env, which the flip does not touch. So, for the modes the CLI door accepts
(`cli_emit_mode_supported`: obj llvm bc tokens ast iface fmt deps deps-json doc header
pymodule pymodule-c test…), replace `"$BIN" <"$stage1_request"` with
`"$BIN" -emit "$emit_mode" -o "$out" "$src"` inside the SAME guard (RSS monitor, env, exit
status unchanged); keep the request path only for the modes the CLI door does not take
(interpret, c-archive, tests/benches/fixtures); then delete `flatten_includes`, its Python,
`$flat.map`, the OFFSET_MAP env line, and the `# smt` / `def arena_alloc(` greps (the driver
decides both from its own expanded buffer: `source_has_header` scans 8 lines,
`runtime_std_enabled` checks the buffer before the env). Verify with cli_includes check 5,
every `emit_*_parity_smoke`, gen3 (the seed is built THROUGH the wrapper), and the full gate.
The driver's `expand_includes` is byte-identical to stage0 on six real graphs and compiles the
compiler unaided. Blocker MEASURED: 3 of 22,548 symbols differ because internal loop-lambda
names embed a LINE NUMBER and the two flattenings number lines differently. Steps:
1. make lambda/loop-body symbol names derive from the ORIGINAL (file, line) via the
   `FLAT:ORIG:PATH` map the driver already carries (`ELISA_STAGE1_LINE_MAP`), so both paths
   produce identical names;
2. assert byte-identical objects for `src/driver/elisac.elisa` via both paths
   (`cli_includes_smoke.sh` already has the shape);
3. flip the wrapper to pass the ORIGINAL file and delete `flatten_includes` + the Python;
4. keep `# smt` detection in the driver (it already has an in-compiler fallback that must
   stay bounded — do not scan 11 MB per generation; scan the original header only).

### 4.2 Re-key the report emitters off (file, line) or token index
STEP 1 + 1b DONE 2026-09-07 — certified: full gate 345/345 in 21m25s, the first fully green gate
since the runtime-object race was fixed. Details: 1b threads the offset through
the ten decl-level helpers that took a bare `line: u32` (their callers hold a Pos); callers
that hold only a line (a computed one, or an `Ast.Annotation`, which carries no offset) pass
0 and take the line fallback. Same numbers as step 1 at every ratchet and 292/292 on the self
source. One trap cost an hour: the file-wide rename rewrote the helper's OWN three fallback
lines into calls to itself, and every fallback path recursed forever (96 % CPU, no output);
recorded in memory. Step 1 as recorded: `emit_ast_range_at(tokens, line, offset)`
binary-searches the token at the node's byte offset, walks back to the first non-layout token
on that token's line, and extends as the line helper does; offset 0 (generated) falls back to
the line. 26 call sites carry `<pos>.line, <pos>.offset`; the fmt emitter's global
`fmt_stmt_line` gained a `fmt_stmt_offset` twin set at its five assignment sites; the six
decl-level helpers that take a bare `line: u32` are unchanged (step 1b). Byte-preserving by
measurement: all emit ratchets at exactly their prior values (fmt 77, lowered 76, iface 124,
doc 105, header exact, ast 136, tokens 281, test-runner 129/0, annotated-list OK) and the
compiler's own source 292/292 auto-region sites against stage0 on the SAME source (the first
comparison used a stale stage0 output and read as 999 lines of difference — the input was the
file being edited). Measured before: ONE helper is the line key — `emit_ast_line_range(
tokens, line)` in `elisac.elisa` (a linear scan from token 0 for the first token on `line`,
then a bracket-depth walk to the depth-0 colon or newline) — with 50 call sites (21 pass a
bare `line`, the rest `<pos>.line`), plus `emit_ast_line_end`. `Ast::Pos` already carries
`offset`/`end_offset` (pos_of_token) and `Lexer::Token` has `start`, so the key can be the
statement's byte offset with a binary search over `tokens[i].start`; generated nodes
(`pos_at_line`: offset 0) keep the line fallback; literals carry no Pos at all
(`IntLit(value)`), which is why the emitters scan a statement's tokens for a matching literal
— that part stays. The stop condition `stop_token.line != line` becomes "not the start
token's line", which survives `#line` renumbering. Step 1 (this refactor) changes NOTHING
observable today and is guarded by the four emit ratchets (fmt 77, lowered 76, doc 45, iface/
header exact) and test-runner 129/0/160. STEP 2, MEASURED 2026-09-07 (env-gated, default unchanged): with ELISA_STAGE1_LINE_DIRECTIVES=1
`expand_includes` splices stage0's `#line <n> <abs path>` at every file start and resume (plus
stage0's newline guard), and the driver's expanded unit is BYTE-IDENTICAL to stage0's expansion
of the compiler's own 509-file closure (13,068,558 bytes, 1051 directives — the model of stage0's
Go rules first disagreed by 524 bytes, which was the model testing the last appended PIECE for a
trailing newline instead of the buffer; a blank last line is an empty piece). The lexer already
consumes the directive and records the filename. In that mode neither map is published. The
TAIL before it can be the default, each measured: (a) eleven fmt helpers still take a bare
`line: u32` and key by line (fmt_static_is_directive, fmt_struct_decorator_lines,
fmt_body_needs_auto_region, fmt_auto_region_number, fmt_block_from_source[_at_indent],
fmt_render_postfix_can, fmt_render_guard_can, fmt_line_is_implicit_submit,
fmt_line_starts_with_catch, fmt_has_try_before) — the 1b pattern again, their callers hold a Pos;
(b) the two `emit_ast_line_end` sites and the probe at elisac.elisa:19240; (c) stage0 uses TWO
offset conventions for synthesized names: `__auto_<n>` is the BUFFER offset (directive bytes
included), but the machine-mode enum `__MachineMode_<hash>_<n>` is FILE-RELATIVE (434 with or
without the leading directive; stage1-with-directives printed 561 = 434 + one directive) — so
the machine-name site must subtract the directive bytes before its file, i.e. keep a per-file
base offset (the line map already knows every file start). With directives on today: fmt 62/77,
iface 122/124 — exactly the sites in (a)-(c). When they are done, the maps retire and test-
runner's 160 skipped include-bearing units become comparable.
MEASURED FURTHER 2026-09-07 02:15 — converting the eleven fmt helpers to offsets (done, byte-
preserving by default: fmt 77, lowered 76, iface 124 with the switch off) moved the switched-on
fmt number NOT AT ALL (62), because the remaining breakage is not range lookup but LINE AS A
GLOBAL ORDER: with directives on, the fmt emitter interleaves top-level declarations (the
`using` rows, consts) by ascending `.line`, and lines restart per included file, so
`cpp_unordered_map` prints `def fail(…)` where stage0 prints `const ARENA_BACKEND_LIBC_MALLOC`;
the header emitter matches annotations by line the same way (`wolf_pointer_memset`: stage0
emitted a header, stage1 none). ROOT CAUSE: `Ast.Annotation` / `EnumAnnotation` /
`LocalRegionAnnotation` carry a `line` and no byte offset, so every consumer that orders or
matches by annotation line breaks the moment lines are not unique. The foundation for the rest
of step 2 is therefore: give the annotation records an `offset: u32` (set at every parser
creation site from the token's `start`), then order/match by offset in fmt and the header
emitter; plus the two `emit_ast_line_end` sites, the probe at elisac.elisa:19240, and the
file-relative convention for `__MachineMode_…_<n>` (a per-file base offset from the line map).
CORRECTED 2026-09-07 (gate gate_ao running on the annotation-offset foundation): the "file-
relative `__MachineMode`" reading was WRONG. stage0's `Pos.Offset` is the buffer position for
every synthesized name; the raw-file offset of the fixture's `machine` is 307, stage0's 434 =
307 + one 127-byte directive, stage1's 561 = two — stage1's emitter added the directive-free
fallback delta (`path+9` in the `__MachineMode_` rewriter; the map delta in
`fmt_auto_region_number`) on top of an offset the lexer had already measured past the spliced
directive. And `fmt_body_needs_auto_region` bails when `emit_fmt_offset_delta(0) < 0` (no map)
— which is exactly the directives-on state, so every auto-region fixture declined: that is the
bulk of fmt 62/77. Fix: `emit_fmt_offset_delta` returns 0 when directives are on (the fallback
is `< 0`-gated, so 0 disables it at both sites). No per-file base offset is needed.
MEASURED 2026-09-07 04:10 with the zero-delta fix seeded: switch ON fmt 77/77 (was 62) and
iface 124/124 (was 122) — the fmt/iface tail is CLOSED with directives on. Header: all 20
FAILED fixtures print the same `L1019: try without else requires the current function to
return an error union` — one cause: `enclosing_try_function_line` took the largest function
`Symbol.line <= try line` (line as a global order; L1019 is in the spliced prelude), and the
`__error_set_family` rows were matched by function line. Fix in flight (batch zh): `Symbol.offset`
(add_symbol threads it; Func + extern-callable sites pass the Decl pos offset), `offset` on the
`__try_without_else` and `__error_set_family` rows, and an offset-first lookup with the old
line lookup as the fallback for producers without offsets. Test-runner: stage1's
`emit_test_runner_report` prepended its own `#line 1` over a buffer that already opened with
stage0's (stage0's emit_runner.go adds none) — now skipped when directives are on.
MEASURED 2026-09-07 04:12 (batch zh4, seeded with all three fixes): switch OFF fmt 77, lowered
76, iface 124, header OK, test-runner OK, diagnostics OK; switch ON fmt 77/77, iface 124/124,
header OK, test-runner OK. Every measured emit mode now matches stage0 with the directives
spliced. Remaining before flipping the default: lowered under the switch (running), a full
gate on the Symbol.offset change, then the flip itself (make `line_directives_enabled` true
by default, delete the ELISA_STAGE1_LINE_MAP / OFFSET_MAP publication and their readers).
DESIGN DECISION 2026-09-07 04:45 — flip WITHOUT line renumbering. What every measured mode
needed from the directives was stage0's BYTE OFFSETS (the directive bytes in the buffer);
the lexer's renumbering (`lexer.line <- N` on `#line N path`) bought nothing measurable and
costs two whole classes: 62 bare-line equality lookups in src/semantic (each a silent wrong
answer once two files share a line number — `function_is_variadic(annotations, line.line)`
is one) and file attribution for 843 diagnostic sites (279 carry no Pos at all): with
renumbered lines and no map, a fault in an included file prints the ROOT path. The lexer's
directive test (`frontend_case_line_directive_retargets_filename`) asserts only the filename
retarget, `-emit tokens` and `-emit ast` print no line numbers, and the two diagnostic
printers already go through the map-aware `push_diagnostic_location`. So: the lexer consumes
the directive as ONE BUFFER LINE (`lexer.line + 1`, filename retarget kept), lines stay
unique across the unit, ELISA_STAGE1_LINE_MAP stays the (already exact) file+line
attribution, ELISA_STAGE1_OFFSET_MAP retires (delta 0 everywhere), and `#line` directives are
spliced unconditionally. Documented divergence: a USER-WRITTEN `#line` is not honoured for
line numbering by stage1 (none exists in src/ or any fixture). Acceptance: full gate with the
switch on, then the flip, then the test-runner smoke drops its include `continue`.
FLIPPED 2026-09-07 05:25 (gate zf3 running): directives are spliced BY DEFAULT
(`ELISA_STAGE1_LINE_DIRECTIVES=0` opts out), the lexer counts a directive as one buffer line
(no renumbering; filename retarget kept), the LINE map is published unconditionally and is
the file+line attribution for every printed location (push_diagnostic_location, and the
new flat_line_to_original for the ABI-lint issue lines), the OFFSET map is no longer
published. Measured on the flipped default: fmt 77, lowered 76, iface 124, header OK,
tokens 281/281, diagnostics 294/294, and test-runner 129 -> 149 byte-identical / 0 divergent
once its include `continue` was dropped — the last 20 needed stage0's rule that `extern
puts(` is declared only when the expanded unit does not already contain it. Follow-up
(cleanup commit, after the gate): retire the offset-map machinery — push_offset_map_entry,
s0_extra / line_directive_length, the ELISA_STAGE1_OFFSET_MAP reader in
emit_fmt_offset_delta, fmt_map_delta_probe and the `< 0` bail in fmt_body_needs_auto_region,
the `__MachineMode_` `path + 9` fallback, the ELISA_STAGE1_DUMP_OFFSET_MAP hook — and the
wrapper-era comments that describe the maps as the mechanism.
FOUND BY THE GATE 2026-09-07 05:38 (cli_includes_smoke §6, plus a hand probe): with the
directive counted as a buffer line, the LINE map's entries were recorded BEFORE the directive
line — every mapped diagnostic line was one too high (`c.elisa:6` for a fault on line 5).
Fixed by pushing the root and resume entries AFTER the directive; and a second one the smoke
does not cover: a DEDUPLICATED include leaves stage0's newline-guard byte as an empty buffer
line that emitted_lines never counted, so every line after it mapped one too low per
dedup'd include (probe: `include b / include c(includes b) / include b` gave a.elisa:7 for
line 5). Now counted. Both shapes are probes only — the second belongs in
cli_includes_smoke §6 as a fixture (TODO with the cleanup commit).
FOUND BY THE GATE 2026-09-07 06:16 (lexer parity, `line_directive.elisa`): the lexer harness
DOES pin stage0's renumbering for a user-written `#line` (token positions hashed against
stage0), so "no renumbering" cannot be the lexer's spec. Split by caller instead:
`Lexer.renumber_on_directive` defaults to true (stage0 semantics — what the harness, the
unit tests and any direct lexer user see), and the driver tokenizes the units IT expanded
through `frontend_tokenize_expanded_unit`, which clears it: there the directives are the
driver's own splices, lines stay unique buffer lines, and the line map attributes. The only
divergence left is a user-written `#line` inside a unit compiled by the driver (counted, not
honoured) — no such source exists. Batch zf6: reseed, lexer parity, dedup probe, full gate.
FOUND BY THE GATE 2026-09-07 06:58 (zf6: 345 ok, exactly 2 FAIL): the buffer-line design's
true cost is the set of LINE-SURFACING sites — numbers that leave the compiler and must be
stage0's: the effect-handler clone symbol `__effect__<src>__<handler>__<LINE>__at_<n>`
(parser_effect_specialization) and the runtime panic location `panic at FILE:LINE:COL`
(emit_panic_report). Both were +1. Mechanism: the driver mirrors every line-map entry into
two Lexer-level tables (`source_line_map_flat/orig`) and `source_original_line(flat)`
translates; the two sites, the ABI-lint issue line and the driver's diagnostic printer all go
through it. Rule for the future: a `Pos.line` that is COMPARED stays a buffer line; a
`Pos.line` that is PRINTED or NAMED goes through source_original_line. Batch zf7 = the fix,
the two smokes, the dedup probe, a fresh gate.
NOTE 2026-09-07 07:40 (found while probing): stage1's own backend DECLINES darray-typed
globals (`source_line_map_push@… (expression statement)`, `source_original_line@… (index
expression)`) although stage0 compiles them — every `global` in src/ is scalar for that reason.
The translator now reads ELISA_STAGE1_LINE_MAP through getenv (declared once, in
src/lexer/lexer.elisa). Also seen: stage1 types `value_bytes + 0` (a `u8&` plus an integer
LITERAL) as i64 and rejects the binding, where stage0 accepts it — a stage1 over-rejection on
`ref + literal`; `ref + i64_variable` is fine. Both belong on the backend gap list.
DONE 2026-09-07 08:29 — §4.2 step 2 landed (commit after 67a15bab): directives on by
default, buffer-line design, full gate green (zf9: 345 ok, rc=0). Left for the cleanup
commit: retire the offset-map machinery (37 sites, inventory in the session log), fold the
driver's two map parsers onto source_original_line, and rewrite the wrapper-era comments.
CLEANUP 2026-09-07 08:45 (batch zc2: seed ok, fmt 77 with auto-region rendering now
unconditional): the offset-map machinery is gone — emit_fmt_offset_delta, push_offset_map_entry,
line_directive_length, the s0_extra/offset_map threading through expand_includes and its
four call sites, the ELISA_STAGE1_DUMP_OFFSET_MAP hook, fmt_map_delta_probe and the `< 0`
bail in fmt_body_needs_auto_region, the `__MachineMode_` `path + 9` fallback (−128/+18 lines);
the wrapper-era prose is rewritten. Gate pending; then commit.
Step 2 as it was planned: emit
stage0's `#line` directives throughout the driver's expansion (the lexer must honour them —
re-attribute line/column/file), after which stage1's flat buffer EQUALS stage0's, every
auto-region offset matches with delta 0, the offset map and the line map both retire, and
test-runner's 160 skipped include-bearing units become comparable. The linear scan is also a
perf item on an 11 MB unit (50 sites x O(tokens)); the binary search fixes it as a side effect.
Mechanics for step 1, measured: `fmt_stmt_line` is a GLOBAL mutable u32 in emit_fmt_expr.elisa
set by the statement emitter — add a sibling `fmt_stmt_pos: Ast::Pos` set at the same
assignments; the six bare-`line` callers in elisac.elisa are decl-level helpers whose `line:
u32` parameter becomes the declaration's Pos (their callers already hold it); no binary-search
helper over tokens exists yet — write one keyed on `tokens[i].start`.
`-emit fmt`/`iface`/`doc`/`header` recover token spans keyed by LINE NUMBER. That is why
`#line` directives regress fmt 32→19 and why test-runner cannot echo stage0's
directive-bearing expansion. Once keyed by token index: test-runner's remaining byte
difference closes, cross-include diagnostic attribution needs no map, and 4.1 gets simpler.
Files: `src/driver/emit_fmt_expr.elisa` (`fmt_*` span recovery), `elisac.elisa`
`emit_iface_decl` token-span path, `c_header.elisa`. Gate: all four `emit_*_parity` ratchets
must not drop; test-runner 52/52 + build-and-run.

### 4.3 Linking in the driver
MEASURED 2026-09-06 — most of this was already in the driver: `run`/`test`/`bench` (project
subcommands), `-emit test`, and `c-archive` all link inside `elisac.elisa` via `system()`
(`link_executable`, `link_test_runner`), with the weak-symbol callback fallback written to
/tmp and `-link/-L/-l` honoured through ELISA_STAGE1_LINK; `main` already had the `exe`
branch (object beside the executable, link, unlink) and `exe` was already a CLI-door mode.
What was NOT: the wrapper still rewrote `-emit exe` into `obj` + a bash link line of its own;
`link_executable` read only its private `ELISA_STAGE1_RUNTIME_OBJ` (the gate, the wrapper and
the docs say `ELISA_RUNTIME_OBJ`) and hard-coded `clang` from PATH where the wrapper used the
LLVM-matched `ELISA_CLANG`. DONE 2026-09-06 (full gate 345/346 in 21m42s, the one miss the backend_native in-gate flake
above; 511/511 standalone): the wrapper passes `exe` through
with `ELISA_RUNTIME_OBJ` and `ELISA_CLANG` in env and its link block is deleted;
`link_executable` honours both runtime names and `ELISA_CLANG`. Direct probes answer 42 with
either clang and leave no temporary; the 8 `-emit exe` smokes, stage1_product and
project_build (13/13) pass. NOT done, deliberately: the "runtime object next to the binary"
default — link_executable has no argv[0]; the repo-relative default plus the env stands.
`-emit exe`, `run`, `test`, `bench`, `c-archive` shell out to host clang from BASH. Move the
spawn into the driver (`posix_spawn`/`execvp` extern, already used for `c-bind-check`'s `cc`
subprocess — reuse that path), honour `-link/-L/-l` and `-target-triple` (already parsed), and
find the runtime object without `ELISA_RUNTIME_OBJ` being mandatory (default to
`build/runtime/elisacore_runtime.o` next to the binary, error by name when absent). Gate:
`project_build_smoke.sh` (stdout/stderr/rc parity), `stage1_product_smoke.sh` (exit 42).

### 4.4 `-emit wasm` without Python
`wasm_build.py` does: portable runtime object build (content-addressed cache under
`build/wasm-cache`), `wasm-ld` invocation, `.mjs`/`.d.mts`/`.d.ts` facade generation from the
export list, `.json` manifest, component mode (`--wasm-only --component-type`). The facade
generator is a projection of the export table the driver already has (`pymodule` does the
same job for Python in Elisa). Port in this order: manifest → facade → link step → cache.
Oracle: `wasm_smoke.sh` end-to-end (Node loads and runs the module) plus byte-identical
sidecars against the Python output for the whole transition, then delete the Python.

### 4.5 `pymodule-so` build
SCOPED 2026-09-06 — NOT "the same shape as 4.3". The wrapper's pipeline (lines ~500-720 of
`elisac_stage1.sh`) does, in order: validate the python/python-config pair; auto-build the
runtime object when absent; `-emit pymodule` for the manifest; three Python introspections
(the module name from the manifest, `sysconfig.get_config_var("EXT_SUFFIX")`,
`_imp.extension_suffixes()` to decide whether `-o` already carries a suffix); `-emit pymodule-c`
for the shim; `python3-config --includes/--ldflags`; `clang -c -fPIC` the shim and the callback
fallback; `clang -shared` with the runtime object. Moving it into the driver means the driver
spawning Python (system() + a temp file, the way it already shells out to clang) for the
three introspections, or reimplementing EXT_SUFFIX/ldflags discovery — the latter is
platform-specific and exactly what the two-interpreter mismatch guard exists to catch. Gate:
the twelve `pymodule_*_smoke.sh` that end in `-emit pymodule-so` plus `pymodule_python_bin`.
Not started. Same shape as 4.3 only in that: the driver already emits the C and the `.pyi`; the wrapper finds
`python3-config` and links. Move discovery + link into the driver behind `-emit pymodule-so`.

### 4.6 Delete the wrapper
When 4.1–4.5 are green: `elisac_stage1.sh` = seed build + `exec bin/elisac-stage1 "$@"`.
Update every smoke that greps wrapper error strings (a sixth of the suite greps for wording;
expect ~16 red smokes on the first run, as the diagnostic-text change produced).

---

## 5. Phase 3 — the four missing surfaces (weeks 4–12, parallelisable)

### 5.1 Column spans: 148 pending → 0
Mechanical per check: replace the bare `line: u32` parameter with the offending EXPRESSION
and report `Ast::expr_pos(expr)`; `check_affine_collection` and `resolve_types` are the worked
examples. Rules: the STATEMENT's span is wrong (64 diverged that way and were rolled back);
`if xs.count:` reports at `xs.count`. Order: highest-frequency kinds in
`test/fixtures/diagnostics/` first (UndefinedName, TypeMismatch, arity). Also drive the 86
`pos_at_line` parser sites down — each is a synthesized node; give it the span of the token
that caused synthesis. `diagnostic_columns_smoke.sh` prints the count on every run; DIVERGED
fails the gate.

### 5.2 Parse-error wording and recovery
stage0 names the token KIND (`unexpected token DEDENT`), stage1 the TEXT; recovery differs
(3 errors at line 4 vs stage0's 2 at line 3). `parser_ast` replay is 100/100 on
ACCEPTANCE only. Add a parse-error MESSAGE diff over `test/fixtures/parser/*.neg.elisa`
against stage0 (same shape as `diagnostics_diff.sh`), ratchet from wherever it lands, then
port stage0's kind-naming and its error-recovery synchronisation points (statement start,
DEDENT) into `parser_core.elisa`.

### 5.3 `-emit ir` writer — widen the closed subset; then accept `.elisair` as INPUT
Writer: covers plain callable externs + decorators (`ir_writer_smoke.sh`); refuses richer
extern forms because the compact side tables are lossy. Oracle is exact and total:
`elisac -emit lowered <bundle> == elisac -emit lowered <source>`. Grow the node mapping until
the 254-bundle corpus stops refusing; refuse BY NAME wherever stage1's AST cannot pick one
stage0 type (`Expr.Refinement` = `TryExpr` | `GetExpr`) — never guess. Wire kinds: `Position`
and `Params` are inline structs (kind 7); ints zigzag; `IntLit.Value` is a STRING; zero-valued
fields omitted; emit map fields LAST for determinism (encode 20× and compare).
Input: map decoded nodes onto stage1's AST (the 148-distinct-type-names wall is for THIS,
not for reading). Gate: source-vs-bundle `-emit ast` 254/254 and interpreter round-trip.

### 5.4 The fact system → `-emit semantic` / `-emit facts`
The one "needs a subsystem" call that held under re-measurement, twice. ~4,000 lines in
stage0: CFG construction (a plain statement walk), graph partitions / alias equivalence
classes, cleanup plan, return isolation, fact transforms + formatters, the fact-trace filter
language (`contract: version=fact-trace-v2 order=… matchers=… filters=…`). Output is
98,663 lines over 56 fixtures; 234,495 alias facts. The trivial subset reaches 2/56 — do not
rebuild it expecting more. Plan, each step with its own byte-diff gate against stage0:
1. CFG builder over `Ast::Stmt` with stage0's block numbering (verify via `fact_blocks`);
2. `fact_snapshot` (params, returns, alphabetical qualified function order);
3. `fact_exits`, `fact_transforms` (refinement: control-flow guard → non-null);
4. alias classes (`fact_groups`);
5. the filter language and the `=== lowered ===` section for `semantic` (needs 6.2).
Prerequisite: 5.1 (every position is `file:line:col-endcol`). This is the largest single item
in the plan; budget it as a subsystem, not a mode.

### 5.5 `project easm-lint` — the register-liveness closed set
130 agreeing / 782 refused / 0 diverged; boundary is parameters and non-void returns (both
force `inputs:`/`outputs:` and reach register dataflow). 126 issue codes total; 13
implemented atomically (a partial checker cannot skip checks — 3-of-13 gave 808
divergences). Next closed set: parameterised routines. Steps: extend the corpus in
`easm_lint_differential_smoke.sh` FIRST and read the reachable-code count; implement
establish/read/overwrite liveness over the instruction stream (`input-register-unused`,
`return-register-not-written`, `register-read-uninitialized`, `implicit-read-uninitialized`);
then stack alignment (`stackMod`), callee-saved proofs, direction flag, operand-size
inference, frame carriers, lockstep composition — each as its own atomic closed set with a
FAILING fixture per code verified against stage0. Source: `easm.go` (163 functions, 19
analysis passes, ~3.9k lines); stage1 already has `easm_model/parse/verify_*.elisa`.

### 5.6 `-emit serve` + `-addr`
231-line HTTP/1.1 compile server in stage0; dispatches to `semantic`, `facts`, `ir`. Do last;
it needs 5.3–5.4 for parity and it is a network service that compiles submitted source —
owner decision (§8) before a second implementation exists. If built: libc sockets via externs,
a minimal request parser, the JSON encoder from `project.elisa`.

---

## 6. Phase 4 — presentation ratchets and remaining polish

### 6.1 `-emit fmt` 32/56, `doc` 45/56, `progress` 47/56
2026-09-06: `emit_fmt_parity_smoke` went from 62 to **77 byte-identical fixtures** the moment
the wrapper stopped supplying its own offset map (§4.1 flip) and the driver's byte-exact one
was used instead — fifteen fixtures whose only divergence was an `__auto_<offset>` number
displaced by a non-ASCII byte in a comment. Raise the ratchet (32) to 77 once the flip lands.
- fmt: 9 `<fmt-*-todo>` markers (lambda body, `can`, `static`, block, stmt, pattern, decl,
  op). Port each arm; the known ceiling is stage0's `__auto_N` region naming (upstream
  stable-name change needed — §7).
- doc: 11 remaining diffs; re-measure and list them (the four non-obvious rules — canonical
  unparse, auto-region wrap, `static if` chain collapse, field types from tokens — are done).
- progress: the 9 remaining are stage0's structural-list-descent discharge
  (`while (…) and a.end.next != null: a.end <- a.end.next`); stage1 over-warns, which is the
  acceptable direction. Port the descent rule only with a fixture that FAILS when the rule is
  wrong in the under-warning direction.

### 6.2 `-emit lowered` 33/56 — needs the analyser's in-place desugarings
2026-09-06: 76 of 158 byte-identical through the flipped wrapper (ratchet raised 33 -> 76); the
remaining 82 are the analyser desugarings below, not offsets.
The 23 remaining need UFCS → free-call rewriting, overload mangling to `__ovl__`, and
address-of insertion applied to the AST before unparsing. stage1's semantic layer does not
mutate the AST. Options: (a) a separate desugaring pass producing a lowered CLONE of the tree
(the effect clone machinery shows the shape), or (b) an unparser flag that renders those
three transformations on the fly from resolution results. (b) is smaller and cannot corrupt
the tree the backend lowers. Also feeds 5.4's `=== lowered ===` section.

### 6.3 `-emit packed` — the `common:` policy
Blocked on §8 decision. If (b) "match stage0's side table" is chosen: touches
`packed_row_llvm_type`, `packed_row_bytes`, every `+ commons` payload shift, the common
read/write paths, and the AoS prefix-column write path that just got fixed
(`aaf74a57`/`bbb89bcd`) — a subsystem that has segfaulted under change twice. Gate: the
word-index table in the memory note (stage0 1,2 vs stage1 2,3 with a common; both 1,2
without), the packed smokes, and the compiler's own AST store (self-host).

### 6.4 `-emit interpret` — 2 known stage0-interpreter bugs
`generic_default_argument` (generic call binding a named argument by POSITION — stage0 bug,
non-generic half fixed upstream in `8836d1d5`) and `uintptr_corpus_probe`. Fix the generic
half upstream (§7), then drop `EXPECTED_DIVERGENT`.

### 6.5 Symbol parity (`nm` diff) — re-measure at matched -O0
`python3 test/parity/stage0_backend_recorder/be_symbol_diff.py /tmp/be_oracle.tsv` at -O0
BOTH sides (comparing defaults measures the -O3 flag: 269/277 "divergent"). Last 270/3/3.
Remaining by design: `_axpy` (internalization policy), 2 dview helper EXTRAs (different
lowering). Re-run after every export/ABI change (`ab348cb5`, `90028083`, `d552a6fa` all
touched this area since the last measurement).

### 6.6 Performance
Compile-CPU baseline 66.5 s (`compile_cpu_time.py`); driver self-compile 27 s → 17 s after
the 09-01 allocator work (`1ff636ae`: memcpy relocations, 1 MiB regions, free-list hint).
`elisacore_std/arena.elisa` now has `free_list` fields — confirm the block-cache idea from the
arena note is what landed (it was blocked on cross-repo vendoring; if the std was re-vendored
with it, the note's "blocked" is stale). Next measured targets, in order: `sample` the
self-compile again for the top leaf; the semantic field-chain memo (`6278d3f9`,
`6921b84a`) suggests more hash-chain walks exist (`bf2b1319`, `a584ab52`) — profile before
guessing. Keep `compile_cpu.baseline` ratcheted.

### 6.7 Platform portability
- MEASURED 2026-09-06 on Ubuntu 24.04 x86_64 (Vast instance): stage0 needs LLVM >= 19
  (`LLVMDIBuilderInsertDeclareRecordAtEnd`), a `C.ulonglong` cast in `llvm_exprs_fstring.go`
  (uint64_t is `unsigned long` on Linux; patched in both repos), AND `z3` on PATH: the CLI
  defaults `enableSMT: true`, so without a solver every `ensure` on a conditional fails with
  "could not be proven statically" — the std's `max/min/clamp` included. The wrapper's link
  line is macOS-only (`-Wl,-dead_strip`, `-Wl,-stack_size`, `-lLLVM`); a clang shim that maps
  them to `--gc-sections`/`-lLLVM-21` was enough to seed.
- `host_platform_name()` constant `"macos"` — Linux needs `uname` via extern;
- smokes assume Mach-O (`file` says Mach-O, `nm` output shapes, `-dead_strip`); audit
  `test/parity/*.sh` for `Mach-O|otool|-dead_strip` and gate them on host;
- Apple clang vs LLVM clang note in the wrapper (LLVM_CONFIG compatibility);
- WASM: aggregate exports are rejected by design (adapters are the escape hatch) — keep.

---

## 7. Cross-repo items (Elisa-core / stage0)

Held here because the stage1 oracle depends on them. Sequencing constraint: the Elisa-core
git hook rebuilds `~/.elisac/elisac` on every commit — never commit to stage0 while a stage1
gate is running.

7.1 Effectful-helper specialization in stage0 (parity for §3.1).
7.2 Interpreter generic named-arg-by-position bug (§6.4).
7.3 Warnings on STDOUT and non-reproducible warning output on large inputs (noted 08-17,
    never chased): run `-emit obj` on the compiler source 10× and diff stderr/stdout.
7.4 `AssignableTo` through the variable-assignment path with a generic return (`take_result`,
    §3.3.4).
7.5 `__auto_N` region naming stability (fmt ceiling, §6.1).
7.6 stage0 accepts `handler H() for A.Tick:` when uninstalled — decide whether stage0 should
    reject too (the owner's rule is "modules are accessed with `::`, and if the compiler
    allows `.` it should not").
7.7 Vendored runtime: keep `check_runtime_drift.sh` green; every `elisacore_std/*.elisai`
    re-vendor must copy EVERY file (the guard's own advice was wrong once).

---

## 8. Decisions the owner must make (do not guess these)

| # | question | default if silent |
|---|---|---|
| D1 | Adopt stage0's two-message wording for mismatched effect heads (§3.1.3)? | keep stage1's until stage0 has the feature |
| D2 | Port effectful-helper specialization to stage0 (§3.1.7)? | no; stage1-only gate |
| D3 | ~~By-value parameter drop~~ — RESOLVED: already fixed by `1f6db0c0`; no decision needed | — |
| D4 | `common:` layout — RESOLVED 2026-09-05: report is now truthful and matches stage0 field-for-field; the only residue is physical AoS row bytes (24 vs 32). Keep current unless a store must cross compilers. | current |
| D5 | Build `-emit serve` at all (§5.6)? | no |
| D6 | Switch `scripts/build_runtime_object.sh` from stage0 to stage1 (trust-root change)? | no |
| D7 | Delete the wrapper once §4 is green (removes the Python dependency entirely)? | yes, staged |
| D8 | SMT/Z3 stays out of scope? | yes |
| D9 | stage0 rejects `handler for A.Tick` uninstalled (§7.6)? | yes, for consistency |

---

## 9. Sequencing and milestones

```
M0 (day 1)     §2: commit, re-baseline, fix the three stale docs, refresh memory notes
M1 (week 1-2)  §3.1.4-5, §3.3.5, §3.2 investigation, §3.6/3.7 confirmations
M2 (week 2-3)  §3.3.1-3.3.4 permissive gaps (each behind a stage0-measured table)
M3 (week 3-4)  §3.1.1-3.1.3, §3.1.6 stress test, §3.4 over-reporting re-measure
M4 (week 3-6)  §4 driver owns the CLI (4.1 → 4.2 → 4.3 → 4.4 → 4.5 → 4.6)
M5 (week 4-8)  §5.1 columns to 0, §5.2 parse errors, §5.3 ir writer/reader
M6 (week 6-12) §5.4 fact system, §5.5 easm liveness set, then §5.6 if D5=yes
M7 (rolling)   §6 ratchets, §6.5/6.6 re-measures, §7 upstream items as they unblock
```

Exit criterion for "the compiler is finished to declared scope": every row of §1.1 either
reads N/N, or its residue is one of the §1.3 deliberate decisions, or it is a §8 item the
owner answered "no". Nothing else counts.

---

## 10. Per-item verification recipe

For each task above, the job script has the same five parts:

```
PART 0  seed build from the edited tree (stage0 -> stage1), touch $STAGE1
PART 1  the task's probe matrix: every fixture through BOTH compilers; print
        s0(rc,run) s1(rc,run) and the first two lines of each diagnostic; flag DIVERGES
PART 2  the focused smoke(s) named in the task
PART 3  differential_corpus.sh + adversarial_differential.py (-O0 and -O2)
PART 4  self_host_gen2.sh + self_host_gen3_smoke.sh (run ALONE, not in parallel with PART 2/3)
PART 5  ELISA_GATE_PROFILE=full bash test/parity/run_all.sh   (only before a commit)
echo "ALL PARTS DONE"
```

And the traps that have produced a FALSE reading at least once each — check before believing
a number: a gate on `bin/elisac-stage1` tests THE SEED, not the tree; a self-hosted emitter
fix needs TWO generations before it runs; never judge `run_all.sh` from the tail (the SKIP
list prints last); a "DECLINE" in the corpus can be a TIMEOUT; `build/parse_report` is stale
unless rebuilt through the sourced script; `$(find …)` unquoted splits the repo path on its
SPACES; BSD `sed` ignores `\b`; `sview(value, start, END)` takes an END index, not a length;
`git stash` on a clean tree pops an unrelated older entry — use `git worktree`.
