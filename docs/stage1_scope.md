# What stage1 is, and what it is not

stage1 is an **object-emitting Elisa compiler**: source in, native `.o` out, with the same
accept/reject decision and the same computed answers as stage0. That is the whole product
goal. This file exists so the rest of stage0's CLI stops being read as an unfinished to-do
list — it is not one, and an audit that counts those modes as gaps is measuring the wrong
thing.

## In scope — the parity that is actually claimed

| Property | How it is held |
|---|---|
| Same answers | `test/parity/differential_corpus.sh` — compile, link and RUN both, compare exit codes. MISMATCH is ratcheted at zero. |
| Same acceptance | parser + semantic acceptance suites, `diagnostics_diff.sh` |
| Reproduces itself | `scripts/self_host_gen2.sh` then `self_host_gen3_smoke.sh` — `gen3.o == gen4.o` byte-identical |
| Builds the stdlib | `self_host_runtime_smoke.sh` — stage1 compiles the runtime and programs agree |

Anything that would let stage1 emit a WRONG answer is in scope regardless of how obscure the
construct is. Anything that is merely a different way to *present* what the compiler already
computed is not.

## Out of scope — deliberately, not pending

stage0's driver exposes roughly thirty `-emit` modes plus native link/run, a debugger, a REPL
and an SMT integration. stage1 implements `obj`. The rest are **not stage1 goals**:

* **Presentation of existing analysis** — `ast`, `lowered`, `semantic`, `facts`, `tokens`,
  `packed`, `progress`, `iface`, `deps`, `deps-json`, `doc`, `fmt`. These re-render data the
  compiler already has. Porting them adds no parity signal, and stage0 remains available to
  produce them.
* **Alternate outputs** — `ir`, `bc`, `header`, `c-archive`, `c-bind-check`. The object path
  is the one the fixpoint and the corpus exercise. (`llvm` IS now implemented — it prints the
  same module the object path lowers, so it shares that parity rather than adding a surface.)
* **Execution and tooling** — `interpret`, `serve`, `test`, `tests`, `test-runner`, `benches`,
  `fixtures`, native link/run, the debugger, the REPL. These are a build system and a
  developer environment, not a compiler.
* **SMT / Z3.** stage1's proof-adjacent checks are the heuristic semantic rules and are
  described as such. There is no plan to embed a solver; a program that needs stage0's SMT
  should be checked by stage0.

If one of these is ever wanted, it is a NEW feature with its own justification — not a parity
debt.

## Optimisation levels and `-emit llvm` — in scope and honoured (2026-08-03)

`-O1`, `-O2` and `-O3` run LLVM's `default<O{n}>` pass pipeline in the driver; `-O0`
(the default) skips it, so the fixpoint and every unoptimised measurement are unchanged.
The pipeline had been disabled while `default<O2>` trapped on large self-host modules —
those traps were the opaque-handle `==` and arena-identity miscompiles in the SELF-HOSTED
binary, not LLVM's; with them fixed the compiler builds its own 110k-line module at -O2
(9.1 MB -> 5.4 MB object) and the resulting binary compiles correctly.
`test/parity/opt_pipeline_smoke.sh` holds the invariant that matters: optimisation NEVER
changes answers — every runnable repro fixture must exit identically at -O0 and -O2.
`-Os`/`-Oz` remain rejected (no size-pipeline parity to hold them to). Before this, the
levels were accepted-and-ignored — a wrong answer to a question the user asked — and then
rejected outright; honouring them closes that properly.

`-emit llvm` prints the SAME module as textual IR instead of lowering it — the debugging
surface every backend investigation in this repo kept borrowing from stage0. The smoke
round-trips the IR through clang.

## Bootstrap policy, unchanged

`scripts/build_runtime_object.sh` still invokes stage0. Switching it would make the
from-scratch path depend on a seeded stage1 — a bootstrap-policy decision, not a parity fix.
