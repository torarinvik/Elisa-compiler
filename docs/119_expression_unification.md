# Docs/119 — expression unification forms

This is the stage1-facing specification for the expression forms covered by
`test/parity/docs119_forms_smoke.sh` and the runtime checks in
`test/parity/block_expressions_smoke.sh`. It records the syntax and semantic
boundaries that the self-hosted frontend preserves.

## 1. One expression grammar

An expression may be a literal, call, operator expression, block value, or
value-producing control form. A value form may appear anywhere an expression
is accepted, including an assignment RHS and a return value. Every value form
parses to an `Ast.Expr` and resolves names in its lexical scope.

## 2. Bare block values

An assignment can introduce an indented block without an explicit keyword:

```elisa
value: i64 =
    local: i64 = 40
    local + 2
```

Leading statements execute in block scope; the final expression is the block
value. The tail is evaluated before block-local defers and destructors run.
Locals declared inside the block do not leak out or replace an outer binding
with the same name. Missing values are handled by the normal value-form diagnostics.

The annotation can be omitted when the result can be inferred. `<-` evaluates
the whole block before updating an existing mutable binding:

```elisa
answer =
    half: i64 = 21
    half * 2

remaining: mutable i64 = 100
remaining <-
    consumed: i64 = answer + 8
    remaining - consumed
```

Prefer a block when a value needs intermediate calculations or a local mutable
accumulator. Keep those temporaries inside and expose the final result as an
immutable binding. A simple expression does not need an extra block. Reading
outer bindings is allowed; mutation requires a capture or the state-threading
assignment form below.

The compiler's allocation decisions in `codegen_memory_speed.elisa` use this
style for the permitted iterable, stack budget, and selected buffer name.


## 3. Conditional and loop values

Indented `if`/`else` branches can produce a value. A value-form `if` requires
a final `else` branch. Loop expressions use an accumulator header:

```elisa
total: i64 =
    for item in xs |acc = 0| -> acc:
        acc <- acc + item
```

The header may type the accumulator (`|acc: u64 = 0|`) and list captured
outer mutables (`|acc = 0, total|`). A bitwise `|` inside the iterable is an
operator, not a header delimiter; recognition is structural and top-level.

## 4. Capture and mutation rules

`|name|` captures an outer binding for mutation inside a value block. The
binding must exist and be mutable. Mutation of an uncaptured outer binding is
rejected by the value-block checker. Captures are lexical names carried in the
block expression's `captures` side-table.

### In-place state-threading assignments

A bare `<-` block can update fields of its assignment target and yield that
same target on every branch:

```elisa
structs <-
    structs.cond_bind_depth <- structs.cond_bind_depth - 1
    if structs.cond_bind_depth == 0:
        structs with {cond_bind_names <- [], cond_bind_slots <- [], cond_bind_types <- []}
    else:
        structs
```

This form implicitly captures `structs` for mutation. Its field writes execute
in place; the identity result does not load or store the whole record, even at
`-O0`. Block locals remain scoped and block cleanup runs once on exit. A bare
identifier followed by `with { ... }` inside a value block updates its fields
in source order and yields that identifier.

Recognition requires a direct field update, identity results on all branches,
and no shadowing declaration of the target. Leading statements currently
support simple declarations, assignments, and defers. Other statement shapes
and conditions introducing bindings are conservatively excluded. Other outer bindings still require captures.
Explicitly captured blocks retain their ordinary value-assignment semantics;
this rule does not turn arbitrary record-valued assignments into mutations.
The condition-binding cleanup in `codegen_condition.elisa` and
`codegen_stmt_match_switch.elisa` uses this form.

## 5. `rebind`

`rebind` explicitly threads a value back into existing mutables and can bind a
fresh target with an annotation:

```elisa
rebind total, applied: i64 =
    total + delta, delta
```

Targets are parsed before the RHS, which is an expression or block value. The
frontend preserves target names and resolves the RHS; backend move and
ownership lowering are separate stages.

## 6. Required parity checks

Valid forms must parse cleanly, and name resolution must descend into block
bodies, loop headers, captures, and rebind RHS expressions. The focused smoke
also checks that a bitwise `|` in an iterable is not misread as a header and
that `src/` plus `elisacore_std/` has no parse false positives.

Run both the frontend checks and the compiled runtime checks:

```sh
test/parity/docs119_forms_smoke.sh
test/parity/block_expressions_smoke.sh
```

The implementation is in `src/parser/parser_core.elisa`,
`src/parser/parser_stmt.elisa`, `src/parser/parser_stmt_control.elisa`, and
`src/semantic/resolve_value_blocks.elisa`.

## Collection updates in `with`

`darray += element` appends exactly one element in place. It is a statement,
not an expression returning a reference. Numeric `+=` retains numeric addition.
Use `.extend(elements)` for multiple elements; `+=` never implicitly flattens
an array-valued element or accepts a batch in place of a scalar element.

Field updates support the same operation:

```elisa
structs <-
    if structs.cond_bind_depth > 0:
        structs with {
            cond_bind_names += name,
            cond_bind_slots += slot,
            cond_bind_types += slot_type,
        }
    else:
        structs
```

`with` yields its receiver; `<-` replaces a field, while `+=` updates it.
Fields execute in source order. A complex statement receiver, such as
`rows[next_index()] with {items += value}`, is evaluated once. Appending uses
the collection's existing growth-region and mutability rules, including when
it grows through a reference parameter. Bulk append requires explicit `extend`.

## Optional scrutinees in value matches

`match opt:` in value position accepts `null`, binder, and `_` arms, each with an
optional guard. `_` covers absence as well as any payload; a binder's guard runs
only on a present payload; a bare `null` arm yields the empty optional. Without
`_`, both a `null` arm and an unguarded binder are required, otherwise
`non-exhaustive match expression over T?; …` is reported (docs/122 §4). The same
shapes lower in statement position, and a value block yielding such a match is
checked through its tail. Verified 2026-09-14 by
`test/parity/block_expressions_smoke.sh` (stage0/stage1 runtime parity at O0/O2,
byte-identical rejection text).
