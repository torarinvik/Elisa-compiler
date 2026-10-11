# Cross-language compiler and runtime benchmarks

`cross_language.sh` compares the Elisa and C kernels with equivalent Rust and Zig
implementations for `matmul`, `sieve`, and `darray_sum`. It measures object-only compile time
as the primary compiler metric, end-to-end executable build time as a second metric, then
checksums and times generated-program runtime.

Run it with:

```sh
REPEAT=5 BUILD_REPEAT=5 bash test/bench/codegen_perf/cross_language.sh build/codegen-perf-cross-language
```

For a compiler/build-only comparison while workload output is under repair, use
`COMPILE_ONLY=1 BUILD_REPEAT=5`. It records object-only and executable-build timings, skips
checksum and runtime checks, and writes `COMPILE_COMPLETE` instead of the full-suite `COMPLETE`.

The suite is intentionally substantial: `matmul` performs 30 300×300 multiplies, `sieve`
runs 30 sieves of ten million entries, and `darray_sum` traverses four million entries 200
times. `REPEAT` controls runtime samples and `BUILD_REPEAT` controls both compiler sample
sets; each defaults to five. `COMPILE_ONLY` accepts `0` or `1`; repeat counts accept positive
integers. Use more samples for claims from
a noisy host. `BENCH_TIMEOUT_SECONDS` defaults to 900 seconds and bounds each compiler or
program process group. `ELISA_STAGE1_BIN`, `ELISA_RUNTIME_OBJ`, `CLANG`, `RUSTC`, and `ZIG`
select the tool binaries and runtime object. `ELISA_STAGE1_TRIPLE` must be unset so every
implementation targets the host. The output directory must be empty; use a fresh path for
each run. `COMPLETE` is written only after checksums and final toolchain hashes pass.

Release flags are recorded in `metadata.txt`: Elisa `-O3 -foverflow=wrap`, C `clang -O3`,
Rust `-C opt-level=3 -C codegen-units=1 -C target-cpu=native -C overflow-checks=off`, and Zig
`-O ReleaseFast -mcpu=native`. Object-only timing uses Elisa `-emit obj`, Clang `-c`, Rust
`--emit=obj`, and Zig `build-obj`. End-to-end timing builds an executable with each compiler;
Elisa's measurement includes Stage1 object emission and native linking. The Elisa backend
uses LLVM host CPU features when no target triple is specified; C, Rust, and Zig receive
native CPU flags. Elisa dead-strip and executable-link flags are re-derived by
`scripts/platform.sh` and their resolved values are recorded in `metadata.txt`.

The runner checks Stage1 provenance against the checkout before building. Timed Elisa samples
invoke the Stage1 product directly with the wrapper's pinned compiler, runtime, repository, and
host environment; this keeps wrapper freshness checks and RSS polling out of compiler timings.
The untimed correctness preflight still uses `scripts/elisac_stage1.sh`. It records the
compiler versions, source-manifest hash, Stage1/runtime hashes, LLVM version and linked
library, Rust toolchain, host CPU, and repository revision. `toolchain.before.sha256`,
`toolchain.after-build.sha256`, and `toolchain.after-run.sha256` pin the selected compiler
executables, Stage1 product, runtime object, `llvm-config`, and detected LLVM shared library.
For static LLVM configurations, the manifest also records the archive list reported by the
selected `llvm-config`. The runner does not content-hash the external linker, compiler
sysroots and runtimes, SDK, dependencies of dynamic compiler libraries, or OS libraries;
comparisons assume those parts of the installed host toolchain remain fixed.
`sources.sha256` hashes the explicit workload files plus `.elisa`, `.elisai`, `.c`, `.h`,
`.sh`, and `.py` files under `src`, `elisacore_std`, and `scripts`, including uncommitted
edits. Stage1 provenance separately checks its recorded Elisa source tree and build recipe.
Edits to manifest inputs during initial builds or repeated compiler/build samples invalidate
the run.

`compile_samples.csv` stores each rotated object-only compile wall time, waited-child CPU time
(user plus system), and host load averages before and after the sample; `compile_results.csv`
records best and median wall and CPU time. `build_samples.csv` and `build_results.csv` contain
the same measures for complete executable builds. Waited-child CPU includes compiler/linker
subprocesses that are reaped by their parent. Each compiler process group has a timeout so a
stuck frontend, linker, or child worker is killed with its parent.

The ordinary Elisa semantic path is measured: incremental fact shadow/cache settings and
forced contracts are cleared, the opt-in Stage1 object cache is disabled, and Stage1 uses one
codegen job. Inherited target, diagnostic, profile, memory, and timing switches are cleared;
this includes `ELISA_DBG_*`, `ELISA_EXPLAIN_*`, and `ELISA_DEBUG_NODE_COUNT` diagnostics;
the harness sets the same Linux and x86_64 host markers as the wrapper. Zig receives
unique local and global cache directories for every compile and executable-build sample so
its own cache cannot turn later samples into hits; those directories are created before each
timer starts. The OS page cache remains under normal OS control. `metadata.txt` records these
policies and the shared source/toolchain fingerprints.

Runtime `samples.csv` stores every fresh-process wall and child CPU sample with launch order;
`results.csv` records the matched full checksum and exit status, best and median wall and child
CPU times, and repeat count. The checksum preflight is separate from timed runs and is not a
warmup for their fresh processes. Timed launch order rotates across variants each repetition.

All variants must agree on the full checksum and process exit status before runtime timing.
The harness also checks independently calculated totals: `matmul` -432360, `sieve` 19937370,
and `darray_sum` 751804663071387784. Their exit statuses are respectively 113, 189, and 152.
These fixed values catch a shared implementation mistake that a four-way agreement check
alone would miss.

Linux runs are marked qualified only on x86_64 with at least 64 affinity-available CPUs, a
shared cgroup namespace, a visible controller mount rooted at `/`, and no v1/v2 cgroup quota
below 64. The runner fails closed if it cannot verify those conditions; inspected paths and
the result are saved in `host_qualification.json`. Mac runs are marked exploratory. The
qualification only covers the cgroups visible through `/proc`; outer quotas hidden from both
the process and PID 1 cannot be detected by this check. The
macOS runner selects LLVM through `brew --prefix llvm`, ignoring inherited LLVM path
overrides, and records the resolved path and version. Cross-language compile times cover
only these kernels; they do not replace the Stage1 self-compile gate, where phase timers separate parsing,
semantic analysis, LLVM optimization, and object emission.

## Interpretation limits

These are source-level workload comparisons, not a language-wide ranking. Elisa's `darray`
uses its region arena and compiler-generated capacity/bounds logic. The C/Rust/Zig versions
use contiguous allocations from the system allocator; sieve frees its flags on each call,
while the existing C `matmul.c` and `darray_sum.c` leave their process-lifetime buffers for
process teardown. Rust's `Vec` capacity is pre-sized for matmul and darray_sum. Elisa's
matmul builds its three `n * n` arrays with unfiltered comprehensions, which allocate each
result once at its final size. This matches the other implementations' pre-sized allocation
plan while keeping the Elisa source in expression-based style.
Elisa's darray_sum creates a zero-filled array comprehension, then overwrites each entry with
the same LCG values used by the other languages; this adds one initialization pass before the
timed checksum loops. An unreserved `n * n` push loop remains a separate compiler optimization
case and is not represented by the matched matmul comparison.

Elisa also keeps dynamic darray bounds checks in optimized output. Rust may prove checks
redundant in these indexed loops, Zig ReleaseFast disables safety checks, and C has no bounds
checks. `-foverflow=wrap` aligns signed-overflow behavior but does not remove Elisa memory
safety checks. A separate safety-preserving comparison should use Rust's bounds-checking
release build and Zig `ReleaseSafe` alongside Elisa's checked build.

Elisa links a separately built runtime object; `scripts/build_runtime_object.sh` uses `-O2`
by default even when benchmark objects use `-O3`. The runtime object path and hash are recorded
so results can be reproduced with another selected runtime build. Fixed workload sizes keep
signed arithmetic in range, so Elisa and Rust overflow checks are disabled to align with C
and Zig ReleaseFast. Do not generalize this configuration to arbitrary programs. For checked
arithmetic, use Elisa `-foverflow=trap`, Rust `-C overflow-checks=on`, and a Zig safety-enabled
release mode as a separate configuration.
