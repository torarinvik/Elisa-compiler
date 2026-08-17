# What stage1 has not ported from stage0

Measured 2026-08-17 against `~/.elisac/elisac` (stage0 `15502394`) and `bin/elisac-stage1`
at commit `e381c6cc`, with the full parity gate green at 166/166.

Everything in **Part 1** was re-measured today. **Part 2** is carried from earlier sessions
and is marked accordingly — treat those numbers as needing a re-measure before you act on
them. The distinction matters: the backend-corpus figure in the old notes was `119 gaps`, and
the real number today is `0` reachable.

---

## Part 1 — measured today

### 1.1 Emit modes: 24 of 28 ported

stage0 advertises 28 `-emit` modes. The stage1 driver implements 24 of them (plus `exe`,
which stage0 has no equivalent for).

**Not ported at all — 4:**

| Mode | What it is | Note |
|---|---|---|
| `semantic` | the analyzer's own report | stage1 *runs* a semantic gate but cannot print stage0's report |
| `facts` | the fact/obligation dump | depends on the same reporting layer |
| `ir` | stage0's pre-LLVM IR text | stage1 has no equivalent IR stage; this is a representation gap, not a printer gap |
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

### 1.3 CLI subcommands

| Subcommand | Status |
|---|---|
| `init <name>` | **ported** — produced a byte-identical directory tree today |
| `init-lib <name>` | **ported** — identical output and rc |
| `project view [target]` | **ported** — identical (this session) |
| `project deps [--json]` | **ported** — identical (this session) |
| `project abi-lint` | **not ported** — `error: unsupported project subcommand "abi-lint"` |
| `project easm-lint` | **not ported** — same |
| `build` | **not ported** — exits 1 **with no message at all** |
| `run` | **not ported** — exits 1 silently |
| `test` | **not ported** — exits 1 silently |
| `bench` | **not ported** — exits 1 silently |

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

Replayed all 285 unique sources that stage0's own `src/backend` + `test/backend` suites
lower (recovered from `/tmp/be_oracle.tsv`):

- **275 compile under stage1**, 10 fail (3 rejections, 7 declines).
- **All 10 are rejected by stage0's own CLI too.** They are in-process-only shapes reaching
  internal carrier types (`StringView`, ghost erasure) that user code cannot spell.

So this oracle is **exhausted**: 275/275 of the CLI-reachable corpus. Earlier notes said
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

- **Nested variant sub-pattern** — `Expr.Leaf(Token.Ident)`, single-field nested pattern.
  Scoped, not fixed; the declining emitter is identified.
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
5. **Column spans in diagnostics.** Threading work, no design questions.
6. **`build|run|test|bench` for real** — needs the link step; the wrapper already knows how.
7. **Move include expansion into the driver.** The largest remaining "the CLI is not
   self-hosted" item.
8. **`-emit semantic` / `facts`** — both blocked on the same reporting layer; do them together.
9. **`-emit ir`** — needs an IR stage stage1 does not have. Largest item here; question
   whether stage1 wants one at all.
10. **`-emit serve` + `-addr`** — a daemon; independent of everything above.
