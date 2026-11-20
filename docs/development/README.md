# Working on the Elisa compiler

Follow the [quickstart](../../README.md#run-your-first-program) to prepare
Stage0, Stage1, and the host toolchain. Run commands below from the repository
root with `ELISA_CORE` and `ELISACORE_BIN` set as in the quickstart.

## Verify a change

```sh
test/parity/stage1_product_smoke.sh
test/parity/run_all.sh --profile full
```

The product smoke compiles and runs native fixtures and checks that an
installed snapshot can emit an object. The full parity suite exercises
diagnostics, code generation, and self-hosting using Stage0 as a reference.
Some tests also need host tools such as Z3, Node.js, or CPython development
headers. The [CI workflow](../../.github/workflows/parity.yml) documents the
toolchain used for the hosted lexer and code generation checks.

Keep formal fixtures under [`test/`](../../test/). Store ad hoc experiments
and generated reports under `build/`. A pair of tracked TSV baselines
supports diagnostic comparisons and test scheduling. The standalone [LLVM pass tests](../../test/llvm/) exercise individual backend rewrites.

## Runtime synchronization

The canonical standard library lives in Elisa-core. Check the vendored copy
under [`elisacore_std/`](../../elisacore_std/) against it:

```sh
scripts/check_runtime_drift.sh
```

## Build outputs

The bootstrap script writes the compiler to `bin/elisac-stage1` and the
runtime object to `build/runtime/`. Both directories contain generated
files. Removing them from a checkout requires seeding Stage1 again before
compiling there. A snapshot installed with `scripts/install_stage1.sh`
keeps its own compiler and runtime.

Use the rebuild time limit in [AGENTS.md](../../AGENTS.md) when working on
either compiler stage.
