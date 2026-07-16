# Docs/119 — expression unification forms

This is the stage1-facing specification for the expression forms covered by
`test/parity/docs119_forms_smoke.sh`. It records the syntax and semantic
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
value. Missing values are handled by the normal value-form diagnostics.

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

The authoritative executable check is:

```sh
test/parity/docs119_forms_smoke.sh
```

The implementation is in `src/parser/parser_core.elisa`,
`src/parser/parser_stmt.elisa`, `src/parser/parser_stmt_control.elisa`, and
`src/semantic/resolve_value_blocks.elisa`.
