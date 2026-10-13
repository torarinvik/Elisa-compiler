# Borrowed DArray fold probe

This focused probe compares a read-only fold over a borrowed DArray formal with Rust slice
iteration and Zig slice iteration. Each program fills four million `i64` values from the same
wrapping `u64` recurrence, then sums the slice 200 times. Each prints the same full checksum
and exits with `checksum % 251`. No timing claim is attached to this fixture.

## Build and inspect

Run from the repository root. Use a current Stage1 product for Elisa; LLVM IR output from an
older product does not validate current source lowering.

```sh
OUT=build/ir-probes/borrowed-darray-fold-current-20261013
mkdir -p "$OUT"

ELISA_STAGE1_BIN=bin/elisac-stage1 \
  scripts/elisac_stage1.sh -emit llvm -O3 -foverflow=wrap \
  -o "$OUT/borrowed-darray-elisa.ll" test/bench/borrowed_darray_fold/sum.elisa
ELISA_STAGE1_BIN=bin/elisac-stage1 \
  scripts/elisac_stage1.sh -emit llvm -O3 -foverflow=wrap \
  -o "$OUT/borrowed-darray-interleave8.ll" test/bench/borrowed_darray_fold/sum_interleave8.elisa
ELISA_STAGE1_BIN=bin/elisac-stage1 \
  scripts/elisac_stage1.sh -emit llvm -O3 -foverflow=wrap \
  -o "$OUT/borrowed-darray-interleave16.ll" test/bench/borrowed_darray_fold/sum_interleave16.elisa
ELISA_STAGE1_BIN=bin/elisac-stage1 \
  scripts/elisac_stage1.sh -emit llvm -O3 -foverflow=wrap \
  -o "$OUT/borrowed-darray-darray-interleave8.ll" test/bench/borrowed_darray_fold/sum_darray_interleave8.elisa
ELISA_STAGE1_BIN=bin/elisac-stage1 \
  scripts/elisac_stage1.sh -emit llvm -O3 -foverflow=wrap \
  -o "$OUT/borrowed-darray-darray-interleave16.ll" test/bench/borrowed_darray_fold/sum_darray_interleave16.elisa

rustc test/bench/borrowed_darray_fold/sum.rs --edition=2021 \
  -C opt-level=3 -C target-cpu=native -C overflow-checks=off \
  --emit=llvm-ir="$OUT/borrowed-darray-rust.ll"
rustc test/bench/borrowed_darray_fold/sum.rs --edition=2021 \
  -C opt-level=3 -C target-cpu=native -C overflow-checks=off \
  --emit=asm="$OUT/borrowed-darray-rust.s"

zig build-exe test/bench/borrowed_darray_fold/sum.zig -O ReleaseFast \
  -mcpu=native -lc -femit-llvm-ir="$OUT/borrowed-darray-zig.ll" \
  -femit-asm="$OUT/borrowed-darray-zig.s" \
  -femit-bin="$OUT/borrowed-darray-zig"
```

Keep compiler logs, benchmark output, and timing captures under the same ignored `$OUT` directory.

The cross-language flags correspond to the fast profile used by
`test/bench/codegen_perf/cross_language.sh`: Elisa O3 with wrapping arithmetic, Rust O3 with
native CPU features and overflow checks off, and Zig ReleaseFast for the native CPU. Capture
compiler versions, host CPU, repository revision, and source hashes alongside any later IR or
timing result. All source fixtures are the probe inputs; `SHA256SUMS` pins them and this README. Timing requires a separate qualified benchmark run with equivalent
correctness preflight and host controls.

The baseline Elisa function takes `darray[i64]&` explicitly and iterates with `for value in xs`;
Rust uses `&[i64]` and `for &value in xs`; Zig uses `[]const i64` and `for (xs)`. The optional `sum_interleave8.elisa` and `sum_interleave16.elisa` keep the same data and checksum
but spell the reduction as an indexed ascending range with the corresponding LLVM loop hint. The
`sum_darray_interleave8.elisa` and `sum_darray_interleave16.elisa` variants apply the hint directly
to `for value in xs`, exercising the borrowed DArray latch. Compare these paths separately: the
range variants test indexed lowering, while the direct variants test the new DArray loop metadata.
A separate manual-metadata experiment on a minimized wrapping reduction produced 16 and 32
`i64` values per backedge for factors 8 and 16 respectively. It was an LLVM counterfactual, not
output from the new source syntax or a current Stage1 compiler. Factor 8 matches Zig's native
ReleaseFast loop width; factor 16 matches the wider Zig loop after the common LLVM optimization
pipeline. An isolated LLVM-MCA model gives factor 16 slightly fewer model cycles per element
than factor 8 (0.181 vs. 0.200), but factor 16 adds callee-save work in the standalone helper,
and MCA is not a runtime measurement. Keep both factors as measurement candidates; do not infer
a speedup from loop width or the model. Current Stage1 output is still needed to verify the hint
path. Main's allocation and fill stay outside the fold helper.

## Probe provenance

The Rust and Zig IR/assembly inspection in this working session used repository revision
`273318c5d6d3da09b3388465e27f5275d55ab817` on Darwin arm64 (Apple M5), Rust
`1.99.0 (b940084d7 2026-09-28)` with LLVM `23.1.2`, and Zig `0.17.0`. Rust and Zig
IR/assembly were emitted successfully with the commands above. No current-source Elisa IR or timing result is
included: the current Stage1 seed is blocked by static store-flow errors in the compiler source.
The revision and tool versions describe this inspection environment; re-run and record them
when comparing outputs from a later source revision or another host.

In this inspection, Rust inlined the fold and generated a NEON loop that handles eight `i64`
values per branch (four two-lane vector accumulators), followed by a scalar tail. Zig inlined
the fold and generated eight two-lane vector accumulators across four paired vector loads,
handling sixteen `i64` values per branch. These are generated-code observations only; they do
not establish relative runtime performance or predict Elisa's output.
