# AST-shape and backend gotchas (stage1 semantic-check porting)

Reference-grade notes for agents porting stage0 diagnostics to the stage1
self-hosted frontend (`src/parser/*.elisa`, `src/semantic/*.elisa`). Every
entry below was checked against the actual source or actual compiler
behavior at the time of writing (elisac binary at `$HOME/.elisac/elisac`,
stage1 repo `Elisa-compiler` @ commit `1a7a726`). No entry is a guess.

Oracle setup used to verify these:

```bash
export ELISACORE_BIN="$HOME/.elisac/elisac"
export REPO_ROOT="$(pwd)"          # Elisa-compiler repo root
bash test/parity/build_parse_report.sh
printf '...' | ./build/parse_report
```

---

## 1. `catch EXPR:` desugars to `Stmt.Match` — walking `Stmt.Match` sees catch blocks too

**Trigger:** any semantic pass that pattern-matches on `Ast::Stmt.Match` to
find genuine `match` statements will ALSO see every `catch EXPR:` block,
because the parser desugars `catch` into the identical node.

**Why:** `catch_statement` in
`src/parser/parser_stmt_pattern.elisa:228-236` builds
`Ast::Stmt.Match(scrutinee, arms_buffer, catch_token.line)` — there is no
separate `Stmt.Catch` node. The catch-all arm `error e:` / bare `error:` is
parsed by `parse_pattern_primary`
(`src/parser/parser_stmt_pattern.elisa:105-110`) as
`Ast::Pattern.TypeBind("error", binder)` (binder `""` for a bare `error`).
`parse_catch_arm_block` (same file, lines 72-83) additionally rejects a
catch whose first arm is that error-binding pattern (stage0 parity), so a
well-formed `catch` always has at least one non-error arm before the
optional `error e:` arm.

**Correct idiom:** a check that means "real `match`, not a desugared
`catch`" must positively test for the catch shape and skip it — checking
`kind`/`kind is DiagnosticKind` is not enough, since both are literally
`Stmt.Match`. The established pattern (see gotcha #6) is:

```elisa
def match_arms_have_error_pattern(arms: darray[Ast::MatchArm]) -> bool:
    for arm in arms:
        is_error_arm: bool = match arm.pattern:
            Ast::Pattern.TypeBind(bound_type, binder): bound_type == "error"
            _: false
        if is_error_arm:
            return true
    return false
```

then `if not match_arms_have_error_pattern(arms): ...` before firing.

**Evidence:**
`src/parser/parser_stmt_pattern.elisa:236` (`Stmt.Match` construction from
`catch_statement`), `:109` (`Pattern.TypeBind("error", ...)`), `:78-80`
(reject leading error arm). Confirmed live via
`test_catch_arms_modeled`/`test_catch_requires_success_arm` in
`test/parity/parser_ast_test.elisa:416-508`, and reproduced directly:
`catch do_load(path):` with a `n:` arm and an `error e:` arm parses with 0
syntax errors and both arms show up as ordinary `MatchArm`s.

---

## 2. `mutable T` / `T&` / `lmut T` are ALL the same `Expr.Unary` node — not distinct AST variants

**Trigger:** any code assuming `mutable`, `&`, and `lmut` type-qualifiers
produce different AST node *kinds* that must be unwrapped one at a time.

**Why:** there is exactly one wrapper shape,
`Ast::Expr.Unary(operator: TokenKind, operand: Expr, line: u32)`
(`src/parser/parser_tokens.elisa:72`). The parser's `unary_expression`
(`src/parser/parser_expr_ops.elisa:201-227`) treats
`Not/Bang/Tilde/Minus/Plus/Ampersand/Mutable/Lmut/Static/Heap/Stack/Tail`
as siblings in one `elif kind in {...}` branch (line 215) and all of them
build `Ast::Expr.Unary(operator_kind, operand, token.line)` (line 222) —
the only thing that differs is the `operator` field's `TokenKind` value.
Postfix `T&`/`T&&`/... (reference-type suffix, as opposed to prefix
address-of `&x`) is handled separately in `postfix_expression`
(`src/parser/parser_expr_ops.elisa:124-141`) but ALSO builds
`Ast::Expr.Unary(TokenKind.Ampersand, active, token.line)` — same node
shape again. Postfix `T?` (optional) is likewise a `Unary` with
`operator == TokenKind.Question` (line 117-122).

**Correct idiom:** unwrap generically by matching `Expr.Unary(operator,
operand, line)` and checking `operator` against the specific `TokenKind`s
that matter, recursing on `operand` for chains.

**CRITICAL — `bare_type_name` unwraps ONLY `Mutable`, and this is
deliberate, NOT a bug to "fix":** `bare_type_name` in
`src/semantic/resolve_types.elisa:24-32` recurses through `Unary` only
when `operator == TokenKind.Mutable`, and returns `""` for `Ampersand`
(`&`), `Lmut`, optionals, generics, and everything else:

```elisa
def bare_type_name(expression: Ast::Expr) -> sview:
    if expression is Expr.Unary(operator, operand, unary_line):
        if operator == TokenKind.Mutable:
            return bare_type_name(operand)
        return ""            # refs, optionals, generics, user types — all skipped
    if expression is Expr.Ident(name, ident_line):
        return name
    return ""
```

Do **not** extend it to unwrap `Ampersand`/`Lmut`. ~35 call sites depend
on its "bare **by-value** type name" contract specifically to distinguish
`next: Node` (embed → infinite size) from `next: Node&` (ref → finite).
Collapsing that distinction produces confirmed false positives in at
least four smokes — `struct_layout_smoke.sh` (self-recursion check flags
`next: Node&` as directly self-recursive), `cast_smoke.sh`,
`assign_type_smoke.sh`, `field_assign_smoke.sh` — verified by building
the patched helper and running the parity suite.

**If a check genuinely needs the type name *through* a ref**, use a
SEPARATE ref-aware helper that only that check opts into — see
`bare_type_name_through_ref` in
`src/semantic/check_field_immutable_assign.elisa:19-27`, which unwraps
`Mutable`/`Ampersand`/`Lmut`. That is the correct pattern, not a
workaround: ref-through resolution is per-check opt-in, never the shared
default.

**Evidence:** `src/parser/parser_tokens.elisa:72`;
`src/parser/parser_expr_ops.elisa:215,222` (prefix);
`:124-141` (postfix `&`); `src/semantic/resolve_types.elisa:24-32`
(by-value-only unwrap, current tree);
`src/semantic/check_field_immutable_assign.elisa:19-27` (the ref-aware
opt-in helper).

---

## 3. f-strings build an owned `dstr` via `__fstr(...)`, never an `sview`

**Trigger:** storing an f-string's value into an `sview`-typed field (e.g.
a `Diagnostic` field) or otherwise treating `f"...{x}..."` as if it were a
borrowed view.

**Why:** the parser desugars every f-string — interpolated or not — to a
call `__fstr(part0, part1, ...)`
(`src/parser/parser_expr_literals.elisa:192-200`), and stage0's analyzer
types that builtin call's result as a fresh `dstr` (a `DArrayType` of
`u8`), explicitly noting it allocates:
`compiler/src/semantic/analyzer_expr_builtin_fstring.go:33-40` (Go stage0
repo) — `dstrType := &DArrayType{Elem: a.namedTypes["u8"], ..., SurfaceName: "dstr"}`
and the call is stamped with `Memory.Allocate` permission. So `f"..."` has
exactly one type, the owned formatted string, "whether or not it
interpolates" (comment at `parser_expr_literals.elisa:193-194`) — there is
no static-literal-sview shortcut.

Meanwhile `Ast::Diagnostic` (`src/semantic/semantic_types.elisa:516-529`)
is entirely `sview` fields (`name`, `expected`, `actual`) — it holds
**raw, unowned spans into the source text**, not formatted strings. There
is no field that could hold an owned `dstr` without a lifetime/ownership
mismatch.

**Correct idiom:** checks store the raw `sview` pieces (offending name,
expected/actual type text) on the `Diagnostic`, and the message is
assembled with an f-string only at render time, one call site per
`DiagnosticKind`, e.g.
`src/semantic/semantic_api.elisa:174`:
`buffer.extend(f"undefined name '{diagnostic.name}'")`. Never try to
pre-format a message and stash it on a `Diagnostic`.

**Evidence:** `src/parser/parser_expr_literals.elisa:192-200`;
`compiler/src/semantic/analyzer_expr_builtin_fstring.go:33-40` (stage0,
Elisa-core repo); `src/semantic/semantic_types.elisa:516-529`;
`src/semantic/semantic_api.elisa:174-199` (render-time f-string assembly).

---

## 4. `TypeKind.String` conflates `cstr`/`sview`/`dstr` — "String has no fields" is FALSE

**Trigger:** any soundness argument of the form "primitive types have no
fields, therefore a check may fire on `object.field` whenever
`object_type.kind` is a scalar-ish kind including `String`".

**Why:** the whole inferred-type model is deliberately coarse:
`TypeKind` (`src/semantic/semantic_types.elisa:26-34`) is exactly
`{Unknown, Void, Int, Float, Bool, Char, String, Named}` — comment at
lines 37-39 says richer shape (tuples, refs, optionals, generics) "is
added as the engine grows; until then those infer to `Unknown`." `String`
here stands for *any* of `cstr`/`sview`/`dstr`, and `sview`/`dstr` are
real structs with real fields (`sview.len`, `dstr.count`, etc., defined in
the runtime/backend, not user `.elisa` source — they're compiler
builtins). `check_field_access_on_primitive.elisa`'s header comment
(lines 1-4) states the correct boundary explicitly: "Strings/structs/enums
(Named) have fields/methods and Unknown is bottom, so both are
deliberately excluded" — the check only fires for
`Int`/`Float`/`Bool`/`Char` (`src/semantic/check_field_access_on_primitive.elisa:27-29`).

**Correct idiom:** never use `TypeKind.String` as evidence that a value
has no fields. A `FieldAccessOnPrimitive`-shaped check must enumerate the
firm scalar kinds explicitly (`Int`, `Float`, `Bool`, `Char`) and exclude
`String`, `Named`, and `Unknown`.

**Evidence:** `src/semantic/semantic_types.elisa:26-39`;
`src/semantic/check_field_access_on_primitive.elisa:1-29`.

---

## 5. `-> void error[E]` and `-> void` are IDENTICAL in the symbol table

**Trigger:** any check keyed on `sym.return_type == "void"` (or a scrutinee
type of `TypeKind.Void`) meaning "this function returns nothing" — it will
also match a fallible function whose SUCCESS type is void.

**Why:** `parse_signature_clauses` discards the `error[...]` error-set
clause entirely during parsing (it's "consumed without modeling" — see
`src/parser/parser_types.elisa:183-186`), so a function declared
`-> void error[E]:` records the exact same `return_type` text (`"void"`)
as one declared plain `-> void:`. This is spelled out explicitly in
`src/semantic/check_void_match_scrutinee.elisa:7-16`.

Combined with gotcha #1 (catch → `Stmt.Match`): a `catch fallible_call():`
where `fallible_call` returns `void error[E]` has a scrutinee that infers
to `TypeKind.Void` — structurally indistinguishable from `match
some_void_call():`, a genuine bug. The only usable signal is the arm
shape from gotcha #1 (`Pattern.TypeBind("error", ...)` arm present ⇒ it's
a catch, not a real void-scrutinee match).

**Correct idiom:** any "void scrutinee"/"void value used as X" check must
call `match_arms_have_error_pattern(arms)` (or equivalent) first and
bail out if true, exactly as
`src/semantic/check_void_match_scrutinee.elisa:94-98,133-137` does:

```elisa
Expr.Match(scrutinee, arms, line):
    if not match_arms_have_error_pattern(arms):
        scrutinee_type: InferType = infer_expression_type(scrutinee, ...)
        if scrutinee_type.kind == TypeKind.Void:
            table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.VoidMatchScrutinee, ...})
```

**Evidence:** `src/parser/parser_types.elisa:183-186` (error-set clause
discarded); `src/semantic/check_void_match_scrutinee.elisa:1-16` (comment
spells out the exact mechanism) and `:94-101,133-141` (the guard in
practice).

---

## 6. `TypeKind.Unknown` is a deliberate bottom — never treat it as a firm type

**Trigger:** a check that flags "any non-numeric type" or "any type that
isn't X" without excluding `Unknown`, firing on expressions the inference
engine simply couldn't classify yet (tuples, refs, optionals, generics,
lambda results, etc. — see gotcha #4's `TypeKind` list).

**Why:** `TypeKind.Unknown` means "the (deliberately small) inference
engine doesn't know," not "this value has no type" or "this is some odd
primitive." Existing checks are explicit about this:
`check_void_operand.elisa:12` — "Never fires on `TypeKind.Unknown` — only
a firm `TypeKind.Void` triggers"; `check_void_unary_operand.elisa:9` says
the same. `resolve_loops.elisa:9,30` treats `Unknown` as "assume OK,
don't flag" for iterability.

**Correct idiom:** every new "is this the wrong shape/type" check needs an
explicit `if type.kind == TypeKind.Unknown: return`/skip, or must
structure the condition as a positive match against only the firm kinds
it cares about (never an `!=` against one excluded kind).

**Evidence:** `src/semantic/check_void_operand.elisa:12`;
`src/semantic/check_void_unary_operand.elisa:9`;
`src/semantic/resolve_loops.elisa:9,30`.

---

## 7. `Expr.Call(callee: Expr.Field(...))` is a method call / UFCS / cast — never a real field access

**Trigger:** a check that walks `Expr.Field(object, field, line)` looking
for genuine field-access semantics (unknown field, field-access-on-
primitive, etc.) and fires on `recv.Name()` because `recv.Name` parses as
a `Field` node.

**Why:** postfix call unifies method calls, UFCS, and casts: `recv.Name()`
parses identically whether `Name` is a struct method, a free function
taking `recv` by UFCS, or (if `Name` is a type name) a value cast — the
callee is always `Expr.Field(recv, "Name", line)` wrapped in
`Expr.Call(callee, arguments, argument_names, line)`. Both
`check_field_access_on_primitive.elisa:18-21` and
`check_unknown_field_access.elisa:18-24` special-case this identically:

```elisa
Expr.Call(callee, arguments, argument_names, line):
    if callee is Expr.Field(call_object, call_field, call_line):
        table <- walk_..._(call_object, table, ...)   # walk the receiver only
    else:
        table <- walk_..._(callee, table, ...)
    for argument in arguments |table|:
        table <- walk_..._(argument, table, ...)
```

i.e. when a `Field` is the direct callee of a `Call`, the check recurses
into the receiver but explicitly skips applying the field-access check to
that `Field` node itself.

**Correct idiom:** any AST walk that treats bare `Expr.Field` as "a field
access to validate" must, in its `Expr.Call` arm, detect
`callee is Expr.Field(...)` and route around the field-access logic for
that specific node (still walking the inner receiver expression
normally).

**Evidence:** `src/semantic/check_field_access_on_primitive.elisa:4-6,18-21`;
`src/semantic/check_unknown_field_access.elisa:4-6,18-24`.

---

## 8. `Expr.Binary` right operand of `is`/`as` is a type/pattern target, not a value — don't resolve it as a reference

**Trigger:** a name-resolution or value-typed walk over `Expr.Binary(left,
operator, right, line)` that unconditionally recurses into `right`,
misreading the RHS of `x is SomeEnum.Variant` or `x as SomeType` as an
undefined-name use of `SomeEnum`/`SomeType`.

**Why:** `is`'s right side is a refinement target/pattern (built via the
same dotted-path/variant syntax as `Pattern.Variant`/`TypeBind`, just
spelled as an `Expr` in binary-operator position) and `as`'s right side is
a type expression — neither is a value reference. `resolve_expr.elisa:429-434`
is explicit:

```elisa
Expr.Binary(left, operator, right, line):
    table <- walk_expression(left, table, bound, bound_mutability)
    # The right operand of `is` (a refinement target/binding) and `as`
    # (a type) is not a value reference, so it isn't resolved here.
    if operator != TokenKind.Is and operator != TokenKind.As:
        table <- walk_expression(right, table, bound, bound_mutability)
```

The same `if operator != TokenKind.Is and operator != TokenKind.As:` guard
recurs verbatim across the other expression-walking checks (e.g.
`check_field_access_on_primitive.elisa:14-17`,
`check_unknown_field_access.elisa:14-17`).

A parallel case: `Expr.Index(object, index, line)` where `object` is
`Expr.Field(_, "cast"/"ref"/"specialize", _)` — there `index` is a type
argument (`x.cast[T]`), not a value index, gated by
`index_receiver_is_type_application` (`resolve_expr.elisa:351-355`).

**Correct idiom:** any expression walk that recurses into both sides of
`Expr.Binary` must special-case `operator == TokenKind.Is` / `.As` and
skip the right side; any walk into `Expr.Index` must check
`index_receiver_is_type_application(object)` before treating `index` as a
value.

**Evidence:** `src/semantic/resolve_expr.elisa:351-355,423-434`.

---

## Investigated but NOT included (could not verify)

**"`x is SomeEnum.PayloadlessVariant` inside `if` compiles in stage1 but
the Go backend dies with `unsupported expression *ast.TypeExprExpr`."**
Could not reproduce against the current `elisac` binary
(`$HOME/.elisac/elisac`). Probed all of: `if x is Enum.Variant:` (plain
and packed-adjacent), assignment `b: bool = x is Enum.Variant`, compound
conditions (`if a and x is Enum.Variant:`), `while x is Enum.Variant:`,
ternary (`1 if x is Enum.Variant else 0`), a value-position `return x is
Enum.Variant`, across `-emit obj/llvm/lowered/semantic`, `-O0`/`-O2`,
`-permissive` and strict — all compiled cleanly (exit 0, valid object
code). Reading the Go backend (`compiler/src/backend/...`) confirms
`*ast.TypeExprExpr` is *not* handled in the generic `emitExpr` switch's
`default:` case
(`llvm_exprs_llvmvalueiszeroconstant_..._constenummemberinfo.go:456-457`,
`"unsupported expression %T"`), but `emitBinaryExpr` special-cases
`TOKEN_IS` unconditionally and dispatches to a dedicated `emitIsExpr`
before ever reaching the generic switch on the RHS
(`llvm_exprs_emitlistlitexpr_to_emitisexpr_..._emitmembershipcomparevalueandexpr.go:1442-1447`),
and `if`/`while` conditions also get a dedicated
`conditionTargetPattern`/`emitConditionPatternTestAndBind` path
(`llvm_bodies_conditiontargetpattern_to_emitconditionpatterntestandbind.go`).
So every position an `is`-test can appear in today routes around the
unhandled `default:` case. This may have been a real, now-fixed bug, or
may require a trigger not tried here (e.g. a specific packed-enum
attribute syntax that didn't parse in this compiler build). Do not carry
this gotcha forward without a fresh, successful repro.
