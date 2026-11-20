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

## What is deliberately NOT claimed (decisions, not debt)

Almost all of stage0's `-emit` surface is now implemented AND gated (`doc`, `iface`, `deps`,
`header`, `unsafe`, `c-archive`, `interpret`, `test`, `tests`, `test-runner`, `benches`,
`fixtures`, `packed`, `progress`, `lowered`, `c-bind-check*`, `pymodule*`, `ir` partial) —
see `docs/PORTING_GAPS.md` for the live per-mode state. What remains out of scope is a short,
explicit list of *decisions*:

* **SMT / Z3.** stage1's proof-adjacent checks are the heuristic semantic rules and are
  described as such. A program that needs stage0's SMT should be checked by stage0.
* **`-Os` / `-Oz`.** Rejected: no size-pipeline parity to hold them to.
* **A bare `x = v` in an inner scope** is a DECLINE, not stage0's lowering (which compiles
  into an infinite loop). A loud decline beats reproducing a wrong answer.
* **Packed `common:` physical row layout.** stage1 gives each inline common its own word;
  stage0 byte-packs inline commons into the tag's prefix word. Self-consistent on each side, a
  store never crosses compilers, and `-emit packed` reports each compiler's real layout.
* **`host_platform_name()` is the constant `"macos"`.** A Linux build must change it.
* **`-emit semantic` / `facts` / `serve`** are not implemented (a fact system stage1 does
  not have; a network compile server) — open work, not an exclusion.

If one of these is ever wanted, it is a NEW feature with its own justification — not a parity
debt.

## Opt-in frame-pointer retention

`-fno-omit-frame-pointer` adds LLVM's `"frame-pointer"="all"` policy to emitted
function bodies, including generated helpers and EASM bodies. It does not add
attributes to external declarations, enable trace callbacks, or change the
default build policy. `-fomit-frame-pointer` restores the default policy; the
last explicit option wins. The internal process setting is
`ELISA_STAGE1_KEEP_FRAME_POINTER=1` (only the exact value `1` enables it).

This is a prerequisite for native profiler experiments, not a guarantee of
complete source-level stacks: inlining, tail calls, foreign code and externally
linked runtime objects still require separate unwind/attribution handling.
The profiler integration gate verifies the policy and executable answers at
O0–O3, plus actual ARM64 main-function frame setup on macOS.

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

`-emit exe` links the object against the runtime into a runnable binary — the exact
compile-and-link every harness in this repo already performs by hand, promoted to a flag.
Host clang does the link; the smoke builds and RUNS one.

## Bootstrap policy, unchanged

`scripts/build_runtime_object.sh` still invokes stage0. Switching it would make the
from-scratch path depend on a seeded stage1 — a bootstrap-policy decision, not a parity fix.
