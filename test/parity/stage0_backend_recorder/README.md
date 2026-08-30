# stage0 backend-corpus oracle

Replays every program stage0's BACKEND lowers to LLVM IR through stage1, to find
features stage0 implements that stage1 does not.

The gate already replays stage0's `src/parser`, `test/semantic` and `src/semantic`
(~2.4k) suites. `src/backend` (289 tests) and `test/backend` (150) had no replay at
all — this is that missing dimension. It is NOT wired into `run_all.sh` yet: it needs a
stage0 checkout with the recorder applied, and its results are a work list rather than a
pass/fail ratchet.

## 1. Apply the recorder to stage0

From the local stage0 worktree (`$ELISA_CORE`, default `../../Go projects/structpy-tree`):

```bash
git apply /path/to/recorder.patch
cp parity_backend_record.go compiler/src/backend/
```

`recorder.patch` widens the lexer's source-registry gate to `ELISA_BACKEND_PARITY_OUT`
and splits `GenerateLLVMIRWithWarnings` — the single sink every textual-IR entry point
funnels through — into a thin wrapper plus the original body, so each lowering is
recorded exactly once. Both are inert unless the env var is set.

## 2. Harvest the corpus

```bash
cd "$ELISA_CORE/compiler" && ELISA_BACKEND_PARITY_OUT=/tmp/be_oracle.tsv \
  go test ./src/backend ./test/backend -count=1
```

Row format: `b64(filename) \t ok \t optLevel \t b64(source) \t b64(error)`, where `ok=1`
means stage0 produced IR. A failing test in the suite does not invalidate the rows
already written.

## 3. Replay through stage1, then VERIFY

```bash
python3 be_replay.py /tmp/be_oracle.tsv          # writes be_gaps.json + a summary
python3 be_verify.py                             # cross-checks gaps vs the stage0 CLI
```

**Always run step 3's verify.** Many in-process tests reach shapes user code cannot
spell (`internal runtime carrier type "StringView"`, ghost-erasure invariants); the
stage0 CLI rejects those too, so they are not stage1 gaps. On the 2026-08-08 baseline
this separated 130 raw declines into **119 real gaps + 11 artifacts** — an 8%
overstatement if skipped.

## Baseline (2026-08-08)

287 stage0-lowered programs → stage1 compiled 157, declined 130 → **119 verified gaps**.
See `stage0-backend-corpus-gap` in the project memory for the cluster breakdown and
which ones have since been fixed.
