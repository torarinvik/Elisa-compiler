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
* **Alternate outputs** — `ir`, `llvm`, `bc`, `header`, `c-archive`, `c-bind-check`. The object
  path is the one the fixpoint and the corpus exercise; a second output format would be a
  second surface to keep in parity for no correctness gain.
* **Execution and tooling** — `interpret`, `serve`, `test`, `tests`, `test-runner`, `benches`,
  `fixtures`, native link/run, the debugger, the REPL. These are a build system and a
  developer environment, not a compiler.
* **SMT / Z3.** stage1's proof-adjacent checks are the heuristic semantic rules and are
  described as such. There is no plan to embed a solver; a program that needs stage0's SMT
  should be checked by stage0.

If one of these is ever wanted, it is a NEW feature with its own justification — not a parity
debt.

## The one thing that was a real defect: silent flags

`-O0`, `-O2` and `-O3` used to be **accepted and ignored** by `scripts/elisac_stage1.sh`, so
`-O0` and `-O3` produced byte-identical objects while the caller believed otherwise. That is
not a missing feature, it is a wrong answer to a question the user asked, and it is the one
part of the CLI gap worth fixing. The wrapper now rejects an optimisation level it cannot
honour rather than pretending to apply it.

The LLVM pass pipeline itself stays disabled — `default<O2>` has trapped on large self-host
modules (see the note in `src/driver/elisac.elisa`). Emitting unoptimised objects is a stated
property, not an accident; host `opt`/`clang` can optimise afterwards.

## Bootstrap policy, unchanged

`scripts/build_runtime_object.sh` still invokes stage0. Switching it would make the
from-scratch path depend on a seeded stage1 — a bootstrap-policy decision, not a parity fix.
