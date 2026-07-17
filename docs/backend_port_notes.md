# stage1 backend port — scoping notes

## What the remaining work actually depends on

Measured, not estimated. stage0's backend is 54,417 lines / 156 files of cgo.

### dict is gated behind GENERICS (found 2026-07-17)

dict is NOT analogous to darray. stage0 lowers a darray INLINE, needing only two runtime
primitives (`arena_alloc`, `arena_realloc`) — so it could be mirrored by reading stage0's
`-emit llvm` output.

A dict instead calls **monomorphized std generics**:

    arena_dict_get_mut__i64__i64
    arena_dict_find_index__i64__i64
    arena_dict_get_or_insert__cstr_key_shape__i64

and pulls the std into the module: a three-line dict program emits **102 functions**.
`%DynDict__K__V = type { ptr, i64, i64, i64, ptr }`, `%DictBucket__K__V = { ptr, i64, i8 }`.
A dict program also does not compile at all without `elisacore_std/collections.elisa`
included (`undefined identifier "arena_dict_get_mut"`).

So supporting dict requires, in order:
1. **Generic function instantiation / monomorphization** (`f[K,T]` -> `f__i64__i64`).
2. Compiling `elisacore_std/collections.elisa`, which itself needs error unions
   (`error[RuntimeError]`), references, and optional-of-reference (`mutable T&?`).

That is a subsystem, not a slice. Generics are the real gate, and they unlock user generics
too — so generics, not dict, is the next structural target.

Note the dict SYNTAX also differs from the guess: `d[k] <- v` does NOT insert
(`arena_dict_get_mut` returns `mutable T&?`, so it is a type error). The working forms are
a dict literal `{1: 40, 2: 2}` and `d.entry(k).insert(v)`; `d[k]` reads.

### Ordering implied by this

- generics/monomorphization  -> unlocks dict, set, user generics, most of the std
- region inference proper    -> auto regions exist (0d24d40) but nothing smarter: no region
                                parameters, no polymorphism, no death-time
- packed enums               -> needs the AoS store model
- effects, DWARF, -Wperf     -> independent, later

### Method that works

READ THE REFERENCE'S IR. `elisac -emit llvm x.elisa` hands over the exact representation,
runtime signatures, and constants (darray's 256 initial capacity, the Arena strategy=2
field, the grow rule). Every ABI in this port came from there rather than from guessing.

## generics: design constraint found before implementing (2026-07-17)

Attempted monomorphization, got the machinery working (template registration from the
file-level `generic_param_names`/`generic_param_lines` side table keyed by function LINE;
binding-aware type resolution; `identity` + [i64] -> `identity__i64` mangling matching
stage0; declare-at-callsite + worklist for bodies) — then hit a REAL region constraint and
backed it out rather than force it. What was learned, so the next attempt starts here:

### 1. Type bindings must live in an already-threaded table, not a new parameter

`no_type_bindings()` returning a fresh empty `TypeBindings` is REGION-POLYMORPHIC, so it
cannot be called from a non-region-inferable context ("must occur where a region can be
inferred"). Constructing an empty owned container per call site does not work. Put the
current instantiation's bindings in `StructTable` (already threaded everywhere a type is
resolved), set on entry to an instantiation and cleared on exit.

### 2. Mangled-name STORAGE is the real problem

An `sview` is a (ptr, len) VIEW. Building a mangled name into a local `darray[u8]` and
pushing it into a longer-lived table copies only the outer {ptr,count,cap} — the BYTES stay
in the function's auto region and are freed at return. Elisa's region checker catches this
exactly:

    value in region "__auto_N" is stored into longer-lived region "__rg_generics" via a
    by-value copy; region "__auto_N" is freed first, leaving a dangling element

(The backend's own region model catching a real dangling reference in the backend is a good
sign for the language; it is still a design problem to solve.)

Neither easy option is right:
  * `darray[darray[u8]]` — the inner buffer must be allocated in the TABLE's region, not
    built locally and pushed. Needs the name built in place, through a mutable reference to
    a slot that already lives in that region.
  * a flat `darray[u8]` pool + (start, len) — an sview into the pool DANGLES if the pool
    reallocs. Would have to re-derive the view at each use and never hold one.

The clean answer is probably a region-parameterized name builder (`def build_name[@r](...)
-> sview @r`) so the bytes are allocated in the table's region by construction. That is a
design pass, not a patch.

### 3. Scope for the eventual attempt

stage0 supports inferred (`identity(42)`) and explicit (`identity[i64](42)`) calls; the
explicit form makes the callee an `Expr.Index`, not an `Expr.Ident`. Start with ONE type
parameter and scalar type arguments; multi-parameter inference is separate.

## nested generics: diagnosed to the exact line, not yet fixed (2026-07-17)

A generic calling another generic DECLINES (pinned by `decline_case generic_chained`).
Everything else about generics works — see 41638be. Diagnosis so far, so the next attempt
does not start from zero:

### Symptom

The emitter TRAPS (SIGTRAP, rc=133) — it does not mis-emit. `identity(x)` called from inside
`wrap[T]`'s instantiation. Both inferred and explicit (`identity[i64](42)`) forms trap. A
generic calling a NON-generic is fine; a generic instantiated twice at top level is fine.

### Where, exactly

Traced with `perror` probes at each step. The queueing all succeeds:

    instantiate wrap -> queued
    drain 0: emit wrap body -> instantiate identity -> queued -> body done
    drain 1: emit_instantiation_body ENTER -> ... -> TRAP

and within `emit_instantiation_body` for the SECOND instantiation it reaches:

    "F pushing binding"          <- printed
    structs.binding_names <- structs.binding_names.push(generics.params[generics.param_start[slot]])
    "G pushed name"              <- NOT printed

So the trap is on that one statement, on the second instantiation only. The first
instantiation executes the identical statement fine. Every index involved is valid by
construction (two templates => names/param_start/param_count all count 2, params count 2,
slot == 1).

### Ruled out

* Not the drain loop capturing a by-value `generics`: moving the loop into
  `drain_instantiations(generics: mutable GenericTable&, …)` so the capture copies a
  REFERENCE did not help. (Worth keeping in mind anyway — that IS a real hazard, cf. the
  `=` vs `<-` capture semantics.)
* Not unbalanced binding push/pop: every push has a matching pop on every path
  (instantiate_generic, generic_return_type, instantiation_param_type,
  emit_instantiation_body).
* Not recursion/non-termination: the drain trace shows it terminating into the trap.

### Narrowed further: it is the PUSH, not the read

Two hypotheses tested and DISPROVEN:

1. *Single-statement aliasing* (reading through `generics` while writing through
   `structs`). Binding the name to a local first does NOT fix it — still rc=133.
2. *push/pop leaving a darray in a bad state.* A standalone push/pop/push cycle on a
   struct-held `darray[sview]` through a `mutable&` works fine.

A finer probe places it exactly:

    2 read param_start   <- printed
    3 read params[]      <- printed
    4 pushed name        <- NOT printed   ** the push itself traps **

The value is already in a local by then, so it is neither the read nor an aliased index.
It is `structs.binding_names.push(...)` on the SECOND instantiation, after the first has
completed several balanced push/pop cycles.

### THEORY CONFIRMED by experiment (2026-07-17)

Pre-sizing the binding stack — so a binding is an index STORE and a push never GROWS —
changed the failure from **rc=133 (SIGTRAP, a bounds check)** to **rc=139 (SIGSEGV, reading
freed memory)**. Removing one growth site MOVED the crash. That is the confirmation: the
cause is a caller-owned darray being GROWN from inside a callee.

The remaining SIGSEGV is the other growing tables — `GenericTable`'s `pending_*` and
`inst_*` — which are pushed from `instantiate_generic`, itself running deep under
`emit_function_body`.

### ROOT CAUSE FOUND: `x <- []` inside a callee is NOT a clear

`instantiation_param_type` ended with:

    _ = push_type_binding(structs, …)
    resolved = annotation_value_type(…, structs)
    structs.binding_names <- []          # <-- THIS
    structs.binding_types <- []
    return resolved

`structs.binding_names <- []` does NOT clear the caller's darray. It REBINDS the caller's
field to a **fresh empty darray allocated in THIS callee's auto region**, which is freed the
moment the callee returns. Every later access to `structs.binding_names` then follows freed
memory — hence SIGTRAP (bounds check against a garbage count), and SIGSEGV once the binding
stack no longer grew. It also silently wiped any OUTER instantiation's bindings.

Replacing it with a `pop` FIXES the nested-generic crash: `wrap[T]` calling `identity[T]`
emits with rc=0 instead of trapping. **Confirmed.**

To CLEAR a shared container from a callee, pop to the intended depth (or have the OWNER
clear it). Never `<- []` a field you do not own — the empty literal is allocated where you
are standing, not where the field lives. This is worth remembering well beyond generics: any
`x.field <- []` inside a function that received `x` as a `mutable&` is this bug.

### Still to do: the pre-sizing refactor is NOT the fix and broke things

Pre-sizing (index stores + explicit counts) was an experiment to *prove* the growth theory,
and it did — but as an implementation it regressed working generics: with the tables
pre-sized, `generic_explicit` emitted only `@main` and no instantiations at all (invalid IR).
It was reverted. Do NOT re-apply it wholesale; the `<- []` fix above is the real one and is
independent of it.

### The fix (superseded — kept for context)

Pre-size EVERY table that is grown from inside a callee, in emit_module's region, and use
index stores plus an explicit count:

* `StructTable.binding_names` / `binding_types` + `binding_depth`   (done in the experiment)
* `GenericTable.inst_*`     + `inst_count`
* `GenericTable.pending_*`  + `pending_count`

Overflow should DECLINE, never grow — growing is precisely what breaks. Remaining work: the
`*_handles` arrays hold `LLVMValueRef`, which has no default to prefill with, so
`new_generic_table` needs `ctx` to seed them with `LLVMConstNull(pointer_type)`; and every
`.push(...)` site must become an index store against the count.

### Why this matters beyond generics

This is the cross-fn "grower" lifetime machinery, and the shape is
`region-byvalue-builder-uaf` (caller-owned struct field grown via a forwarded `mutable&`).
A minimal repro of that exact shape runs CLEAN:

    struct Table: names: mutable darray[sview]
    def use_once(t: mutable Table&, n: sview): t.names <- t.names.push(n); _ = t.names.pop()
    def outer(t: mutable Table&, n: sview):    t.names <- t.names.push(n); use_once(t, n); _ = t.names.pop()

so the trigger needs more than that: a deep call chain, several live `mutable&` tables, and
region-polymorphic frames between. Reducing it is worth real effort — a well-typed program
must not be able to trap or segfault the emitter, so with a repro this is a stage0 bug.

### Superseded theory: cross-fn grower region

When `push` GROWS the darray, the new backing is allocated from the region inferred AT THE
PUSH SITE — `emit_instantiation_body`'s auto region — which is freed when that function
returns. The next call then reads a freed buffer. `StructTable` is a caller-owned struct
whose field is grown through a forwarded `mutable&`, which is the shape of the known open
bug `region-byvalue-builder-uaf` (region-poly struct builder, field grown via forwarded
`mutable&` -> UAF), and touches the cross-fn "grower" lifetime machinery.

A minimal repro of that shape does NOT reproduce it:

    struct Table: names: mutable darray[sview]
    def use_once(t: mutable Table&, n: sview): t.names <- t.names.push(n); _ = t.names.pop()
    def outer(t: mutable Table&, n: sview):    t.names <- t.names.push(n); use_once(t, n); _ = t.names.pop()

runs clean. So the trigger needs more than "callee grows a caller-owned field": the real
case has a deep call chain, several distinct `mutable&` tables live at once, and
region-polymorphic frames in between. Reducing it is the next job — with a repro this is a
stage0 bug worth filing, because a well-typed program must not be able to trap.

### RESOLVED (38b3f30)

Fixed by replacing the two `<- []` lines with pops. Nested generics now work, including
three-deep chains and two type arguments; the decline fixture was promoted to real coverage.
The pre-sizing refactor was NOT needed and was not applied.

## references (`T&`): LANDED (68402af)

RESOLVED. The blocker recorded below was WRONG: `T&` is a POSTFIX
`Expr.Unary(Ampersand, T)` all along (parser_expr_ops.elisa ~147 — the parser distinguishes
it from infix bitwise-and by looking PAST the whole `&` run). The annotation resolved fine;
that is exactly why the end-of-function classifier probe never fired. The decline was
DOWNSTREAM: field access through a reference.

`struct_address_of` is the piece that was missing: a plain local's struct address is its
alloca; a `P&` parameter's is that alloca LOADED. After that, field GEP/load/store are
identical for both, so field access needs no ref-specific path.

Lesson: "the probe never fired" meant *everything resolved*, i.e. look DOWNSTREAM — not
"the node is unknown". Two sessions were spent hunting the AST shape that was never the
problem.

## references (superseded — the wrong diagnosis, kept for the lesson)

Attempted next, reverted rather than leave dead code. What is known:

### stage0's lowering (read from `-emit llvm`)

    def bump(n: mutable i64&) -> void       =>   define void @bump(ptr %0)
    bump(x)                                 =>   call void @bump(ptr %x)

A reference is just a `ptr`. The callee spills it (`%n = alloca ptr; store ptr %0`) and
loads THROUGH it. This fits this backend well: locals are already allocas, so passing
`&local` is passing the alloca. Mutability is a frontend concern — the backend needs only
the referent type. `TypeKind.Ref` with `bits` indexing a `ref_targets` side-pool, and
`llvm_type_of` returning `LLVMPointerTypeInContext(ctx, 0)`, is the right shape (it compiled
cleanly).

Both idiomatic forms work under stage0 and are the fixtures to aim at:

    def total(p: P&) -> i64: return p.x + p.y                       # immutable struct ref
    def bump(c: mutable Counter&) -> void: c.value <- c.value + 1   # mutable struct ref

(`n <- n + 1` on a `mutable i64&` trips stage0's unsafe audit — "pointer arithmetic requires
can[Unsafe]" — so prefer the struct-ref forms for fixtures.)

### The open question: WHERE does `&` live in the stage1 AST?

Not on `ParamDecl` (its fields are `name`, `type_expression`, `is_mutable`, `has_default` —
there is no `is_ref`). And NOT reachable as `Expr.Unary(Ampersand, T)`: adding that case did
not fire, and an end-of-function classifier probe in `annotation_value_type` never printed at
all — meaning every annotation RESOLVES (so `p: P&` is resolving, presumably to plain
`Struct P` with the `&` dropped) and the decline is somewhere else entirely.

Next step is therefore NOT to guess the node again: dump the actual annotation for `p: P&`
(e.g. teach test/breadth a mode that prints the parsed annotation, or probe the parser
directly) and find where `&` is recorded. `parser_types.elisa:245` mentions
`TokenKind.Ampersand` alongside `Lmut` under a `provenance` flag — that is the lead.

## error unions: ABI fully mapped, not yet implemented (2026-07-17)

The last named blocker before `collections.elisa` compiles (hence dict/set). References
(68402af) and optionals (d82d2c8) already cleared the other type-model prerequisites.

Not started as code — it is a new CALLING CONVENTION, a bigger slice than the recent ones,
and this was the tail of a long session. But the expensive part (discovering the ABI) is
DONE. Everything below is read out of stage0's `-emit llvm`; implement directly from it.

### Working source (stage0 accepts, returns 42)

    error Bad:
        Nope

    def risky(flag: bool) -> i64 error[Bad]:
        raise Bad.Nope if not flag
        return 42

    def main() -> i64:
        catch risky(true):
            ok:
                return ok
            error e:
                return 1

SYNTAX GOTCHAS (both cost a round): `catch` is NOT infix — `x = f() catch 0` does not
parse. And a `catch` block's SUCCESS ARM MUST COME FIRST ("catch expression must start with
a success arm").

### The ABI — the tag is the RETURN, the value goes through an OUT-POINTER

`def risky(flag: bool) -> i64 error[Bad]` lowers to:

    define i32 @risky(ptr %0, i1 %1)

NOT the `{i32, i64}` struct by value. The i32 RESULT is the error tag (0 == ok) and the
success value is stored through the leading out-pointer:

    if.then:  store i64 0,  ptr %0   ; raise: payload zeroed
              ret i32 1              ;        tag = the error's code
    if.end:   store i64 42, ptr %0   ; return v
              ret i32 0              ;        tag = 0 == ok

So: **`f(out_ptr, args…) -> i32 tag`**. The declared type
`%ErrUnion__Bad__i64 = type { i32, i64 }` exists but is only materialized at the CALL SITE.

### Call site + catch

    %call.result = alloca i64
    store i64 0, ptr %call.result
    %calltmp     = call i32 @risky(ptr %call.result, i1 true)
    %call.payload = load i64, ptr %call.result
    ; rebuild the union value from (tag, payload)
    %errunion.err   = insertvalue %ErrUnion__Bad__i64 undef, i32 %calltmp, 0
    %errunion.value = insertvalue %ErrUnion__Bad__i64 %errunion.err, i64 %call.payload, 1
    %errunion.code  = extractvalue %ErrUnion__Bad__i64 %errunion.value, 0
    %catch.ok = icmp eq i32 %errunion.code, 0
    br i1 %catch.ok, label %catch.value, label %catch.dispatch

    catch.value:      ; the `ok:` arm — payload = extractvalue …, 1
    catch.dispatch:   ; switch i32 %errunion.code, label %catch.error [ … ]
                      ; per-variant arms become switch cases; `error e:` is the default

### BLOCKED — and NOT on the backend: stage1's AST loses the catch subject

Do not start the implementation below until this is fixed. `Ast::Stmt.Block` is:

    Block(kind: sview, clause: darray[sview], binding: sview, body: darray[Stmt], line: u32)

There is **no Expr field**. `catch risky(true):` is parsed by `parse_block_prefix`
(src/parser/parser_stmt_control.elisa ~238): `block_kind` becomes "catch" and the prefix
tokens go into `clause` (dotted-name sviews) or are skipped by the `_:` fallthrough. The
SUBJECT EXPRESSION is discarded — at best the dotted name "risky" survives, with the call
and its arguments gone. The backend cannot emit a catch because the information is not in
the tree.

Worse, stage1 also MIS-DIAGNOSES that program (which stage0 compiles and runs):

    P 0
    D 2
      L9 top-level integer match arm must use an integer literal or _
      L9 top-level integer match arm must use an integer literal or _

L9 is the `ok:` success arm — the checker is running catch arms through the INTEGER MATCH
arm check. A real stage1/stage0 divergence, filed as a task against the frontend.

`try EXPR` (statement form, e.g. collections.elisa:977
`try arena_dict_reserve(owner, m, target_capacity)`) has the same shape and probably the
same gap — check it when fixing.

### Implementation order (once the AST carries the subject)

1. `error Bad: Nope` decl -> a table of error sets and their variant CODES. Codes start at
   1; **0 is reserved for ok**.
2. `declare_function`: a `-> T error[E]` signature becomes `i32 (ptr, params…)`.
3. `emit_function_body`: `return v` -> `store v, out; ret i32 0`. `raise E.X` ->
   `store zero, out; ret i32 <code>`.
4. Call site: alloca the payload, call, then either rebuild the union (to match stage0) or
   just branch on the tag directly — the union value is an artifact of stage0's lowering,
   not something the ABI requires.
5. `catch` statement: success arm FIRST, then a switch over the code with `error e:` as the
   default.

Only the single-error-set, non-generic case is needed to start; `collections.elisa` uses
`error[RuntimeError]` throughout.

## Modules — ABI mapped, not yet implemented

Read from stage0's `-emit llvm`, not guessed:

    module M:
        def get() -> i64: ...
    def main() -> i64:
        return M::get()

emits `define i64 @M.get()` and `%calltmp = call i64 @M.get()`. So the mangling is
**dot-separated** (`M.get`), while the SOURCE spelling of a qualified call is `::`.
`M::get` parses to `Expr.Scope(Expr.Ident("M"), "get", line)` — a node kind distinct from
`Expr.Field` (parser_expr_ops.elisa ~132), so the call path can tell a qualified call from
UFCS without ambiguity.

Design constraint that decides the shape: `FnTable.names` holds **sviews into the source
buffer**. A mangled `"M.get"` has no source text to point at, so keying the table by the
mangled string would need synthesized storage that outlives every lookup — and an sview
into a growing `darray[u8]` DANGLES on realloc.

So: add an `owners: mutable darray[sview]` column to FnTable (module name, `""` for
top-level) and key lookups on the (owner, name) PAIR. Nothing is synthesized except the
LLVM symbol name itself, which is a temporary cstr built at declaration time exactly as
`register_struct_name` already does via `sview_to_cstr(name, name_storage)`.

Touch list (16 call sites total): `lookup_function` (3), `function_index_of` (2),
`param_type_of` (3), `lookup_return_type` (4), `function_name_of` (4) — each gains an owner
argument, `""` at existing call sites. `emit_module`'s four passes must also walk into
`Decl.Module(name, body, line)` bodies rather than skipping them (`function_name_of` returns
"" for a module today, so a module's functions are silently never emitted — which is why a
qualified call declines).

Nested modules (`A::B::get`) are NOT covered by a single owner column; either flatten the
owner to a dotted path or decline them.
