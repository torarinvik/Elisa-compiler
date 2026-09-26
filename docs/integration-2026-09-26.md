# Compiler branch integration — 2026-09-26

This checkpoint integrates the available Elisa compiler histories into `main`. It does not declare the complete language or runtime memory safe. The remaining work packages in IMPLEMENTATION_PLAN.md stay open.

## Source accounting

- `46bef6f7` merges detached verification tip `c63c23ac`, including the current semantic index work through `aef6be4e`. It retains the stronger nullable alias invalidation, tuple-layout fixed point, and narrow enum identity barrier.
- `9493acf8` retains distinct working-tree gains: corrected C export metadata lookup, C-header coverage, the typed target-machine fixture, and standalone machine/tuple/enum fixtures.
- `97f26eb7` integrates `audit/codex-main-worktree` history at `6d725040`. Modern split modules take precedence over obsolete monolithic refactors. Concrete gains were ported into the current modules: bulk IR byte appends, receiver-argument appends, and alternate-leaf capacity reservation. The static-if AST report fix was already present.
- `9db72c72` records the superseded semantic-index branch. Range-diff verified its three patches against the already integrated equivalents: `6787e6a7 = 5d0e2ae1`, `59954f18 = 53c020c1`, and `be005efb = debc3a98`.
- `amm-placement` (`2213e393`), `codex/composite-error-catch` (`4f3f7354`), and `audit/nw-port` (`ad4296fa`) were already ancestors of main.
- `7a17acd2` adds regression coverage proving that runtime inclusion does not disable zeroed-reference rejection.

## Corrections and exclusions

The loose change that disabled the zeroed checker whenever runtime inclusion was enabled was rejected. The older broad enum exemption was rejected in favor of the integrated narrow nominal-identity check. Superseded nullable and tuple changes were resolved to the stronger verified implementations. Obsolete cosmetic rewrites were not replayed onto modern modules.

Combined validation exposed an overbroad region-return relaxation: ordinary typed-reference forwarding was permitted by dropping all implicit reference sources, which also accepted a field-derived borrow that erased its inferred lifetime. Commit `1bcf0674` distinguishes direct forwarding from field-derived returns, retains explicit-region checks and the opaque void-pointer exception, and tests the positive and negative cases at O0 and O2.

## Validation

The first combined-source seed passed; compiler inputs were SHA-256 compared before and after the build. The product hash was `6e4cf1db10a7a5b0c5ce9f66de0509f383ce3c3244b556ce78f8622f5005ef5f` (see final build records for the corrected product).

Before the region correction: native compile-and-run checks passed 529/529, C headers matched Core byte-for-byte and passed C/C++ syntax checks, and Gen2 self-hosting passed. Nullable flow, zeroed-reference safety (including runtime inclusion), destroyed-view lifetime, invalid atomic orders, IR writer serialization and rejection, explicit generic concrete errors, and machine-state lexer checks passed. Two native differential fixtures were skipped because Core rejects them. Initial zeroed/region test attempts selected a stale legacy Core product; reruns explicitly selected the current Core binary. The region suite then exposed the regression described above.

The corrected product was freshly seeded and passes the expanded `sview_region_tie_smoke.sh` at O0/O2 with both Core and Stage1. Stage1 rejects the implicit field-reference case before LLVM emission. Corrected Stage1 SHA-256: `b8bd3a694848ea2d278439ca8f4f8cf7bb564145a4b40c417165ab6a756948de`; runtime SHA-256: `44b2e4e9aa6f8488b9c74a301d6424b79d54e21e875d5eb39acb9e1d372b4391`. The corrected compiler also passes Gen2 self-hosting; the Gen2 product passes the same O0/O2 lifetime regression suite. Zeroed-reference checks pass again, including runtime inclusion. The reference-reborrow suite passes all 27 rejected contexts plus executable forwarding, real double-reference, cast, and lock/submit controls. The fallback-type suite passes all six cases against Core (three rejections and three positive controls), with zero findings in its frontend/standard-library scan. Logs and compiler-input manifests are retained under `build/integration-20260926/`. No full acceptance, sanitizer, or cross-target qualification is claimed.

## Preservation and cleanup

The original tracked working patch and detached verification build log are archived under ignored `build/integration-20260926/`. A complete patch including untracked files and the stash metadata were archived before dropping the pre-integration stash. All six original untracked fixture/test files were checked against the stash's untracked tree and preserved exactly. All discovered branch tips are ancestors of main after integration. Remote publication is outside this checkpoint: another process pushed main during validation; this integration task did not run `git push`.

All four redundant worktrees and their merged local branches were removed. The semantic-index-latest worktree was retained until its active proof-build consumer finished, then removed after a clean-source and ancestry check. Only the main worktree remains. Audit remote-tracking refs remain as historical references.
