# Borrowed DArray fold probe

This focused probe compares a read-only fold over a borrowed DArray formal with Rust slice
iteration and Zig slice iteration. Each program fills four million `i64` values from the same
wrapping `u64` recurrence, then sums the slice 200 times. Each prints the same full checksum
and exits with `checksum % 251`. No timing claim is attached to this fixture.

## Build and inspect

Run from the repository root. Use a current Stage1 product for Elisa; LLVM IR output from an
older product does not validate current source lowering.

```sh
ELISA_STAGE1_BIN=bin/elisac-stage1 \
  scripts/elisac_stage1.sh -emit llvm -O3 -foverflow=wrap \
  -o /tmp/borrowed-darray-elisa.ll test/bench/borrowed_darray_fold/sum.elisa
ELISA_STAGE1_BIN=bin/elisac-stage1 \
  scripts/elisac_stage1.sh -emit llvm -O3 -foverflow=wrap \
  -o /tmp/borrowed-darray-interleave8.ll test/bench/borrowed_darray_fold/sum_interleave8.elisa

rustc test/bench/borrowed_darray_fold/sum.rs --edition=2021 \
  -C opt-level=3 -C target-cpu=native -C overflow-checks=off \
  --emit=llvm-ir=/tmp/borrowed-darray-rust.ll
rustc test/bench/borrowed_darray_fold/sum.rs --edition=2021 \
  -C opt-level=3 -C target-cpu=native -C overflow-checks=off \
  --emit=asm=/tmp/borrowed-darray-rust.s

zig build-exe test/bench/borrowed_darray_fold/sum.zig -O ReleaseFast \
  -mcpu=native -lc -femit-llvm-ir=/tmp/borrowed-darray-zig.ll \
  -femit-asm=/tmp/borrowed-darray-zig.s \
  -femit-bin=/tmp/borrowed-darray-zig
```

The cross-language flags correspond to the fast profile used by
`test/bench/codegen_perf/cross_language.sh`: Elisa O3 with wrapping arithmetic, Rust O3 with
native CPU features and overflow checks off, and Zig ReleaseFast for the native CPU. Capture
compiler versions, host CPU, repository revision, and source hashes alongside any later IR or
timing result. The five files in this directory are the complete probe inputs; `SHA256SUMS`
pins their contents. Timing requires a separate qualified benchmark run with equivalent
correctness preflight and host controls.

The baseline Elisa function takes `darray[i64]&` explicitly and iterates with `for value in xs`;
Rust uses `&[i64]` and `for &value in xs`; Zig uses `[]const i64` and `for (xs)`. The optional
`sum_interleave8.elisa` keeps the same data and checksum but spells the reduction as an indexed
ascending range with `by interleave(8)`. It tests the current LLVM loop hint against the baseline;
8 is a candidate because synthetic LLVM shows it can target 16 `i64`s per backedge, matching
Zig's native loop width. This remains a code-shape hypothesis until current Stage1 output is
available. Main's allocation and fill stay outside the fold helper.

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
