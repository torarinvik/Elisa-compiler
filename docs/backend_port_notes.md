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

## Modules — LANDED

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

Nested modules (`A::B::get`) are NOT covered by a single owner column: they nest Scope
inside Scope, whose head is not an Ident, so they DECLINE rather than mangle a wrong symbol.
Flattening the owner to a dotted path would lift that, but a dotted owner has no source text
to point an sview at — the same constraint as above.

Implemented as described. One footgun found while probing: stage1's parser treats `get` as
an UNGATED contextual keyword (parser_expr.elisa ~114), so `def get()` cannot be called even
though stage0 compiles it — every other contextual keyword there (`do`, `when`, `machine`)
is gated on lookahead. Filed separately; avoid `get` in fixtures until fixed.

## Externs — LANDED (the AST gap was fixed)

`extern strlen(s: cstr) -> usize` lowers to `declare i64 @strlen(ptr)` in stage0 — trivial
IR. But `Ast::Decl.Extern(name, param_start, arity, variadic, callable, decorators, line)`
has **no return-type field**, and `extern_declaration` (parser_types.elisa ~172) calls
`skip_declaration_header_clauses()`, which swallows the `-> usize`. The return type is
parsed and discarded, so the backend cannot emit the `declare`.

Param types DO survive, but in a side table rather than the node: `param_start`/`arity`
index `File.extern_params` (`ExternParam{name, type_name: sview, provenance_bearing}`),
where the type is a bare NAME, not an Expr.

Filed as task_d010c4d5 — and FIXED: `Decl.Extern` now carries `return_type_name`, so this is
implemented. Param and return types are bare NAMES (not Exprs), so both resolve through
scalar_type_of_name rather than annotation_value_type. Variadic externs and `extern name: T`
(a global, not a function) decline.

Still open in the same family: task_c19cb583 (`Stmt.Block` has no Expr, so `catch
risky(true):` loses its subject) and tuple labels. Those remain FRONTEND fixes.

Knock-on, now resolved: a cstr fixture's EXIT CODE could not observe a string's contents
without `strlen`, so `ir_case` covered the literal's shape instead. With externs working,
`strlen("hello") + 37 == 42` observes the contents behaviorally, and the cstr ir_cases are
now belt-and-braces rather than the only evidence.

## Tuples — BLOCKED on the stage1 AST (labels discarded)

The BACKEND side is trivial and already built: a tuple IS an anonymous struct. stage0 emits
`t: (a: i64, b: i64) = (40, 2)` as `alloca { i64, i64 }` + `store { i64, i64 } { i64 40,
i64 2 }`, reads `t.a` as `getelementptr { i64, i64 }, ptr %t, i32 0, i32 0`, and passes /
returns by value (`define { i64, i64 } @pair()`, `define i64 @take({ i64, i64 } %0)`) —
exactly the existing Struct machinery with a structurally-interned anonymous type.

The blocker is that `Ast::Expr.Tuple(elements: darray[Expr], line: u32)` stores **no
labels**. For the named-tuple TYPE `(a: i64, b: i64)`, parser_expr.elisa (~266) consumes
each label and keeps only the element types; the node's own comment in parser_tokens.elisa
(~94) states this and notes that closing it "needs labels on this node".

`t.a` cannot resolve to index 0 without the label, and `t.0` is not valid Elisa (it lexes as
FLOAT ".0" — stage0: `expected newline, got FLOAT(".0")`), so a tuple's fields cannot be
read AT ALL. Since reading fields is the only use of a tuple, the backend declines.

Note the same missing labels already cause a known FRONTEND divergence: the node cannot
distinguish canonical `(x: int, y: int)` from positional `(int, int)`, which stage0 rejects
everywhere, so stage1 wrongly ACCEPTS the positional form (backlog 110b). One fix — labels
on Expr.Tuple — closes both that diagnostic gap and this backend blocker.

Spellings (verified against stage0): the TYPE is named-field `(a: i64, b: i64)`; the VALUE
is POSITIONAL `(40, 2)`. `(a: 40, b: 2)` is rejected ("expected IDENT, got INT").

## Region threading (cross-fn) — LANDED

This is the first real piece of region POLYMORPHISM, and stage0's shape is simple. For

    def fill(out: mutable darray[i64]&) -> void:
        out.push(42)

    def main() -> i64:
        xs: mutable darray[i64] = []
        fill(xs)
        return xs[0]                       # stage0: exit 42; stage1 currently DECLINES

stage0 emits `define void @fill(ptr %0, ptr %1)` — **TWO** params for a one-param function.
`%1` is the CALLER's arena, threaded implicitly, and the growth inside uses it:
`call ptr @arena_alloc(ptr %1, ...)` / `@arena_realloc(ptr %1, ...)`. The call site passes
it: `call void @fill(ptr %xs, ptr %"__auto_85#1")`.

So the rule: a function with a GROWABLE CONTAINER REF param (`mutable darray[T]&`) gains an
implicit trailing `ptr` arena parameter, and growth inside uses THAT arena instead of the
function's own auto region. It must NOT arena_free it — the region belongs to the caller.

Implementation sketch:
1. `needs_arena_param(decl, structs)` — true when any param is a Ref whose target is a
   DArray. Add a `needs_arena: darray[bool]` column to FnTable so call sites can ask.
2. `declare_function` — append one `ptr` param when so.
3. `emit_function_body` — bind `local_runtime.arena` to the TRAILING PARAM rather than
   building a fresh `auto.region` alloca, and skip the arena_free.
4. `emit_direct_call` — append the caller's `runtime.arena` as the trailing argument.

DONE as sketched (5e85393 threaded runtime; this commit added the arena param). What the
sketch MISSED: darray ops through a REF. A `darray[T]&` param's slot holds a POINTER to the
caller's header, so push/count/index each needed one extra load — `darray_address_of` now
resolves a local darray (its slot) and a borrowed one (load the slot) uniformly. Also
`Runtime.owns_arena`: a threaded arena is BORROWED and must never be arena_free'd, or the
callee destroys the caller's region on return.

Historical note — the blocker that was: step 4 needed the runtime at the call site, and
`emit_expression` did not take `runtime` — `emit_statements` does, but
`emit_expression` / `emit_call` / `emit_direct_call` / `emit_generic_call` do not. Threading
it through is ~33 `emit_expression(` call sites plus their Elisa CAPTURE LISTS (a loop body
that calls emit_expression must add `runtime` to its `|...|`), which is where this gets
error-prone rather than merely tedious. Do that refactor as its own mechanical commit,
verify smoke stays at 204/204, and only then add the arena param.

### Region-RETURN inference — LANDED (same mechanism)

Returning an owned container turned out to be the SAME rule, not a further one. stage0 emits
`def build() -> darray[i64]` as `define %DynArray__i64 @build(ptr %0)` — a container RETURN
TYPE is simply a second trigger for the implicit trailing arena param, and the callee
allocates the returned darray's backing from the CALLER's region, which the caller frees at
its own return.

So `signature_needs_arena(params, return_value_type, structs)` is true when EITHER a param is
a growable container ref OR the return type is a container. That one predicate change lifted
the 95915b5 decline: the case that used to exit 139 (SIGSEGV) now returns 42 and is a real
differential rather than a decline fixture.

Still ahead in the region model: region PARAMS / `@r` annotations and explicit region
polymorphism, death-time, and the non-darray containers (dict/set, which are additionally
blocked behind error unions).

## `packed enum` / the AoS store — LANDED (scalar-payload subset)

This is the REAL AoS store, and it is a different subsystem from the payload enums landed
in d872f3c (those are a plain tagged union `{ i32, [N x i64] }`, no store involved).

The good news, read from stage0's `-emit llvm`: the store is **runtime-call based, not
open-coded** — the same shape as arena_alloc/realloc/free, which the backend already binds.
The heavy lifting lives in the runtime; the backend declares the externs and calls them.

Working stage0 program (verified, exit 42) — note EVERY piece of this is required:

    packed enum Node:
        Leaf(v: int)
        Pair(a: Node, b: Node)

    def build(owner: Arena) -> int:
        store: Node.Store[Local] = Node.Store(owner)
        result: mutable int = 0
        in store:
            n: Node = new Node.Leaf(v: 42)
            result <- match n:
                Node.Leaf(v): v
                Node.Pair(a, b): 0
        return result

    def main() -> int:
        region r(4096):
            return build(r)
        return 0

Types:

    %Node__Store = type { ptr, i64, ptr }            ; { arena, row_bytes, state }
    %PackedStoreIndexAllocResult = type { ptr, i32 } ; { row ptr, index }
    %Node = type { i32, [1 x i64] }                  ; the handle: tag + payload words

Runtime entry points:

    declare ptr @ctx_packed_store_state_new_variant_sparse(ptr arena, i64 row_bytes)
    declare %PackedStoreIndexAllocResult @ctx_packed_store_alloc_fixed_tagged_variant_sparse_result(ptr arena, ptr state, i32 tag)
    declare i32 @ctx_packed_store_read_variant_sparse_tag(ptr state, i32 index)
    declare i64 @ctx_packed_store_read_variant_sparse_word(i32 index, ptr state, i64 word)

Sequence for `Node.Store(owner)`: call state_new_variant_sparse(owner, row_bytes), then
build the store value with three insertvalues (arena, row_bytes, state). For `new
Node.Leaf(v: 42)`: extractvalue the arena/state out of the store, call
alloc_fixed_tagged_variant_sparse_result(arena, state, tag), `store %Node zeroinitializer`
into the returned row pointer, then write the payload words. A match reads the tag with
read_variant_sparse_tag and each payload word with read_variant_sparse_word.

Prerequisites this needs that the backend does NOT have yet:
1. ~~`region NAME(capacity):`~~ — DONE. The capacity arrives as clause[1], a span of the
   SOURCE text (not an Expr), and is parsed back out. Emits `new_region_backend(cap, 0)` with
   `begin`/`end` both starting at the backing; the lazy strategy word stays 0 because the
   backing already exists.
2. ~~`Arena` as a PARAMETER type~~ — DONE. `{ptr, ptr, i64, i64}` passed BY VALUE. A
   region's NAME is bound as an Arena local, so `build(r)` goes through the ordinary Ident
   path and emits stage0's `load %Arena, ptr %r` with no special case. The asymmetry stands:
   passable, not annotatable (`-> darray[i64] @owner` is still rejected).
3. ~~`new T.Variant(field: value)`~~ — DONE for the NAMED-FIELD half. `Shape.Circle(r: 42)`
   emits, with the label checked against the payload field's declared name. Note the parser
   LOWERS `new X(...)` to the constructor expression itself and DISCARDS both the `new`
   keyword and the `[region]` bracket — so `new[Node.Store] X(...)` currently reaches the
   backend indistinguishable from a plain `X(...)`. That bracket will matter for the store's
   explicit form, and is an AST gap of the same family as the others.
4. `in store:` — PARTIALLY DONE. `in NAME:` now activates an ARENA (borrowed: nothing frees
   it). The same construct must also accept a packed Store, which is what remains. Note
   activation is REQUIRED, not decorative: stage0 rejects a push in a function holding an
   explicit Arena param with "darray push requires an active in <arena>: scope", and a
   packed constructor with "requires an active in Node.Store: scope or explicit
   new[Node.Store]".

THE CORRECTION THAT MATTERED: a packed enum's VALUE is an **i32 store INDEX**, not the
`{i32, [N x i64]}` row. stage0 emits `%n = alloca i32` and `store i32 %packed.alloc.index`,
and the match passes that index to `read_variant_sparse_tag(state, index)`. The struct is
only the ROW LAYOUT, written at alloc time. I had it as the row until the IR said otherwise
— it would have been a silent miscompile, since the shapes are plausible either way.

Payload words are 1-BASED: word 0 is the tag, so the first payload field is
`read_variant_sparse_word(index, state, 1)`. The runtime returns an i64, so a narrower
payload is truncated to its own width.

Still ahead: typestate (`Store[Local]` vs `Store[Frozen]`), `freeze(move store)`, and
`common:` blocks with `@storage(inline)` — see the corpus in `Code/test_programs/`
(compiler_parallel_fixture.elisa, packed_enum_common.elisa). The typestate is currently
unmodeled and that is only sound because freeze/move themselves decline.

Sharp edge worth knowing: a RECURSIVE plain enum is auto-promoted to packed. `enum Node:
Leaf(v: i64) / Pair(a: Node, b: Node)` fails with "packed enum constructor Node.Leaf
requires an active in Node.Store: scope" even though it was never declared `packed`.

## Effects — NOTHING TO PORT (verified, not assumed)

`can[...]` has **no backend representation**. Verified by diffing stage0's own IR:

    def risky(n: i64) -> i64 can[Abort.Panic]:   ->  define i64 @risky(i64 %0) #0 { ... }
    def risky(n: i64) -> i64:                    ->  define i64 @risky(i64 %0) #0 { ... }

byte-identical modules; only `source_filename` differs. Effects are a SEMANTIC feature,
enforced entirely before codegen. "Port effects" was on the remaining list and is not backend
work at all — the only backend obligation is to NOT decline an effect-annotated function,
which is pinned by three fixtures (plain, multi-effect, and an `alias`ed effect).

## DWARF — scoped: one 490-line file, and `-g` does NOT reach `-emit llvm`

`compiler/src/backend/llvm_debuginfo.go` is 490 lines — a contained chunk, not a subsystem.

The sharp edge: **`-emit llvm -g` emits NO metadata** (0 `!` lines, same as without `-g`),
while `-emit obj -g` produces real DWARF (`DW_TAG_compile_unit`, verified with dwarfdump). So
the reference's IR-text path cannot be used as the oracle here the way it was for every other
feature — the ABI has to be read out of the OBJECT, or out of llvm_debuginfo.go directly.

That also breaks this port's test method: `emit_native` prints IR text, and the suite pipes it
through llc. Debug metadata WOULD survive that pipe, but there is no stage0 IR to diff it
against. DWARF is also invisible to an exit code, so `diff_case` cannot see it at all --
it needs `ir_case`-style checks against the metadata, or a dwarfdump comparison on the linked
object. Worth doing deliberately rather than by analogy with the other slices.

## `-Wperf` — LANDED (tagging + post-pass verdict)

`-Wperf` does not change codegen: `-emit llvm` with and without it is identical. But unlike
effects it is not purely semantic — `compiler/src/backend/llvm_autovec_verify.go` (260 lines)
attaches `!llvm.loop` metadata carrying an `elisa.autovec.expected` marker plus the source
position, and a POST-OPTIMIZATION pass finds loops that were lowered to be vectorizable and
then failed to. The marker rides in the IR so it survives inlining.

The reason the IR diff showed nothing: it only tags **comprehension build loops**. So the
`-Wperf` backend hook is gated behind comprehensions, which are NOT ported:

    xs: darray[i64] = [i for i in 0..<10]     # stage0: exit 42;  stage1: DECLINES

Comprehensions landed (b50e3d6), then the tagging (4707625), then the pass pipeline
(3e11a20), and now the post-pass verdict: verify_autovec_expectations walks every
terminator's `!llvm.loop` AFTER the passes and reports loops marked
`elisa.autovec.expected` that LLVM did not mark `llvm.loop.isvectorized`.

Gated in BOTH directions, which is the only test that means anything here: a verifier that
never warns passes "no false alarms", and one that always warns passes "catches it". Only
both together say it works.

Two traps found by testing the warning direction:
* An UNROLLED loop has no latch left, so the marker vanishes and there is correctly nothing
  to warn about. At 20 iterations LLVM unrolls the comprehension away entirely -- which made
  a silently-broken verifier look like a working one. The warning case needs a trip count
  too large to unroll (1000) plus a body that cannot vectorize (a recursive call).
* `false return if LLVMIsAMDNode(x) is node` is INVERTED -- `is` binds when PRESENT, so it
  rejected every real MDNode and the verifier never warned. Same inversion as the early
  lookup_function bug.

### Probe harness bug worth knowing

The one-liner probes used throughout this port grep stdout for `UNSUPPORTED` and call its
absence "emits". `emit_native` exits **1 on a PARSE ERROR** and **2 on a decline**, and a
parse error prints no `UNSUPPORTED` — so an invalid program reads as "EMITS". That is how
`fold(+, [...])` (which stage0 rejects outright: "unexpected token + in expression") looked
like a working feature for one probe. Check the EXIT CODE, not just the marker.

## DWARF and `-Wperf` — BOTH LANDED (the shared blocker is gone)

Both were on the remaining list as separate features. They are not: they are the same
architectural gap, and neither is a codegen feature.

stage1's backend is an **IR PRINTER**. `emit_native` builds a module and calls
`LLVMPrintModuleToString`; the suite pipes that text through `llc` and `clang`. There is no
target machine, no pass pipeline, no object emission — `llvm_c.elisa` binds neither
`LLVMTargetMachineEmitToFile` nor `LLVMRunPasses`.

Both features live on the far side of that gap:

* **DWARF** — `-emit llvm -g` emits ZERO metadata (verified: 0 `!` lines, identical to
  without `-g`), while `-emit obj -g` produces real DWARF (`DW_TAG_compile_unit`, via
  dwarfdump). So debug info never appears in the reference's IR-text output.
* **`-Wperf`** — same: no `!llvm.loop` / `elisa.autovec.expected` metadata in `-emit llvm`
  output at `-O0` OR `-O2`. And its verification is inherently post-optimization:
  `verifyAutovecExpectations` (llvm_autovec_verify.go:130) early-returns at
  OptimizationLevel0, then walks every terminator's `!llvm.loop` metadata AFTER the passes
  run, warning on loops marked `elisa.autovec.expected` that did not vectorize. stage1 does
  not run the passes — `llc` does, downstream and out of process.

HALF OF THAT IS NOW DONE (test/breadth/emit_obj.elisa + test/parity/backend_obj_smoke.sh):
stage1 builds a target machine and emits a native OBJECT itself via
LLVMTargetMachineEmitToFile — no `llc` in the pipeline. 5 gated cases (scalar, recursion,
darray, comprehension, struct) compile, link and run at 42.

Gotcha: `LLVMInitializeNativeTarget` is a `static inline` in Target.h with NO exported
symbol, so it cannot be bound — call the per-target functions it wraps
(LLVMInitializeAArch64TargetInfo/Target/TargetMC/AsmPrinter). That also makes the driver
arm64-only for now; the gate skips on other hosts rather than failing.

The PASS PIPELINE is now done too: `LLVMRunPasses(module, "default<O2>", tm, options)` runs
before emission. Note it takes a pipeline STRING, not a level enum, and returns an
LLVMErrorRef that is NULL on success -- so it binds as `-> void&?` and `is` narrowing reads
"an error is present".

The gate proves the passes actually RUN rather than no-op: every behavioural case would pass
identically at -O0 (an exit code cannot see optimization), so obj_optimizer asserts that
`add(40, 2)` is constant-folded into main. Verified by neutering the pipeline to "verify" and
watching it fail.

What REMAINS for DWARF is the DIBuilder surface (metadata built during emission). For
-Wperf, what remains is the autovec TAGGING at emit time plus the post-pass inspection --
the pipeline it needed to judge against now exists.

The original point still stands for both: That is a different kind of work from every slice landed
so far (all of which were "build the right IR"), and it also changes the test method — the
IR-text oracle that drove all 241 checks cannot see either feature, and `diff_case` cannot
either, since neither is observable in an exit code.

Doing the metadata TAGGING half without the pipeline is possible but pointless in isolation:
nothing in stage1 would consume it, and there is no stage0 IR to diff it against.
