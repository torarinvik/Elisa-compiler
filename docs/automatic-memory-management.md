# Automatic manual memory management

The goal: the compiler decides where every allocation lives, when it is freed
and when its storage is reused -- the decisions a careful C programmer makes by
hand -- with no garbage collector, no reference counts and no runtime tracing.
It should do this better than most people writing it by hand, the way a
register allocator beats hand-written assembly: not through clever tricks, but
because it sees every use site and never gets tired.

This document fixes the invariant, maps the pieces stage1 already has onto it,
and lays out the order of work. [memory-speed-automation.md](memory-speed-automation.md)
and [loop-scratch-memory.md](loop-scratch-memory.md) describe individual
optimizations in detail.

## The soundness invariant

> A value is never placed in storage that dies before the value's last use.
> When the compiler cannot prove how long a value lives, it uses the
> longest-lived storage available to it, or it declines loudly.

Everything else is optimization. Where the proof is complete, the value moves
to shorter-lived, cheaper storage: stack before loop region, loop region before
function arena, function arena before caller arena. Where the proof has a gap,
the value goes to longer-lived storage, never to shorter-lived storage. This is
the same shape as a register allocator. It spills when it is unsure. It never
reuses a register it cannot prove is dead.

The failure this invariant forbids is silent. A misplaced value produces a
wrong answer, not a crash. The 2026-09-26 audit found four such cases in the
automation layer. Each returned a plausible but wrong exit code, and
self-hosting did not surface any of them. That is why every placement rule
needs a value-checking differential fixture, not just a compile check.

## The placement ladder

| Storage | Freed | Decided by |
| --- | --- | --- |
| Stack (entry block) | function return | `memory_emit_buffer` bounded stack placement |
| Loop region | each iteration (reset) | loop-scratch lowering |
| Function arena | function return | default for local owners |
| Caller arena (hidden ABI parameter) | caller's region | `signature_needs_arena` / `value_type_returns_caller_region` |
| Explicit `@r` region | the region's scope | the programmer |

Moving a value up the ladder is always sound and only costs speed. Moving it
down requires a lifetime proof.

## What the 2026-09-26 fixes were, in these terms

Each fix restores the invariant at one decision point:

1. **Return values that own region storage** (`codegen_type_sizes.elisa`,
   `codegen_abi_regions.elisa`). Ownership of region storage is transitive
   through Optional, ErrorUnion, arrays, tuples and struct fields, and it stops
   at refs. This matches stage0. A `darray?` return used to be allocated in the
   callee's arena, which dies at return. It now gets the caller arena, and
   stage1's signatures match stage0 for every probed shape except enum-payload
   returns, which stage1 still declines loudly.
   `value_type_owns_region_storage` fails closed (returns `true`) past depth 32.
2. **Value-block tails** (`codegen_memory_speed.elisa`). The tail expression of
   a value block outlives the block's statements. A buffer that the tail reads
   cannot be stack-promoted unless the tail consumes it as a scalar.
3. **Address-of and move roots** (`codegen_growth_arena.elisa`).
   `growth_root_name` now sees through `&x` and `move x`. A ref local whose
   referent is unknown grows in the function's outermost arena, not the
   innermost one.
4. **`__drop__` types are affine** (`symbols.elisa`). A struct with a destructor
   cannot be implicitly copied, or two scopes would run the destructor on the
   same storage. The diagnostic text matches stage0 ("linear value ... must be
   moved explicitly").

`test/parity/amm_placement_soundness_smoke.sh` runs each fixture at `-O0` and
`-O2` and compares the exit code with stage0's. The pre-fix binary fails 9 of
the gate's checks.

## Why the current structure will not scale

Today, each optimization carries its own escape proof. That includes the
memory-speed buffer proofs, growth-arena root naming, loop-region reset and
ABI region inference. The proofs are syntactic, and each one covers only a few
shapes. Every new shape needs a new proof, and a missing case silently falls
through to "no escape". That is exactly the bug class above.

A compiler that allocates better than a human needs one answer to one
question, shared by the checker and by placement:

> For each allocation site, which program points can still reach the value?

## Roadmap

1. **One place/loan/origin analysis per function.** Build it on the CFG. Its
   inputs are places (locals, fields, projections), loans (`&`, ref params,
   region borrows) and origins (which region or arena each value lives in).
   `check_destroyed_region` already walks this shape and is the seed. The
   memsafe audit's open checker items (lref/opt/stk) are also queries against
   this analysis.
2. **Per-function summaries.** Record which parameters escape into the return
   value, which escape into long-lived storage, and which are only read. A
   summary lets the caller keep an argument in shorter-lived storage without
   inlining. This replaces the "unknown call ⇒ decline" rule in the
   memory-speed proofs.
3. **Placement as a solver over the ladder.** Give each allocation site the
   lowest rung that dominates all its reaching uses. The existing optimizations
   become special cases, and the fail-closed rule becomes the solver's default.
4. **Reuse.** Once lifetimes are explicit, storage whose lifetime has ended can
   be reused in place:
   - reset loop regions early;
   - reuse a dead buffer's capacity for the next same-typed allocation;
   - free early inside long functions.

   This is where the compiler beats hand-written code, because a person
   rarely does this consistently.
5. **Explanation.** `ELISA_EXPLAIN_MEMORY=1` should report, for every
   allocation, the rung it got and the fact that blocked the next rung down.
   A person can only trust automatic placement if they can audit it.

Each step ships with value-checking differential fixtures, run at `-O0` and
`-O2`, and with the pre-fix binary shown failing them.
