# Stage0→stage1 diagnostic-port batch primer (template)

## How the orchestrator uses this

Each porting batch adds one or more `DiagnosticKind`s to the stage1 self-hosted
frontend (`src/semantic/`) that stage0 (the Go compiler at `$ELISA_CORE/compiler`)
already reports but stage1 is silent on. Previously each batch got a fresh,
hand-written agent brief that re-derived the same wiring points, oracle protocol,
and gotchas every time (~90% identical across batches 7-11). This file is that
stable core, checked in once.

To start a new batch:

1. Copy the **"Per-batch brief"** section below into a fresh prompt.
2. Fill in every `<<PLACEHOLDER>>`: the diagnostic name (snake_case + PascalCase),
   the fire-condition prose, the stage0 evidence it fires today, the stage1
   evidence it's currently silent, and the exact render-message wording.
3. Append the **"Fixed core"** section verbatim (wiring points, oracle protocol,
   engine helpers, skeleton, gotchas, self-audit checklist, report format) —
   do not paraphrase it; it is accurate to the CURRENT tree as of the commit
   this file was authored against.
4. Hand the assembled prompt to the porting agent.

If the fixed core drifts from the tree (a wiring point moves, a helper is
renamed, a new gotcha is discovered), fix it HERE, in this one file, not in a
per-batch copy.

---

## Per-batch brief (fill in before sending)

- **Diagnostic name**: `<<snake_case_name>>` / `<<PascalCaseName>>`
  (e.g. `field_immutable_assign` / `FieldImmutableAssign`)
- **Fire condition** (prose, precise enough to code from): `<<...>>`
- **Stage0 evidence it fires today**: `<<exact stage0 error string + how you
  triggered it, e.g. via $ELISACORE_BIN -emit semantic on a small fixture>>`
- **Stage1 evidence it's currently silent**: `<<parse_report output on the same
  fixture, showing the diagnostic is absent from the "D <n>" list>>`
- **Render message wording** (goes verbatim into `diagnostic_message`): `<<...>>`
- **Severity**: `<<1=Error / 2=Warning / 4=Hint>>` (match stage0's severity for
  this class of finding; hints are stage1-only extras stage0 doesn't have)
- **Next `code_of_diag_kind` ordinal**: `<<N>>` (one past the current highest;
  see wiring point 6 below — as of this writing the highest is 122)

---

## Fixed core (paste verbatim)

### The 6 wiring points for a new `DiagnosticKind`

A new diagnostic touches exactly six places. Miss one and either the compiler
won't build, or the check will silently produce no visible diagnostic text, or
the smoke harness (`resolve_smoke.elisa`) won't classify it.

1. **`src/semantic/semantic_types.elisa`** — add a new member to the
   `const enum DiagnosticKind of u8:` block (starts at line 67; the current
   last member is `FieldImmutableAssign` at line 509, immediately before the
   `struct Diagnostic` declaration at line 516). Give it a doc comment in the
   same style as its neighbors: what fires it, what `name`/`expected`/`actual`
   carry (if anything), and the soundness/parity note. The `Diagnostic` struct
   itself (line 516-529: `name: sview`, `line: u32`, `kind: DiagnosticKind`,
   `expected: sview`, `actual: sview`, `expected_count: u32 = 0`,
   `actual_count: u32 = 0`) almost never needs to change — reuse `name` /
   `expected` / `actual` for context; only add new fields if no existing field
   shape fits (rare; grep for `expected_count`/`actual_count` usage first).

2. **`src/semantic/semantic_api.elisa`, `diagnostic_message`** (match starts
   line 169) — add a `DiagnosticKind.<<PascalCaseName>>:` arm immediately
   before the final `return buffer` (currently line 476, right after the
   `FieldImmutableAssign` arm at line 474-475). This match has **no wildcard
   arm** — it is exhaustive by design, so a kind added without a message here
   is a stage1 **compile error**, not a silent fallback. Use an f-string:
   `buffer.extend(f"...{diagnostic.name}...")`.

3. **`src/semantic/semantic_api.elisa`, `diagnostic_severity`** (match starts
   line 482) — add a `DiagnosticKind.<<PascalCaseName>>: <<1|2|4>>` arm
   immediately before the blank line ending the match (currently line 607,
   right after `FieldImmutableAssign: 1`). Also exhaustive/no wildcard.

4. **`src/semantic/semantic_api.elisa`, `def check(...)`** (line 35-128) —
   append `table <- check_<<snake_case_name>>(file.top_decls, table)` to the
   ordered call chain inside the `if file.errors.count == 0:` block, right
   before `return table` (currently line 127, after
   `check_field_immutable_assign`). Order within the chain doesn't affect
   correctness (each check independently appends to `table.diagnostics`) but
   keep it appended at the END to match the batch-ordering convention already
   visible in the file (batches 7/8/9/10/11 each landed as a contiguous run).

5. **`src/semantic/semantic.elisa`** — add
   `include "./check_<<snake_case_name>>.elisa"` to the ordered `include`
   list, immediately before `include "./semantic_api.elisa"` (currently the
   very last include, line 146, right after
   `include "./check_field_immutable_assign.elisa"`). `semantic_api.elisa`
   must be the LAST include (it's the facade that calls everything above it).

6. **`test/parity/resolve_smoke.elisa`, `def code_of_diag_kind(...)`** (match
   starts line 281) — add
   `Semantic::DiagnosticKind.<<PascalCaseName>>: <<N>>` as a new arm. `N` must
   be a fresh integer one past the current highest in-use code (as of this
   writing, the highest assigned code is 122, for `FieldImmutableAssign`; the
   next new kind should use 123). This oracle is consumed by
   `test/breadth/run.sh`'s corpus sweep and by ad-hoc probes; it does not need
   to match any stage0 numbering — it is stage1-internal.

None of these six edits touch the parser, the lexer, or the LLVM/Go backend.
A new diagnostic is a pure `src/semantic/` + one-line `test/parity/` change.

### The oracle protocol

Stage1 is a self-hosted Elisa frontend (lexer/parser/semantic in
`src/{lexer,parser,semantic}/*.elisa`), currently BUILT and RUN by stage0 (the
Go compiler in `$ELISA_CORE/compiler`, i.e. `Elisa-core/compiler`). Do not
confuse the two:

- **`$ELISACORE_BIN -emit semantic <file>`** (stage0, Go) — tells you whether
  stage0 already reports the diagnostic today. This is PARITY evidence only —
  it is never proof of what stage1 does.
- **stage1's own oracle** — the ONLY valid signal for "does stage1 report
  this":
  ```bash
  export REPO_ROOT="$(pwd)"              # this repo's root
  # ELISA_CORE defaults to "$REPO_ROOT/../../Go projects/Elisa-core" (the
  # conventional sibling checkout) if unset — override only if yours lives
  # elsewhere. resolve_elisac.sh then builds (or reuses a pinned
  # $ELISACORE_BIN) the stage0 compiler and exports ELISACORE_BIN.
  source test/parity/resolve_elisac.sh   # builds/pins $ELISACORE_BIN (stage0)
  bash test/parity/build_parse_report.sh # compiles test/breadth/parse_report.elisa
                                          # WITH stage0, producing build/parse_report —
                                          # a NATIVE binary that runs STAGE1's own
                                          # lexer -> parser -> Semantic::check
  echo '<source>' | ./build/parse_report
  ```
  Output format (see `test/breadth/parse_report.elisa`):
  ```
  P <n>                                 # parse-error count
    <kindcode> L<line> <context-token>  # one per parse error, if n>0
  D <n>                                 # semantic diagnostic count
    L<line> <rendered message>          # one per diagnostic, if n>0
  ```
  The existing `test/parity/*_smoke.sh` scripts (e.g. `match_pattern_smoke.sh`)
  are worked examples of this exact pattern: build `parse_report` once, then
  `printf '<source>' | "$RPT"` and `grep` the output for expected wording.

`ELISACORE_BIN -emit semantic` runs STAGE0. `parse_report` runs STAGE1. Only
`parse_report`'s `D <n>` / message lines are evidence for whether YOUR new
check fires in stage1.

### The type-inference engine surface (`src/semantic/resolve_types.elisa`)

The engine assigns a structured `InferType{kind: TypeKind, name: sview}` to an
expression from its AST shape plus a flat per-function local-type table. It is
a SOUND SUBSET: anything it can't model infers `TypeKind.Unknown`, and
`Unknown` must NEVER be used to flag a diagnostic — that is stage1's
zero-false-positive guarantee. If you find yourself writing
`if inferred.kind == TypeKind.Unknown: <report anyway>`, stop — that is
exactly the bug class this rule exists to prevent.

```
const enum TypeKind of u8:
    Unknown
    Void
    Int
    Float
    Bool
    Char
    String
    Named

struct InferType:
    kind: TypeKind
    name: sview   # struct/enum name when kind == Named, else empty
```

Core entry point:

```
def infer_expression_type(expression: Ast::Expr, names: darray[sview]&,
                           types: darray[sview]&, table: SymbolTable&) -> InferType
```
(`names`/`types` are the parallel per-function local-type arrays you build
yourself — see the standalone-pass skeleton below.)

Helpers actually used by existing checks (grep them before assuming a
signature — this list is a snapshot):

- `primitive_type(kind: TypeKind) -> InferType` — build a nameless InferType.
- `type_of_name(type_name: sview) -> InferType` — map a declared bare type
  NAME (from `bare_type_name`) onto an InferType (primitive or `Named`).
- `family_of_kind(inferred_type: InferType) -> sview` — coarse family string
  `"int"|"float"|"bool"|"string"|"char"|""` (empty = unknown/void/named).
- `family_of_type_name(type_name: sview) -> sview` — same, from a bare type
  name rather than an InferType.
- `infer_family(expression, names, types, table) -> sview` — `infer_expression_type`
  then `family_of_kind` in one call.
- `kind_is_firm_non_bool(inferred_type: InferType) -> bool`
- `kind_is_firm_non_numeric(inferred_type: InferType) -> bool` — true only for
  `Bool`/`String`; `Char` is numeric-adjacent (char arithmetic is legal) and
  never flags; `Int`/`Float`/`Unknown`/`Named` never flag.
- `comparison_group(inferred_type: InferType) -> u8` — `1`=bool, `2`=string,
  `3`=numeric (int/float/char mutually comparable), `0`=not firm-comparable
  (Unknown/Void/Named — never flag). Two firm operands in different non-zero
  groups can never be `==`.
- `literal_never_fits(lit_kind: sview, type_name: sview) -> bool` — the
  oracle-verified impossible-pair matrix for a LITERAL initializer against a
  declared primitive type name (adaptive pairs like int→char, char→int,
  int→float, float→int are legal and return false).
- `firm_never_fits(value_family: sview, type_name: sview) -> bool` — same
  question for a FIRM (non-literal) expression's family against a declared
  primitive; only the hard bool/string/numeric walls fire.
- `local_type_of(names: darray[sview]&, types: darray[sview]&, name: sview) -> sview`
  — recorded bare type name of a local/param, `""` if unknown.
- `note_local_type(names: mutable darray[sview]&, types: mutable darray[sview]&, name: sview, type_name: sview) -> void`
  — record (or invalidate to `""` on a type conflict) a local's bare type.
- `bare_type_name(expression: Ast::Expr) -> sview` — bare type-expression name,
  seeing through `mutable`/`&`/`lmut` wrappers; `""` for anything else
  (generics, qualified names, etc.).
- `field_type_of(table: SymbolTable&, owner: sview, field_name: sview) -> sview`
  — declared bare TYPE of a registered struct field ("" if unregistered).
- `field_is_mutable(table: SymbolTable&, owner: sview, field_name: sview) -> bool`
- `function_return_type(table: SymbolTable&, function_name: sview) -> sview`
  — declared bare return-type name of a uniquely-named function.
- `function_parameter_type_at(table: SymbolTable&, function_name: sview, position: usize) -> sview`
  (in `check_literal_arg_type_mismatch.elisa`) and the firm-argument sibling
  `function_parameter_type_at_firm` (in `check_firm_arg_type_mismatch.elisa`).
- `direct_function_count(table: SymbolTable&, function_name: sview) -> u32`
  (in `resolve_expr.elisa`) — used to gate call-site checks to UNIQUELY-named
  (non-overloaded) functions only; overloaded names must bail.
- `enum_is_known(enum_name: sview, table: SymbolTable&) -> bool` (in
  `resolve_types.elisa`) — `any owner in table.enum_variant_owner where owner == enum_name`.

**RULE, stated again because it is the whole ballgame**: never report a
diagnostic when the relevant `infer_expression_type`/`infer_family` result is
`TypeKind.Unknown` (or its family-string projection `""`). Every existing
type-flow check (batches 7-11) is worded in its own header comment as "Sound:
fires only when X is firmly known" — copy that discipline into your own
header comment.

### The standalone-pass template pattern

Copy the shape of `src/semantic/check_literal_comparison_impossible.elisa` (a
plain, self-contained example) or `src/semantic/check_field_immutable_assign.elisa`
(a batch-11 example that leans on the type-inference engine, including its own
local `bare_type_name_through_ref` helper where the shared `bare_type_name`
wasn't enough — it's fine to add a small file-local helper when the shared one
doesn't fit, as long as you don't touch the shared helper's contract for other
checks). Skeleton:

```
# One-paragraph header comment: what fires it, what name/expected/actual carry,
# and the SOUND SUBSET boundary (what is deliberately excluded and why).

extend Semantic:
    private:
        # Walk expressions, threading (var_types, type_names) — YOUR own local
        # per-function tables, built fresh per Decl.Func the same way
        # check_literal_comparison_impossible.elisa does.
        def walk_expression_for_<<name>>(expression: Ast::Expr, table: lmut SymbolTable,
                                          var_types: mutable darray[sview]&,
                                          type_names: mutable darray[sview]&) -> void:
            can Memory.Allocate, Abort.Panic:
                match expression:
                    # ... recurse into every Expr shape that can contain the
                    # pattern you're looking for; on a match, push a Diagnostic:
                    #   table.diagnostics <- table.diagnostics.push(
                    #       Diagnostic{kind: DiagnosticKind.<<PascalCaseName>>,
                    #                  name: ..., line: line, expected: ..., actual: ...})
                    _:
                        pass

        # Same shape for Ast::Stmt (VarDecl seeds note_local_type; If/While/For/
        # Match/Block recurse into nested statement lists).
        def walk_statements_for_<<name>>(statements: darray[Ast::Stmt], table: lmut SymbolTable,
                                          var_types: mutable darray[sview]&,
                                          type_names: mutable darray[sview]&) -> void: ...

        # Decl.Func seeds var_types/type_names from params via note_local_type,
        # then walks the body; Decl.Module/Decl.Scoped recurse.
        def check_<<name>>_declarations(declarations: darray[Ast::Decl], table: lmut SymbolTable) -> void: ...

    public:
        def check_<<name>>(declarations: darray[Ast::Decl], table: lmut SymbolTable) -> void:
            can Memory.Allocate, Abort.Panic:
                table <- check_<<name>>_declarations(declarations, table)
```

Save as `src/semantic/check_<<snake_case_name>>.elisa`.

### Known gotchas

- **`catch` desugars to `Stmt.Match`** with a synthetic error arm parsed as
  `Ast::Pattern.TypeBind("error", <binder>)` — see
  `src/semantic/check_void_match_scrutinee.elisa` (header comment + the
  `bound_type == "error"` check at line 21). If your check walks `Stmt.Match`
  arms, decide explicitly whether a `catch`-desugared arm should be excluded
  (most Void/type-flow checks exclude it).
- **`-> void error[E]` and `-> void` are indistinguishable in the symbol
  table**: `parse_signature_clauses` discards the `error[...]` clause entirely
  (see `check_void_match_scrutinee.elisa` lines 11-12, and
  `check_void_value_use.elisa`'s `sym.return_type == "void"` check). Don't
  assume a non-empty return type implies a non-void, non-error-union function.
- **`TypeKind.String` is NOT "no fields"**: cstr/sview/dstr all have
  fields/methods (via UFCS), so any "primitive has no fields" style check must
  explicitly exclude `String` alongside `Named` — see the header comment of
  `check_field_access_on_primitive.elisa` ("Strings/structs/enums (Named) have
  fields/methods ... deliberately excluded").
- **f-strings (`f"...{x}..."`) build an owned `darray[u8]`**, not an `sview` —
  relevant if you're tempted to store an f-string result directly into a
  `Diagnostic.name`/`expected`/`actual` field (those are `sview`; you cannot
  hand them an owned buffer without a separate render step. `diagnostic_message`
  itself does this correctly: it builds its OWN owned `darray[u8]` buffer and
  extends it with per-kind f-strings — see `push_str`/`push_sview`/`push_int`
  in `Bytes` (`semantic.elisa` lines 24-52) and any `diagnostic_message` arm).
- **Method calls parse as `Expr.Call(callee=Expr.Field(...))`**: a bare-Field
  walk (e.g. hunting `object.field`) must special-case a `Field` callee of an
  enclosing `Call` so it isn't double-counted as a field ACCESS — see
  `check_field_access_on_primitive.elisa`'s `Expr.Call` arm.
- **`is` on a payloadless enum variant has historically been a Go-backend
  codegen hazard** (LLVM packed-ABI handling of nested/wildcard rebasing) —
  when writing FIXTURE source for `parse_report`/stage0 comparisons, prefer a
  `match` over a bare `is Enum.Variant:` check on a variant you know is
  payloadless, to avoid an unrelated backend crash masking your actual result.
  (This is carried over general dogfooding experience, not something visible
  in `src/semantic/`'s own comments — treat it as a fixture-writing caution,
  not a semantic-check design constraint.)
- A companion `docs/notes/ast_shape_gotchas.md` does **not yet exist** in this
  repo (checked at authoring time) — if one is added later, link it here
  instead of re-duplicating gotchas.

### Self-audit sweep (run in this order before declaring the batch done)

1. **Fast self-resolve gate**: `test/parity/check_self_hostable.sh`. This
   exercises stage1's OWN resolver (`Semantic::unresolved_table`) over its own
   source (`src/lexer,parser,semantic/*.elisa`) against a small hardcoded
   builtin whitelist (`seed_builtins` in `src/semantic/symbols.elisa`) —
   catches "runtime-only helper" leaks (a check that calls a stdlib/runtime-only
   symbol not redeclared inside the frontend's own file glob) FAST, before the
   full oracle build. A file that passes `parse_report` (built by the real
   stage0 compiler, which knows the whole runtime) can still fail this gate.
2. **Oracle fire/silent pair**: build `parse_report` (oracle protocol above),
   then run it on (a) a fixture that SHOULD fire your new kind and (b) a
   closely related fixture that should NOT (the Unknown-family / adaptive-pair
   case) — confirm `D <n>` and the message text on the first, and confirm the
   count is unchanged (or the specific line absent) on the second.
3. **Exhaustive-match build check**: since `diagnostic_message` and
   `diagnostic_severity` have no wildcard arm, simply getting a clean stage0
   build of `parse_report.elisa` (step above) already proves you didn't forget
   wiring points 2 or 3 — a missing arm is a compile error, not a silent gap.
4. **Regression smokes**: run any existing `test/parity/*_smoke.sh` that
   touches a NEIGHBORING diagnostic family (e.g. touching type-flow checks →
   run `comparison_type_smoke.sh`, `assign_type_smoke.sh`, `field_type_smoke.sh`,
   `operator_operands_smoke.sh` as applicable) to confirm you didn't regress
   an existing check's wording or firing.
5. **Full breadth sweep** (optional, slower): `test/breadth/run.sh` — sweeps
   external corpora through `parse_report` and surfaces any newly-introduced
   false positive at scale.

### Report format

For each new `DiagnosticKind`, report:

- Kind name (snake_case + PascalCase) and the six wiring-point edits made
  (file + line anchor for each).
- The fire-condition prose as landed (may be refined from the brief during
  implementation — note any change).
- Stage0 fire evidence (the exact command + output snippet).
- Stage1 before/after: `parse_report` output on the fire fixture BEFORE your
  change (kind absent) and AFTER (kind present with correct line/message),
  plus the silent-fixture output showing no regression.
- Severity chosen and why (parity with stage0's class of finding, or
  stage1-only hint).
- Any new file-local helper added (name + one-line purpose) if the shared
  `resolve_types.elisa` helpers didn't cover the need.
- Self-audit sweep results (pass/fail per step above).
- Any known limitation / deliberately-excluded case (the "sound subset"
  boundary) — this is not a defect list, it's the contract the check makes
  with future readers.

### Prime directive

Elisa's frontend work is governed by: **sound subset, zero false positives,
principled decline is success**. A check that stays silent on a case it
cannot prove is doing its job correctly. A check that fires on an `Unknown`-
inferred value to "be helpful" is a regression, full stop — it will be treated
as a bug even if it happens to be right on the fixture you tested.
