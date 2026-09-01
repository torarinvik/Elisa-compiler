# What stage1 has not ported from stage0

Measured 2026-08-17 against `~/.elisac/elisac` and `bin/elisac-stage1`.

> **Current-audit note (2026-08-31):** The measurements below are historical and are not
> the live gap ledger. The `parity-gaps` worktree has since added the missing `-emit ir`
> writer slice for plain callable externs, with decorators and their raw arguments retained
> losslessly and a round-trip regression in `test/parity/ir_writer_smoke.sh`. The richer
> extern forms remain an intentional refusal until their compact stage1 side tables retain
> enough structure. The `machine over` lowering remains state-machine lowering; the recent
> fix preserves the arm's lexical scope while materializing successor stores instead of
> replacing it with ordinary loops. A fresh local stage1 product was rebuilt from the
> pinned stage0 compiler on 2026-08-31, and the IR and machine smoke tests pass against it.
>
> **State-machine follow-up (2026-08-31):** A second bootstrap regression was found in
> `parse_bit_group_members`: a multi-state transition captured a temporary optional AST
> expression and made the stage1 backend decline that function. The repair keeps the outer
> `machine over parser.position while true` and moves only the per-member parse into a helper,
> avoiding the unstable transition capture. The rebuilt product now lowers the complete
> `test/breadth/emit_native.elisa` driver with no `parse_bit_group_members` decline; the
> dedicated `state_machine_parser_selfhost_smoke.sh` pins this.
>
> **Machine parser parity follow-up (2026-08-31):** `machine from` now validates explicit
> enum qualifiers before the compact AST discards them, requires a qualified start state, and
> applies the stage0 foreign-mutation rule to `machine over` roots (including roots found in
> the `while` condition and nested driver expressions). These checks preserve the real
> state-machine lowering; they do not rewrite it as ordinary loops. The parser replay oracle
> agrees on 440/440 acceptance cases.
>
> **Nested fixed arrays (2026-08-31):** The old ledger entry claiming `i64[2][2]` was
> rejected by array interning was stale. A fresh `i64[2][3]` read/write fixture is accepted
> by both local stage0 and stage1 at `-O0`, and both linked programs return 44. The existing
> `backend_native_smoke.sh` nested-array coverage and the new fixture cover the behavior.
>
> **Payload error unions (2026-09-01):** The zero-overhead error-union path now preserves
> payload-bearing status values through direct calls, stored unions, generic errorsets, and
> function values. Expression and statement catches bind single- and multi-field payloads;
> native regressions are in `test/parity/backend_native_smoke.sh`.
>
> **Nested variant patterns (2026-09-01):** The previously listed `Expr.Leaf(Token.Ident)`
> gap is closed. Payloadless nested variants, nested payload binders, packed-store nested
> payload decoding, and nested or-pattern bindings now agree between stage0 and stage1 at
> `-O0` and `-O2`; the adversarial differential generators provide independent behavioral
> coverage.
>
> **Backend oracle follow-up (2026-09-01):** A fresh oracle generated from the current
> stage0 backend suites contains 341 unique lowered sources. Stage1 lowers 331; the remaining
> 10 are all stage0-CLI-unreachable internal `StringView`/ghost-erasure fixtures. The only
> reachable gap in the prior 27-case replay was fixed: compact extern metadata now retains
> applied container element names, so `extern f(v: view[T])` lowers its `%DynArrayView` ABI;
> `for mutable item in array` now uses a direct element pointer over stage0's iterator copy.
> The focused checks are `test/parity/extern_view_abi_smoke.sh` and the full backend replay.

**Update, same day** — several items below are now CLOSED, and two were mis-scoped. See
"Progress" at the end for what changed and what the corrected estimates are.

Everything in **Part 1** was re-measured today. **Part 2** is carried from earlier sessions
and is marked accordingly — treat those numbers as needing a re-measure before you act on
them. The distinction matters: the backend-corpus figure in the old notes was `119 gaps`, and
the current backend-oracle number is `0` reachable.

---

## Part 1 — measured today

### 1.1 Emit modes: 24 of 28 fully ported

stage0 advertises 28 `-emit` modes. The stage1 driver fully implements 24 of them (plus
`exe`, which stage0 has no equivalent for) and has a partial frontend-IR writer.

**Not ported at all — 3; partially ported — 1:**

| Mode | What it is | Note |
|---|---|---|
| `semantic` | the analyzer's own report | stage1 *runs* a semantic gate but cannot print stage0's report |
| `facts` | the fact/obligation dump | depends on the same reporting layer |
| `ir` | stage0's frontend-IR bundle | **partly ported** — stage1 writes the lossless closed subset (including plain callable externs); richer AST shapes refuse by name |
| `serve` | the language-server / `-addr` daemon | no server loop at all; see flags below |

**Ported and byte-identical** on a struct + enum + function fixture: `lowered`, `unsafe`,
`progress`, `fmt`, `doc`, `iface`, `deps`, `deps-json`, `interpret`, `test-runner`, `packed`,
`header`. That is one fixture, not a corpus — the per-mode smokes in `test/parity` are the
real evidence for each.

**Ported but expected to differ:** `llvm` (textual IR is stage1's own lowering, never
byte-compared), `obj`/`bc` (compared by behaviour and by `nm`, not bytes).

**Ported with a known divergence:** `packed` cannot reach byte-parity while the `common:`
row layout differs (stage1 inlines commons, stage0 uses a side table) — deliberate and
documented in-code.

### 1.2 Where a "ported" mode actually lives

`scripts/elisac_stage1.sh` is 334 lines of shell + Python and it does real work. These are
**not** in the self-hosted compiler:

- **Include expansion.** The driver never sees `include`; the wrapper flattens first.
- **`-emit deps` / `-emit deps-json`.** The wrapper intercepts both and computes them in
  Python. The driver *also* implements them (`emit_deps_report`) and produces the right
  bytes when invoked directly — the wrapper simply wins. Deleting the Python path is a
  cheap, self-contained cleanup.
- **Linking** (`-emit exe`, `c-archive` assembly) shells out to host `clang`.

Until these move, "stage1 compiles itself" is true of the compiler but not of the CLI.

### 1.3 CLI subcommands — 8 of 10 (updated)

| Subcommand | Status |
|---|---|
| `init <name>` | **ported** — produced a byte-identical directory tree today |
| `init-lib <name>` | **ported** — identical output and rc |
| `project view [target]` | **ported** — identical (this session) |
| `project deps [--json]` | **ported** — identical (this session) |
| `project abi-lint` | **ported** — matches stage0 per rule, text and `--json` |
| `project easm-lint` | **partly ported** — void/no-param routines VERIFIED (13 checks, matches stage0); parameterised routines refused (needs register dataflow) |
| `build` | **ported** — matches stage0; refuses target shapes needing a host linker |
| `run` | **ported** — needs `ELISA_RUNTIME_OBJ` |
| `test` | **ported** — needs `ELISA_RUNTIME_OBJ` |
| `bench` | **ported** |

The silence on `build|run|test|bench` is worth fixing on its own, independently of
implementing them: right now an unsupported subcommand is indistinguishable from a crash.
That is the same class of defect as the mute backend decline fixed in `47a3bb2c`.

`build|run|test|bench` need compile-and-link orchestration, not just reporting. The
resolution half they depend on now exists and is shared (`src/driver/project.elisa`), so
they are mostly driver plumbing plus a link step.

### 1.4 CLI flags not accepted

All rejected by the wrapper with `unknown flag`:

- `-target-triple <triple>` — the driver has `requested_target_triple` behind an env var, so
  this is wrapper plumbing only.
- `-link <flag>`, `-L <dir>`, `-l <name>` — no link-flag passthrough.
- `-addr <host:port>` — belongs with `-emit serve`.
- `-Os` / `-Oz` — deliberately declined (no size-pipeline parity to hold them to).

Accepted and working: `-o`, `-emit`, `-filter`, `-O0..-O3`, `-fnoalias`, `-fbounds-check`.

### 1.5 Diagnostics

Both compilers now print `path:line`, but the span and quoting differ:

```
stage0:  err.elisa:2:12-27: undefined identifier "undefined_thing"
stage1:  err.elisa:2: undefined identifier 'undefined_thing'
```

Two separate gaps: **no column span**, and **single quotes where stage0 uses double**. The
quoting is a one-line fix. The column span needs token offsets threaded into the diagnostic
record.

`diagnostics_smoke.sh` is at 284/284 — but it asserts the accept/reject decision and the
message text, not the span.

### 1.6 Backend feature corpus: no reachable gaps left

Replayed all 341 unique sources that stage0's own `src/backend` + `test/backend` suites
lower (recovered from the current `/tmp/be_oracle-current.tsv`):

- **331 compile under stage1**, 10 fail.
- **All 10 are rejected by stage0's own CLI too.** They are in-process-only shapes reaching
  internal carrier types (`StringView`, ghost erasure) or erased contract nodes that user code
  cannot spell.

So this oracle is **exhausted**: 331/331 of the CLI-reachable corpus. Earlier notes said
"119 real gaps" — that is now closed. The remaining 10 should not be "fixed"; they are not
reachable.

The new decline diagnostic already pays for itself here — the failures self-report, e.g.
`declined 6: same_empty, same_short, differs_short, …`.

---

## Part 2 — carried from earlier work, NOT re-measured

Verify before acting. Each links to the memory note holding the detail.

### 2.1 Deliberate, documented declines

These are decisions, not oversights. Re-opening one means re-litigating the reason.

- **Write-through-ref gap** — needs a ref-target-mutability bit `ValueType` does not have; a
  naive fix would newly permit writes through readonly refs.
- **Typestate call-site check** — `T[?]`/`T[&]` lowers like stage0, but stage1 has no
  call-site state check. Deliberately permissive.
- **`defer function` cleanup-scope** — stage1's check is syntactic, stage0's is scope-depth.
  Confirmed permissive.
- **Packed `common:` row layout** — inline vs side table; blocks `-emit packed` byte-parity.
- **Exhaustiveness bail at `arms.count > 32`** — recorded as UNSOUND; do not re-adopt.
- **`platforms` host selection** (new this session) — a constant, because a self-hosted
  binary has no `runtime.GOOS`. A Linux build must change it.
- **JSON *syntax*-error text** (new this session) — Go's character-level wording is not
  reproduced; the unknown-*field* message is verbatim.

### 2.2 Known-real but unfixed

- ~~**Nested variant sub-pattern** — `Expr.Leaf(Token.Ident)`, single-field nested pattern.~~
  **CLOSED (2026-09-01):** payloadless and payload-binding nested variants, packed-store
  nested decoding, and nested or-pattern bindings all execute with matching results under
  stage0 and stage1 at `-O0` and `-O2`.
- ~~**Applied extern view parameter / mutable fixed-array iteration** — compact extern metadata
  used to discard `view[T]`'s element and the loop backend rejected `for mutable item`.~~
  **CLOSED (2026-09-01):** extern `view[T]`/`darray[T]` parameters resolve to their interned
  by-value ABI; mutable array-like iteration binds a direct element address while preserving
  stage0's iterator-copy semantics.
- **Chain-resolver Optional asymmetry** — the type half handles a Ref-to-Optional pointee,
  the address half does not. Real, but **no reachable fixture was ever found** — do not
  "fix" it blind.
- **`-emit unsafe` strict audit** — the permission model is solved (40/40, EXTRA=0 from five
  AST rules); the blocker was a 16/56 UNGATED strict-audit divergence.

### 2.3 Inventories that need re-measuring

- **Symbol parity (`nm` diff)** — last at 270/3/3 with 11 of 19 blockers closed. Run at
  matched `-O0`.
- **Semantic over-reporting** — last recorded as 642 findings where stage0 makes none. Not
  reproducible by the obvious route today: on the compiler's own source stage1 printed 0 and
  stage0 printed 223 warnings, so the old measurement used a different harness. Re-derive
  the method before quoting the number.
- **SoA subsystem** — 5 corpus files; stage0's representation measured (struct of darray
  columns), two of three layers known.
- **easm** — a large subsystem with its own lockstep oracles in `scripts/`; never inventoried
  as a port gap.

---

## Suggested order

Cheapest first, and each is independently landable:

1. **Make `build|run|test|bench` say why they fail.** Minutes. Removes a silent-failure class.
2. **Diagnostic quote style** (`'x'` → `"x"`). One line, immediately visible in every gate.
3. **Delete the wrapper's Python `deps` path** — the driver already produces the right bytes.
4. **`project abi-lint` / `easm-lint`** — reporting subcommands over resolution that now
   exists; the same shape as the `view`/`deps` port just completed.
5. ~~**Column spans in diagnostics.** Threading work, no design questions.~~ **RE-SCOPED —
   this is a refactor, not plumbing.** The lexer's `Token` carries `column`/`start`/`length`,
   but the AST does not: all 49 `Expr`/`Stmt`/`Decl` variants carry a bare `line: u32`, and
   `Expr` is a packed enum with AST refinement. Columns therefore require widening every
   variant's position payload and updating every construction and every pattern match across
   parser, semantic and backend. Do it as its own piece of work, not as a step in this list.
6. **`build|run|test|bench` for real** — needs the link step; the wrapper already knows how.
7. **Move include expansion into the driver.** The largest remaining "the CLI is not
   self-hosted" item.
8. **`-emit semantic` / `facts`** — both blocked on the same reporting layer; do them together.
9. **`-emit ir`** — needs an IR stage stage1 does not have. Largest item here; question
   whether stage1 wants one at all.
10. **`-emit serve` + `-addr`** — a daemon; independent of everything above.


---

## Progress — 2026-08-17

### Closed

- **Diagnostic text.** 66 of stage0's 190 fixture messages differed from stage1's; now 3,
  each asserted in `KNOWN_DIVERGENCES`. The gate that was supposed to catch this normalized
  with `s/[^[:alnum:]_]+/ /g`, flattening every quote, colon and backtick before comparing —
  it could not see punctuation at all. It is now strict. Fixed along the way: `'x'` vs
  `"x"` (123 sites), a missing `&` on `static u8&` (10 messages, hidden because the fixtures
  matched on a substring), the effect-grant hint bracketing, four `;`-vs-`:` splits, and one
  parenthetical that told the reader the exact opposite of the rule it was explaining.
- **`build|run|test|bench` failing silently.** They now name themselves. They had been
  falling through to the compile path, where the subcommand was read as a source filename.
- **The wrapper's Python `deps`.** Deleted; the driver's own implementation produces
  stage0's bytes and now runs.
- **Driver-side include expansion** — the big one, and it was not merely missing but
  BROKEN. `expand_includes` panicked in the arena on any line longer than ~519 bytes (a
  per-line accumulator growing under a non-relocating arena), and recorded paths verbatim so
  the same file reached by two relative spellings did not dedup. No gate reached it, because
  every gate goes through the wrapper, which flattens first. Fixed: `-emit deps` from the CLI
  is byte-identical to stage0 over all six real graphs including the compiler's own 509-file
  closure, and **`elisac-stage1 src/driver/elisac.elisa` now compiles unaided**, producing an
  object with the same size and the same 22,548 symbols as the wrapper's.
- **stage0 bug, fixed in stage0 rather than reproduced**: the effect-grant hint rendered
  `add  can[...]` with a double space in the multi-effect branch and `add can X` with one in
  the single-effect branch. Also un-rotted three stage0 backend tests that had been failing
  since the syntax they use was removed.

### Corrected scope

Two items in "Suggested order" were estimated as small report ports over resolution that
already exists. That is wrong:

- **`project abi-lint`** needs stage0's native-source ABI scanner — 10 rules over inline asm
  in C/assembly inputs (~350 lines). The report shell is easy; the rules are the work. A
  partial port is worse than none here: it would print "ABI lint: clean" for a project it had
  not actually checked.
- **`project easm-lint`** — the no-EASM case is now ported and byte-identical (that is every
  project not using EASM). A target carrying `.easm` inputs is refused by name: the module
  section needs `easm.ParseFile`, and the package is ~13.7k lines. Printing the file list with
  an empty module section would read as "no exports, no issues" — a false clean.

### Closed since (same day, second pass)

- **`build`, `run`, `test`, `bench`** — implemented and matching stage0's stdout, stderr and
  exit code, by default target and by name, via `--project DIR`, and on both error paths.
  `project_compile_request` resolves the target and builds the same request buffer the flag
  CLI produces, so the compile pipeline is shared rather than duplicated. Linking is still
  not done: a target that emits an object into a non-`.o` output is REFUSED by name.
  `run`/`test` link before running and require `ELISA_RUNTIME_OBJ`, and say so.
- **`-target-triple`, `-link`, `-L`, `-l`** — these were never compiler gaps. The driver has
  implemented all four for a while; only the wrapper's argument loop rejected them. Three
  missing cases in a shell script were reading as missing features. Cross-compilation works
  end to end.
- **A backend gap found by the gate**: indexing directly into a cast (`(p.cast[T&])[i]`)
  declined the enclosing function, because `.cast[T]` is itself an `Index` node and every
  index path wanted an `Ident` base. It made the driver unable to compile itself. Fixed in
  all three place-resolution callers (chain resolver, read, assign) and pinned.

### Diagnostics point at the WRONG LINE for any file with includes (CLOSED)

Found while converging the two flattenings. stage0 reports the line in the ORIGINAL file;
stage1 reports the line in the FLATTENED unit:

```
a.elisa includes b.elisa and c.elisa; the error is on a.elisa line 4
  stage0: a.elisa:4:12-26: undefined identifier "undefined_here"
  stage1: a.elisa:6:      undefined identifier "undefined_here"
```

FIXED. `expand_includes` now emits a `FLAT:ORIG:PATH` entry where each file starts AND where
it resumes after every include it makes (a file's contents are not one contiguous run, so a
start-only map is wrong for everything after its first include). The printers take the last
entry at or below the reported line. A fault inside an included file now names that file and
its own line — previously it was attributed to the ROOT file at a flattened line.

Only the column span is left, and that is the AST refactor below. The map travels in
ELISA_STAGE1_LINE_MAP, the same mechanism `-emit fmt` already uses, so no global state; the
wrapper path (which flattens before the driver runs) is unchanged.

### Still open

Everything else in Part 1, plus: `-emit semantic`/`facts`/`serve`, the four
compile-and-link subcommands, column spans in diagnostics, and the remaining wrapper
responsibilities (the wrapper still flattens by default, and still owns linking). The two
optional-type diagnostics and the namespace-hint call form are scoped in
`KNOWN_DIVERGENCES`.

### Gate

Full parity gate **167/167** on the frozen tree (commit `a81370cd`), bootstrap fixpoint
intact. Note what it caught that hand-picked gates did not: changing shared diagnostic TEXT
turned 16 smokes red, because a sixth of the suite greps for message wording. Run the whole
gate for any change to diagnostic strings.

### Newly found, not yet filed above

- The driver's flattening and the wrapper's number lines slightly differently — 3 of 22,548
  symbols in the self-compiled object differ, all internal loop-lambda names carrying a line
  number. Harmless today, but the two must converge before the wrapper's flattening is
  removed.
- stage0 prints its warnings on **stdout**, not stderr, and warning output on large inputs
  was not reproducible run to run during this session. Worth a dedicated look.


---

## `project abi-lint` — PORTED (2026-08-17)

Implemented in `src/driver/abi_lint.elisa`, all twelve matchers, verified one fixture per
rule against stage0 in BOTH the text and `--json` forms (`project_abi_lint_smoke.sh`, 31
checks). What follows is the scoping note that drove the work.

Not started, but no longer an estimate. What it needs, measured:

**The report** is the easy half — the same resolved-target fields `project view` already
prints, plus `Scanned native files`, `ABI contracts`, `Link flags`, and the issue list, in
text and `--json` form (`formatNativeABILintReport` in stage0's `native_abi_lint.go`).

**The rules are twelve REGEXES**, and Elisa has no regex library, so each becomes a
hand-rolled matcher. This is the actual work, and the reason a partial port is dangerous: a
subtly-wrong matcher makes the tool print `ABI lint: clean` for a project it did not check.

```
\b(__asm__|asm)\b                                   asm block detection
(?i)(RunMainEntry|guest_exec|GuestExec|entry_trampoline|call_main_entry|jump_main_entry)
%[0-9]                                              positional operands
%%r(di|si|dx|cx|8|9)\b                              ABI argument registers
\b(pushq|popq)\b|\b(andq|subq|addq|lea)\b[^\n]*%%rsp\b   stack mutation
\bcall\s+\*        \bjmp\s+\*                        indirect call / jump
(?i)(noreturn|__builtin_unreachable|\[\[noreturn\]\])
"memory"            %%r(9|10|11)\b                   clobber / scratch parking
^\s*#\s*include\s+"([^"]+)"                        recursive scan of quoted includes
ELISA_ABI_CONTRACT\s+([^\n*/]+)                     contract extraction
```

Also needed: recursive scanning through quoted `#include`s with a seen-set, `ELISA_ABI_LINT_ALLOW(code)`
suppression, dedupe+sort of contracts and scanned paths, and per-issue LINE attribution (the
line the asm block starts on).

**A verified oracle fixture.** A project whose target carries `"foreign": ["native/guest.c"]`
with this source trips four rules plus the info rule:

```c
/* ELISA_ABI_CONTRACT guest_entry */
void RunMainEntry(void *ctx) {
    __asm__ volatile (
        "movq %0, %%rdi\n"
        "pushq %%rbp\n"
        "call *%1\n"
        : : "r"(ctx), "r"(ctx)
    );
}
```

stage0 reports, in this order: `inline-asm-positional-abi-operands` (warning),
`inline-asm-stack-without-memory-clobber` (warning), `guest-entry-call-mangles-stack`
(error), `guest-entry-no-scratch-register-parking` (warning), and
`target-triple-defaulted` (info) — all at `guest.c:3` except the last, which is at the
project file. Note the manifest key is `foreign`, not `native`.

Build one fixture per rule and diff against stage0 as each matcher lands; the remaining rules
(`native-source-read-failed`, `native-include-read-failed`,
`missing-guest-entry-abi-contract`, `guest-entry-target-not-x86_64`,
`guest-entry-jump-not-noreturn`) need their own.


---

## Final state, 2026-08-17 — gate 170/170

**CLI subcommands: 9 of 10 fully, the 10th partly.** `init`, `init-lib`, `project view`,
`project deps`, `build`, `run`, `test`, `bench`, `project abi-lint` all match stage0.
`project easm-lint` matches for targets without EASM inputs and refuses the rest by name.

**Emit modes: 24 of 28 fully, with `ir` partly ported.** Missing `semantic`, `facts`, and
`serve`.

**Flags:** all accepted except `-addr`, which belongs with `serve`.

**Diagnostics:** stage0-exact text, and the original file and line. Only the column span is
missing.

**Backend:** the CLI-reachable corpus is exhausted (275/275), and the CLI compiles the
compiler's own 509-file closure unaided, producing an object byte-identical to the
wrapper-flattened one.

### What is left, and why each is blocked rather than merely large

Two of the four are not "more effort" — they need something that does not exist yet, and one
of them is a design decision rather than a port.

- **`-emit ir`** — the frontend-IR bundle is a serialized AST, not a pre-LLVM lowering. The
  stage1 writer now covers its measured closed subset, including callable externs and
  decorators, and refuses richer shapes whose compact side tables are lossy. Widening it
  means extending the exact node mapping and adding source/bundle lowered-output oracles;
  it does not require a new backend IR.
- **`-emit semantic` / `facts`** — both dump the FACT SYSTEM (`fact_snapshot`, `fact_exits`,
  `fact_transforms`, `fact_groups`, `fact_blocks`), with column spans in every position.
  `grep -rl fact_snapshot src/` finds nothing: stage1 has no fact model to dump. So these need
  two separate subsystems — the fact system, and the AST position widening — before any
  printing work starts.
- **`-emit serve` + `-addr`** — a 231-line HTTP server. Portable in principle (sockets via
  libc externs, an HTTP/1.1 request parser, and the JSON encoder this repo now has), but its
  handler dispatches to `semantic`, `facts` and `ir` among other modes, so full parity is
  gated on the two items above. It is also a network service that compiles submitted source;
  worth a deliberate decision before it exists in a second implementation.
- **The EASM VERIFIER** — the remaining half of `easm-lint`. Not a parser: see below.

### easm-lint is a VERIFIER, not a pretty-printer (measured, 2026-08-17)

A routine-subset parser was written, matched stage0's `Module …` / `  export …` lines exactly
on a simple fixture, and was then **removed**. Adding a second export with facts, labels and a
`jmp` made stage0 emit eight `Issues:` entries the parser knew nothing about:

```
unsupported-entry-fact            an entry-fact whitelist
label-contract-without-label      label contracts must match a body label
empty-label-precondition          and must carry a machine-state precondition
unknown-control-contract          control contracts are a closed set
noreturn-jump-without-tail-contract
missing-input-binding             parameters must appear in `inputs:`
register-read-uninitialized       REGISTER DATAFLOW over the instruction stream
```

So the work is not "port the grammar" — the grammar is the easy part and took an afternoon.
It is "port the verifier", and that has now been MEASURED rather than estimated:

* **126 distinct issue codes.**
* 163 functions in `easm.go`, 19 of them analysis passes, over ~3.9k lines.
* The supporting machinery is a machine-state model: register liveness
  (`inputRegisterSet`, `outputRegisterSet`, `implicit-read-uninitialized`), stack alignment
  tracking (`stackMod`, `call-stack-misaligned`, `large-stack-adjust-without-probe`),
  callee-saved preservation proofs (`callee-saved-preservation-unproven`), direction-flag
  state (`direction-flag-not-restored`), operand-size inference (`ambiguous-operand-size`,
  `immediate-truncation`), frame carriers, capabilities, and lockstep composition.

That is a static analyser over x86/ARM assembly semantics, not a report. Each of the 126
codes needs a fixture that FAILS, verified against stage0, or the check is indistinguishable
from an unimplemented one.

**Why a partial port cannot be made safe here.** The usual escape — implement a subset and
refuse anything outside it — does not work, because "this routine is clean" is a claim about
ALL 126 checks. To know that none of them fire on even a two-instruction body, you have to
have implemented them. Refusing everything until the analyser is complete is therefore the
only sound intermediate state, which is exactly where `easm-lint` sits.

A parser without those checks prints a module with no issues, which reads as "this EASM is
fine" for code stage0 rejects with eight errors. That is why `easm-lint` refuses EASM inputs
rather than reporting on them.

Recommended order if the work continues: a decision on the fact system (it gates two emit
modes), then column spans, then the EASM verifier, then `serve` last since it depends on the
others.


---

## easm-lint: the void / no-parameter subset is DONE (2026-08-18)

stage1 verifies it — module lines, issues, exit code — and the differential reads
**130 agreeing / 782 refused / 0 diverged**, from 0/912/0.

**The boundary is parameters and non-void returns**, not instruction complexity. Both force
`inputs:`/`outputs:`, and declaring either reaches register dataflow
(`input-register-unused`, `return-register-not-written`). Excluding them, an exhaustive
5040-configuration sweep reaches exactly thirteen codes, all decidable from declarations plus
the operand-free instruction list, and all thirteen are implemented.

**Two lessons that generalise to the rest of the verifier:**

1. *A partial checker cannot skip checks.* Three-of-thirteen implemented produced 808
   divergences, because the contract checks fire on every routine — accepting any routine
   claims them all. The refusal boundary has to be drawn so no accepted input can reach an
   unimplemented check, which means landing a closed set atomically.
2. *Measure the emission details, do not reason about them.* Four were wrong first try:
   instruction-level issues carry the instruction's line; the exit code is 1 on any error
   issue; `unknown-control-contract` precedes `missing-body`; both precede the `missing-*`
   contract checks.

**To widen it** the next closed set is parameterised routines, which needs the register
liveness model (establish/read/overwrite over the instruction stream). Extend the corpus in
`easm_lint_differential_smoke.sh` first and let the reachable-code count tell you the size of
the set before writing anything.

---

## The AST carries SPANS now (2026-08-18)

`§1.5` said the column span "needs token offsets threaded into the diagnostic record". That
turned out to be the smaller half. The AST itself had nowhere to put one: every positioned
node carried a bare `line: u32`, so the span did not exist to be threaded. Both remaining
big-ticket items — diagnostics columns and the fact system, whose every position is
`file:line:col-endcol` — were blocked on the same missing field.

### What landed

* **`Ast::Pos`** on all 48 positioned `Expr`/`Stmt`/`Decl` variants. It mirrors stage0's
  `lexer.Pos` field for field (minus `File`, one per compilation, recovered from the
  driver's flat-buffer line map) so the frontend-IR writer can emit stage0's own `Position`
  nodes with no translation table.
* **Real spans at 187 parser construction sites** (`pos_of_token`). 87 sites remain
  line-only (`pos_at_line`) — synthesized nodes with no token behind them. `grep
  pos_at_line` is the exact list.
* **`Ast::expr_pos`** — an expression's own span, which is what stage0 reports a diagnostic
  at. `if xs.count:` is reported at `xs.count`, not at the `if`.
* **`Semantic::Diagnostic.pos`**, defaulted, and the driver prints `PATH:LINE:COL-ENDCOL:`
  when it is set. A check that has not been threaded degrades to `PATH:LINE:` — what every
  check printed before — so this converges check by check.

### Why widening beat adding

A new payload slot changes the ARITY of every pattern site: ~11,200 of them. Widening the
existing one changes only the ~340 constructions and the reads that wanted a line. And every
such read is a TYPE error, so the compiler enumerated them — the migration could not
silently keep a wrong value anywhere.

### The bug it exposed, which is the reason it was worth doing

`packed_row_llvm_type` hard-coded the AST AoS row as `{i32, [32 x i32]}`. stage0 COMPUTES
that number (max over the hierarchy's leaves of `ceil(payload_bytes/4)`); 32 was simply what
it came to when the constant was written. `Pos` took `Decl.Func` to 144 bytes, so every
constructor wrote 16 bytes past its record and into the next node's tag.

Nothing declined and nothing faulted at the write. It surfaced as an exhaustive `match`
falling through to its unreachable arm — and only in **gen2**, the compiler stage1 builds,
because gen1 is built by stage0, which sized the row correctly. Fixed by computing it;
`packed_aos_row_width_smoke.sh` now compares the two compilers' emitted row types directly.

### Where the columns stand, measured

`diagnostic_columns_smoke.sh` exists because `diagnostics_diff.sh` strips the location
prefix before comparing — it is about message text, and is structurally blind to positions.
That is how stage1 printed `file:2:` against stage0's `file:2:5-6` with every message gate
green.

Three outcomes, the same discipline the easm-lint differential uses:

```
355 fixtures — 3 agreeing, 148 pending (line only), 0 diverged
```

**DIVERGED fails the gate.** A wrong column is worse than none: it sends a reader, or an
editor's jump-to-error, to the wrong place. The first threading pass produced 64 of them,
all the same mistake — it attached the enclosing STATEMENT's span where stage0 reports the
offending EXPRESSION's. Those were dropped back to line-only rather than shipped.

**To close the 148:** each is one check whose position parameter is still a bare `line: u32`
threaded down from its caller. The fix per check is to take the offending expression instead
and report `Ast::expr_pos` of it — `check_affine_collection` and `resolve_types` are the two
worked examples. The count is printed on every run, so it cannot quietly stop shrinking.

---

## `-emit ir`: the writer is fully SPECIFIED now, not merely "blocked" (2026-08-18)

The earlier note said `-emit ir` could not be ported because stage1 "has no IR". That was
wrong in a useful way: the bundle is not an IR at all, it is a **serialized AST**
(`buildFrontendIRBundle` = version + filename + resolved source + `*ast.File`). stage1 has an
AST, so the only real question was whether it could write stage0's encoding.

It can, and everything needed is now measured.

### The oracle — exact, and over the whole tree

```
elisac -emit lowered <bundle>   ==   elisac -emit lowered <source>
```

Verified identical for a bundle stage0 writes. stage0 UNPARSES the tree it decoded, so a
single wrong node type, field name or nesting shows up as a textual diff of the program.
That is a far stronger check than `-emit ast`, which prints only declaration headlines.

### Why a writer is possible at all

The v2 decoder reconciles the file's type table with its own schema **by NAME**
(`codec_decode.go`: `schema.TypeByName(fileType.Name)`, then a field-name match). Numeric IDs
are file-local. So a writer numbers its own types and fields from 1 and only has to spell
stage0's names correctly — and `Ast::Pos` was deliberately given stage0's `lexer.Pos` field
names, so positions need no translation.

### The framing, read back out of a bundle rather than transcribed

```
magic "ELISAIR2\n" | uvarint version(2) | str filename | bytes source
type table:  uvarint count, then per type: id, name, field count,
             then per field: id, name, value descriptor
node table:  uvarint count, then per node: bytes(body)
             body = uvarint typeID + fields
fields     = uvarint liveCount, then per field: uvarint id, uvarint len, bytes
root       : uvarint node id   (ids are 1-based; 0 is null)
```

**The detail that is easy to get wrong**: `Position` and `Params` are wire kind **7**, an
inline STRUCT (uvarint type ID then its fields) — not node references. Reading a real
bundle's type table is what showed it; the Go struct definitions do not say so. Ints are
zigzag varints, `IntLit.Value` is a STRING, and a field at its zero value is omitted.

### The minimal closed set, with stage0's exact field names

```
lexer.Pos    Col EndCol EndLine EndOffset File Line Offset
File         DeclVisibility Decls Filename
FuncDecl     Name Params ReturnType Body Position  (+29 more, all omittable)
ParamDecl    DefaultValue Mutable Name Position Type      (inline struct)
NamedType    Name Position
ReturnStmt   Position Value
VarDeclStmt  Ghost Mutable Name Owner Position Type Value
ExprStmt     Expr Position
Ident        Name Position
IntLit       IsHex Position Suffix Value
BinaryExpr   Left LoweredCall Op Position Right
CallExpr     Func Args ArgNames Position  (+14 more)
```

### What remains

Writing the encoder in Elisa and growing the node mapping until the corpus stops refusing.
Two language constraints shape it: an `lmut` receiver must be threaded as `x <- f(x, …)`
rather than mutated in place, and the guard form is `VALUE return if COND`.

Constructs where stage1's AST cannot pick a single stage0 type — `Expr.Refinement` stands
for both `TryExpr` and `GetExpr` — must be REFUSED BY NAME, not guessed. A bundle that
decodes cleanly but describes a different program is the false clean this format makes
easy to produce.

A partial writer was drafted and deliberately NOT committed: an unreachable half-module in
`src/` rots, which is exactly how the driver's own include walker stayed broken behind a
wrapper for months.
