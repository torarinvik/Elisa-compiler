# Elisa-compiler (stage1, self-hosted)

The Elisa compiler **written in Elisa** — the eventual single source of truth for
the language, and the frontend that powers the Elisa LSP (→ JetBrains plugin via
LSP4IJ).

Built **frontend-first**: lexer → parser → name resolution → typecheck → LLVM
backend.

## Product binary (day-to-day: no stage0)

After a one-time seed, day-to-day compiles use the stage1 product — not the Go
stage0 `elisac`:

```sh
# Once (needs stage0 only for this seed):
scripts/elisac_stage1.sh --seed

# Then compile Elisa → native object without stage0:
scripts/elisac_stage1.sh -o out.o path/to/program.elisa
# Opt in to the currently ported safe scalar/darray noalias subset:
scripts/elisac_stage1.sh -fnoalias -o out.o path/to/program.elisa
clang -o prog out.o build/runtime/elisacore_runtime.o
```

### WebAssembly

WASM is equally direct and includes the browser/Node integration layer:

```sh
scripts/elisac_stage1.sh -emit wasm -o build/hello.wasm path/to/hello.elisa
# writes hello.wasm, hello.mjs, hello.d.mts, hello.d.ts, and hello.json
```

See [docs/wasm.md](docs/wasm.md) for export adapters, JavaScript loading, memory, and
runtime import customization. The standing end-to-end check is
`test/parity/wasm_smoke.sh`.

| Piece | Role |
|-------|------|
| `src/driver/elisac.elisa` | Product entry: real lexer → parser → `Backend::emit` → object |
| `scripts/elisac_stage1.sh` | Host CLI (`-o`, include flatten) wrapping `bin/elisac-stage1` |
| `scripts/pymodule_pyi.py` | Dependency-free renderer for typed Python stubs from the manifest |
| `bin/elisac-stage1` | Seeded product binary (not checked in; rebuild with `--seed`) |
| `test/parity/stage1_product_smoke.sh` | Standing gate: fixture exit 42 without stage0 |

Host tools still required: `clang`, LLVM (`llvm-config` / libLLVM), optional `ar` /
`llvm-mc` / Z3 for archive, template, and SMT surfaces.

**Gen2 self-host** (stage1 compiling its own product sources into a second binary) is
CLOSED, and closed as a byte-identical fixpoint: `test/parity/self_host_gen3_smoke.sh`
asserts gen2 compiles the compiler and `gen3.o == gen4.o`. stage1 also builds the standard
library's runtime object, gated by `test/parity/self_host_runtime_smoke.sh` — the half the
fixpoint cannot see, since every generation otherwise links the stage0-built runtime.
Track with `scripts/self_host_gen2.sh`. Optional stage0 remains a parity oracle only.

Still open, and the reason self-hosting is not yet complete: the product driver runs
semantic analysis only under `ELISA_STAGE1_SEMANTIC_GATE=1`. With the gate off it emits
code without analysing, so it accepts programs stage0 rejects. The gate cannot default to
on until stage1's semantic layer stops OVER-reporting relative to stage0 on the compiler's
own source (docs/119 E4 "through a call" over reference parameters is the remaining
cluster). See `src/driver/elisac.elisa` for the current measurements.

Built **frontend-first**: lexer → parser → name resolution → typecheck → LLVM
backend.

## Layout

```
src/
  elisacore_frontend.elisa   entry (includes runtime + lexer)
  lexer/                     the self-hosted lexer
    lexer.elisa              module hub (includes the parts below)
    tokens.elisa             token model
    lexer_*.elisa            lexer parts: core, tokens, strings, cursor,
                             comments, numbers, identifiers
  parser/                    region-inferred parser
    parser.elisa             parser
    parser_tokens.elisa      parser AST/token model
elisacore_std/               VENDORED copy of Elisa-core's stdlib (see drift guard)
test/
  fixtures/lexer/            parity fixtures (lexer entry + token-model cases)
scripts/
  check_runtime_drift.sh     fails if vendored runtime != Elisa-core canonical
```

## Status

- **Lexer: complete + parity-locked** against the stage0 Go lexer (token-kind
  FNV checksum). Builds standalone with stage0.
- **Parser: active region-inferred implementation.** The older parser
  prototypes have been removed; `src/parser/parser.elisa` is the single parser
  source.
- **Semantic: parity-complete against stage0 acceptance/diagnostics oracles.**
  `src/semantic/` implements name resolution plus a large diagnostics suite
  (hundreds of `check_*.elisa` passes aggregated by `src/semantic/semantic.elisa`),
  covering regions, borrows, effects, contracts, refinement, and termination at
  the standing semantic-acceptance and diagnostics-diff gates.
- **Backend / EASM: broad parity, with known gaps** (see `docs/backend_port_notes.md`
  current audit). Host tools `ar` / `llvm-mc` / optional Z3 remain platform boundaries.

## Single source of truth

Two guards keep stage1 honest while stage0 still exists:

1. **Runtime drift guard** — `scripts/check_runtime_drift.sh` diffs the vendored
   `elisacore_std` against Elisa-core's canonical copy and fails on any
   difference. Run in CI. Set `$ELISA_CORE` to your Elisa-core checkout (defaults
   to the sibling `../../Go projects/Elisa-core`).
2. **Lexer parity** — the frontend's token-kind checksum must equal the stage0 Go
   lexer's on a shared corpus; `test/parity/run_all.sh` runs this as a standing gate.

## Building / checking locally

```sh
export ELISA_CORE="/path/to/Elisa-core"          # if not the sibling default
scripts/check_runtime_drift.sh                    # runtime in sync?
~/.elisac/elisac -emit semantic test/fixtures/lexer/frontend_lexer.elisa
~/.elisac/elisac -emit semantic src/parser/parser.elisa
```

## TODO

Port status (stage0 → stage1): **substantially complete, but not yet complete**. Standing
parity gates (`test/parity/run_all.sh`) are the authority. Intentional
platform-tool boundaries only: host `ar`, `llvm-mc`, and optional Z3 for SMT
proofs — not compiler logic left unported.

- [x] Cross-repo **parity oracle** (equivalent from this repo): lexer token-kind
      parity via `test/parity/run_parity.sh` against stage0; a dedicated stage0
      CLI checksum flag remains optional Elisa-core polish, not a stage1 gap.
- [x] Breadth diagnostic-count baselines: `test/breadth/run.sh` supports
      `--write-baseline FILE` and `--baseline FILE` for per-file `D <n>` drift.
- [x] Breadth corpus exclusions are explicit: paths containing a `_unused/`
      segment and files ending in `_unused.elisa` are intentionally skipped.
- [x] Type model for backend/analysis surfaces: named tuples (side-table labels),
      refs, optionals, generics/monomorphization, GuestVAddr/HostPtr carriers.
- [x] Analysis engines at acceptance parity with stage0 (regions, borrows,
      effects, contracts, refinement, termination) via diagnostics fixtures and
      semantic acceptance oracles.
- [x] LLVM IR/native object backend, optimization, DWARF, exported C headers,
      and trace hooks.
  - [x] Stage0 backend/EASM parity for this repo: ordinary source paths, guest-overlay
        source lowering, multi-level provenance joins, lockstep (structural +
        symbolic GPR/ALU/flags/ambient + executable oracle), property/enforcement
        suites, and project/template orchestration (llvm-mc/`ar` remain host tools).
- [x] Whole-program disjoint-parameter alias scopes (`FuncDisjointParams` plus combined
      `alias.scope`/`noalias` element metadata), including fresh, clone, aliased, and
      forwarded-call cases under `-fnoalias`.
- [x] Forced dereference/bounds guards (`-fbounds-check` / `ELISACORE_FORCE_BOUNDS_CHECK`).
- [ ] Remaining error-union value operations outside the covered local/parameter/struct clone,
      `try value else fallback`, and expression `catch value:` paths (notably broader generic
      and aggregate propagation forms).
- [x] Cross-repo stage0 frontend retirement is out of band (Elisa-core consumers).
