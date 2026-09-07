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

The inventory and the log that closes it out are kept apart: the first says what is still
missing and how it was measured, the second is dated and says what closed and when.

- [What stage1 has not ported — the measured inventory](porting_gaps_measured.md)
  - Part 1 — measured today
  - Part 2 — carried from earlier work, NOT re-measured
  - Suggested order
- [What stage1 has not ported — the progress log](porting_gaps_log.md)
  - Progress — 2026-08-17
  - `project abi-lint` — PORTED (2026-08-17)
  - Final state, 2026-08-17 — gate 170/170
  - easm-lint: the void / no-parameter subset is DONE (2026-08-18)
  - The AST carries SPANS now (2026-08-18)
  - `-emit ir`: the writer is fully SPECIFIED now, not merely "blocked" (2026-08-18)
