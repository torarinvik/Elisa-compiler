# Q1.2 proof-build invalid-IR reproduction and Q0.1 resolution

## Result

The Q1.2 failure reproduces with the clean Stage1 product at `6b475d894331f0a81c3112167ef7fcf5c642a424` and does not reproduce with the requested Q0.1 branch at `9ef4bff57057e4cb567fc9290294c5189b3bf3e2`.

I built the exact committed proof source `989e880d69888e63940b31066a50e6d0f1068c0f` from a separate clone (not a proof checkout/worktree) with both products enabled, O2, serial builds, and the object cache disabled. With the Q0.1 Stage1 product, the proof/replay pair completed as generation `024249a6fe05478394fb8dacb17d107c`. Repeating the same command and source snapshot with the clean 6b Stage1 product failed while compiling `src/main.elisa`, before object emission:

```text
error: backend generated invalid LLVM IR; refusing to optimize or emit
```

The proof repository was not modified. Its cloned worktree remained detached at the exact commit above. The Q0.1 compiler worktree was clean before this report was added.

## Minimal source and root cause

The compiler branch already contains a focused source reproducer: `test/fixtures/backend/nested_optional_ast_match.elisa`. Its 24-line program matches a packed AST enum variant nested in an optional payload (`Stmt.Return.value: Expr?`). The old 6b product rejects this fixture with the same invalid-IR diagnostic at O0; Q0.1 passes the Stage1 smoke.

The lowering defect is in nested packed-enum subpattern handling. Before Q0.1, the match emitter sent an optional packed-enum value directly to the packed-store handle reader, even though its LLVM representation is a tagged optional aggregate `{ i1, i32 }`. The new `emit_packed_variant_subpattern_test` branches on the presence tag, extracts the payload, and only then passes the packed-enum handle to the nested matcher. This prevents both invalid aggregate-as-integer IR and the corresponding incorrect runtime interpretation. The same change is applied to statement-match and value-match lowering. The evidence is the controlled compiler-version comparison plus the minimized fixture; the old verifier's diagnostic does not expose a function/block name, so no more specific failing IR instruction is claimed.

## Verification

- Clean Q0.1 Stage1 product SHA-256: `b9a1358a49e06d0b80b2d03abf231c6b1ceb23b15154ac5e450dc57611ece4c4`; provenance records source revision `9ef4bff57057e4cb567fc9290294c5189b3bf3e2`.
- Clean 6b Stage1 product SHA-256: `65a9308c53b510365aa69644a0bcaa9a071ea2006683dad6bf2ec12fc394f6b3`; provenance records source revision `6b475d894331f0a81c3112167ef7fcf5c642a424`.
- Exact proof build: Q0.1 passes both proof and replay outputs at O2; 6b fails at `src/main.elisa` with the diagnostic above.
- Focused nested-optional Stage1 regression passes at O0, including its runtime control.
- The regression's emitted LLVM module also passes `opt -passes=verify -disable-output` with LLVM 23.1.1. A check confirms it does not contain a `zext { i1, i32 } ... to i64` of the optional aggregate.
- The nested-optional pattern is Stage1-specific in this source shape; Stage0 parity is not claimed. The separate hierarchical optional enum payload differential script could not run with the available Stage0 product because the freshness guard found it was built from `370110bc`, while its source checkout is now `dbce3243`. I did not bypass the guard or treat that stale Stage0 binary as current evidence.

## Reproduction commands

The proof build was run from the separate detached proof clone with these compiler variables set for each product in turn:

```sh
ELISA_COMPILER_SRC=<clean-compiler-worktree> \
ELISA_COMPILER_ROOT=<clean-compiler-worktree> \
ELISA_COMPILER_REV=<exact-compiler-commit> \
ELISA_COMPILER_BIN=<clean-compiler-worktree>/bin/elisac-stage1 \
ELISA_STAGE1_BIN=<clean-compiler-worktree>/bin/elisac-stage1 \
ELISA_STAGE1_ROOT=<clean-compiler-worktree> \
ELISA_RUNTIME_OBJ=<clean-compiler-worktree>/build/runtime/elisacore_runtime.o \
ELISA_PROOF_PRODUCTS=all ELISA_PROOF_BUILD_JOBS=1 \
ELISA_PROOF_OBJECT_CACHE=0 ELISA_OPT_LEVEL=O2 bash scripts/build.sh
```

The Stage1 regression and explicit verifier gate:

```sh
ELISA_STAGE1_BIN=<clean-q01-worktree>/bin/elisac-stage1 \
  bash test/parity/nested_optional_ast_pattern_stage1_smoke.sh
<clean-q01-worktree>/bin/elisac-stage1 -emit llvm -O0 \
  -o /tmp/nested-optional.ll test/fixtures/backend/nested_optional_ast_match.elisa
<llvm-bindir>/opt -passes=verify -disable-output /tmp/nested-optional.ll
```

No verifier guard was weakened; invalid IR continues to fail closed.
