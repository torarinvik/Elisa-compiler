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
elisac.elisalib/
  manifest.json              library manifest
  src/frontend/              the self-hosted frontend
    elisacore_frontend.elisa   entry (includes runtime + tokens + lexer)
    frontend_tokens.elisa      token model
    frontend_lexer*.elisa      lexer: core, tokens, strings, cursor,
                               comments, numbers, identifiers
  vendor/elisacore_std/      VENDORED copy of Elisa-core's stdlib (see drift guard)
test/
  fixtures/                  parity fixtures (lexer entry + token-model cases)
scripts/
  check_runtime_drift.sh     fails if vendored runtime != Elisa-core canonical
```

## Status

- **Lexer: complete + parity-locked** against the stage0 Go lexer (token-kind
  FNV checksum). Builds standalone with stage0.
- **Parser / semantic: not yet written.** Next milestones.

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
"$ELISA_CORE/bin/elisacore" -emit semantic test/fixtures/frontend_lexer.elisa
```

## TODO

- [ ] Cross-repo **parity oracle**: expose the stage0 Go lexer's token-kind
      checksum (e.g. a `-emit tokens`/checksum subcommand on `elisacore`) so this
      repo's CI can compare without reaching into Elisa-core's Go test internals.
- [ ] Retire the originals in Elisa-core (`Code/frontend_elisacore/`) and rewire
      the 5 in-tree Go consumers once cross-repo parity is green.
- [ ] Parser (frontend layer 2), then name resolution + typecheck.
