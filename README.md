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
src/frontend/                the self-hosted frontend
  elisacore_frontend.elisa   entry (includes runtime + tokens + lexer)
  frontend_tokens.elisa      token model
  frontend_lexer*.elisa      lexer: core, tokens, strings, cursor,
                             comments, numbers, identifiers
  frontend_parser.elisa      region-inferred parser
  frontend_parser_tokens.elisa
                             parser AST/token model
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
  prototypes have been removed; `frontend_parser.elisa` is the single parser
  source.
- **Semantic: not yet written.** Next milestone after parser parity.

## Single source of truth

Two guards keep stage1 honest while stage0 still exists:

1. **Runtime drift guard** — `scripts/check_runtime_drift.sh` diffs the vendored
   `elisacore_std` against Elisa-core's canonical copy and fails on any
   difference. Run in CI. Set `$ELISA_CORE` to your Elisa-core checkout (defaults
   to the sibling `../../Go projects/Elisa-core`).
2. **Lexer parity** — the frontend's token-kind checksum must equal the stage0 Go
   lexer's on a shared corpus. (Oracle hookup is the next infra task — see below.)

## Building / checking locally

```sh
export ELISA_CORE="/path/to/Elisa-core"          # if not the sibling default
scripts/check_runtime_drift.sh                    # runtime in sync?
~/.elisac/elisac -emit semantic test/fixtures/lexer/frontend_lexer.elisa
~/.elisac/elisac -emit semantic src/frontend/frontend_parser.elisa
```

## TODO

- [ ] Cross-repo **parity oracle**: expose the stage0 Go lexer's token-kind
      checksum (e.g. a `-emit tokens`/checksum subcommand on `elisacore`) so this
      repo's CI can compare without reaching into Elisa-core's Go test internals.
- [ ] Retire the originals in Elisa-core (`Code/frontend_elisacore/`) and rewire
      the 5 in-tree Go consumers once cross-repo parity is green.
- [ ] Parser parity, then name resolution + typecheck.
