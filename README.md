# Elisa-compiler (stage1, self-hosted)

The Elisa compiler **written in Elisa** — the eventual single source of truth for
the language, and the frontend that powers the Elisa LSP (→ JetBrains plugin via
LSP4IJ).

Built **frontend-first**: lexer → parser → name resolution → typecheck. The
backend comes later. The stage0 compiler (Go, in the `Elisa-core` repo) remains
the bootstrap toolchain and the **parity oracle** until stage1 reaches parity and
replaces it.

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
- **Semantic: in progress.** `src/semantic/` implements name resolution plus a
  growing diagnostics suite — 142 `DiagnosticKind` variants wired through
  ~90 `check_*.elisa` passes, aggregated by `src/semantic/semantic.elisa`.
  Remaining work includes analysis engines (regions, borrows, effects,
  contracts, refinement, termination) and a native backend.

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

Near-term milestones:

- [ ] Cross-repo **parity oracle**: expose the stage0 Go lexer's token-kind
      checksum (e.g. a `-emit tokens`/checksum subcommand on `elisacore`) so this
      repo's CI can compare without reaching into Elisa-core's Go test internals.
- [x] Breadth diagnostic-count baselines: `test/breadth/run.sh` supports
      `--write-baseline FILE` and `--baseline FILE` for per-file `D <n>` drift.
- [x] Breadth corpus exclusions are explicit: paths containing a `_unused/`
      segment and files ending in `_unused.elisa` are intentionally skipped.
- [ ] Real type representation (tuples/refs/optionals/generics) to replace the
      coarse `TypeKind` — the prerequisite for the analysis engines.
- [ ] Analysis engines: regions, borrows, effects, contracts, refinement,
      termination.
- [ ] Native backend / codegen.
- [ ] Audit and retire remaining stage0 frontend references in Elisa-core; the
      old `Code/frontend_elisacore/` tree and “5 consumers” estimate are stale.
