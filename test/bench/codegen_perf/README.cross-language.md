# Cross-language compiler and runtime benchmarks

`cross_language.sh` compares the Elisa and C kernels with equivalent Rust and Zig
implementations for `matmul`, `sieve`, `darray_sum`, `darray_count_sum`, `darray_growth`, and
`darray_counted_fill`. It measures
object-only compile time as the primary compiler metric, end-to-end executable build time as
a second metric, then checksums and times generated-program runtime.

Run it with:

```sh
REPEAT=5 BUILD_REPEAT=5 bash test/bench/codegen_perf/cross_language.sh build/codegen-perf-cross-language
```

The default `BENCH_PROFILE=fast` preserves the existing release comparison. For a
safety-enabled workload-source comparison of Elisa, Rust, and Zig, use:

```sh
BENCH_PROFILE=safe REPEAT=5 BUILD_REPEAT=5 \
  bash test/bench/codegen_perf/cross_language.sh build/codegen-perf-cross-language-safe
```

`BENCH_PROFILE` accepts `fast` or `safe` and is recorded in `metadata.txt`. The fast profile
uses Elisa `-foverflow=wrap`, Rust `-C overflow-checks=off`, and Zig `ReleaseFast`. The safe
profile uses Elisa `-foverflow=trap`, Rust `-C overflow-checks=on`, and Zig `ReleaseSafe`.
Clang remains at `-O3` in both profiles as an unchecked C baseline; do not describe its
results as safety-aligned. The safe settings enable checked arithmetic and the available
runtime safety checks for each workload source; they do not make the languages' memory-safety
models identical. Both profiles verify identical full checksums and process exit codes before
runtime measurements. The safe profile also builds a separate checked Elisa runtime object in
the selected output directory; it refuses an inherited `ELISA_RUNTIME_OBJ` override so the
runtime's arithmetic mode cannot silently differ from the benchmark profile.

For a compiler/build-only comparison without timed runtime samples, use
`COMPILE_ONLY=1 BUILD_REPEAT=5`. It records object-only and executable-build timings and skips
timed runtime samples. Exact checksum and exit-status parity still runs before the first timed
compiler/build sample and again after the timed executable builds; success writes
`COMPILE_COMPLETE` instead of the full-suite `COMPLETE`.

The suite is intentionally substantial: `matmul` performs 30 300×300 multiplies, `sieve`
runs 30 sieves of ten million entries, and `darray_sum` traverses four million entries 200
times. `darray_count_sum` preserves the same checksum, but moves both traversals into helpers
that each contain one ordinary counted loop. This lets candidates that prove `0..<xs.count` /
`xs[i]` be measured without nested loops. `REPEAT` controls runtime samples and `BUILD_REPEAT`
controls both compiler sample
sets; each defaults to five. `COMPILE_ONLY` accepts `0` or `1`; repeat counts accept positive
integers. Use more samples for claims from
a noisy host. `BENCH_TIMEOUT_SECONDS` defaults to 900 seconds and bounds each compiler or
program process group. `ELISA_STAGE1_BIN`, `ELISA_RUNTIME_OBJ`, `CLANG`, `RUSTC`, and `ZIG`
select the tool binaries and runtime object. `ELISA_STAGE1_TRIPLE` must be unset so every
implementation targets the host. The output directory must be empty; use a fresh path for
each run. `ELISA_RUNTIME_OPT_LEVEL` selects the safe profile's separately built runtime level
(`-O0` through `-O3`, default `-O2`). `COMPLETE` is written only after checksums and final
toolchain hashes pass.
On macOS, the runner first checks `load1 / logical_CPU <= 0.20` before starting preflight
builds, so a closed gate does not launch the benchmark build matrix. This admission check does
not establish correctness or authorize timing: exact correctness preflight is still required
before timing. The runner then checks the same limit before the first and every later compile,
build, and runtime sample, and again after each sample finishes. A pre-sample
violation starts no sample; a post-sample violation lets the in-flight sample finish, writes
`ABORTED.txt`, and prevents either completion marker from being written. Treat every partial
artifact from that run as unusable. This exploratory Mac gate does not change the separate
64-core x86_64 Linux qualification.

Release flags are recorded in `metadata.txt`. The default fast profile uses Elisa
`-O3 -foverflow=wrap`, C `clang -O3`, Rust `-C opt-level=3` with the toolchain's default
codegen-unit count and `-C target-cpu=native -C overflow-checks=off`, and Zig
`-O ReleaseFast -mcpu=native`; the safe profile substitutes Elisa `-foverflow=trap`, Rust
`-C overflow-checks=on`, and Zig
`-O ReleaseSafe`. Object-only timing uses Elisa `-emit obj`, Clang `-c`, Rust `--emit=obj`,
and Zig `build-obj`. End-to-end timing builds an executable with each compiler;
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
On macOS, Elisa and C executable links use the selected Homebrew `ld64.lld` explicitly, and
its resolved binary path and hash are recorded with the run. Rust and Zig executable builds
use their toolchain-selected linker defaults; the harness does not force them onto the same
linker, and `metadata.txt` records that policy. End-to-end build timings therefore include
this toolchain difference. Object-only compile time remains the primary compiler metric and
does not include executable linking.
For static LLVM configurations, the manifest also records the archive list reported by the
selected `llvm-config`. The runner does not content-hash the Linux external linker, compiler
sysroots and runtimes, SDK, dependencies of dynamic compiler libraries, or OS libraries;
comparisons assume those parts of the installed host toolchain remain fixed.
`sources.sha256` hashes the explicit workload files plus `.elisa`, `.elisai`, `.c`, `.h`,
`.sh`, and `.py` files under `src`, `elisacore_std`, and `scripts`, including uncommitted
edits. Stage1 provenance separately checks its recorded Elisa source tree and build recipe.
Edits to manifest inputs during initial builds or repeated compiler/build samples invalidate
the run.

`canonical_workload_fingerprint.json` records every workload's four source hashes, fixed
expected checksum/status, observed preflight checksum/status, the runner hash, host OS release
and build, CPU model and features, and compile profile. Its Elisa runtime profile records
whether the runtime was selected or rebuilt and, for the safe profile, the runtime optimization
level and checked overflow mode. The JSON record also carries the runtime object's SHA-256 as
per-run provenance outside the fingerprint payload. The safe profile rebuilds that object with
the selected Stage1 compiler, so candidate-generated runtime bytes may differ while workload
and profile parity still match. The compiler implementation sources and runtime artifact hash
are omitted from the parity payload so fingerprints can match across candidate revisions; the
same-host identity and runtime build settings remain gated. To require candidate parity before
any timed compiler sample, set
`ELISA_BENCH_EXPECT_CANONICAL_FINGERPRINT` to the primary run's fingerprint file. The candidate
run aborts before timing if a workload, profile, checksum, or status differs.

`compile_samples.csv` stores each rotated object-only compile wall time, waited-child CPU time
(user plus system), and host load averages before and after the sample; `compile_results.csv`
records best and median wall and CPU time. `build_samples.csv` and `build_results.csv` contain
the same measures for complete executable builds. Runtime `samples.csv` records load1 before
and after each runtime sample. Waited-child CPU includes compiler/linker subprocesses that are
reaped by their parent. Each compiler process group has a timeout so a stuck frontend, linker,
or child worker is killed with its parent.

`compile_ratios.csv`, `build_ratios.csv`, and `runtime_ratios.csv` report Elisa's median time
divided by Rust's and Zig's median time for each workload, with wall time and child CPU kept
separate. A ratio below `1.0` means Elisa is faster. Each file ends with an unweighted
geometric mean across the listed workloads; the per-workload raw measurements remain the source
of truth. Compile-only runs produce the compile and build ratio files but no runtime ratio file.

The ordinary Elisa semantic path is measured: incremental fact shadow/cache settings and
forced contracts are cleared, the opt-in Stage1 object cache is disabled, and Stage1 uses one
codegen job. Inherited target, diagnostic, profile, memory, and timing switches are cleared;
this includes `ELISA_DBG_*`, `ELISA_EXPLAIN_*`, and `ELISA_DEBUG_NODE_COUNT` diagnostics;
the harness sets the same Linux and x86_64 host markers as the wrapper. Zig receives
unique local and global cache directories for every compile and executable-build sample so
its own cache cannot turn later samples into hits; those directories are created before each
timer starts. The OS page cache remains under normal OS control, and the correctness preflights
and executable hashing can warm it. `metadata.txt` records these policies and the shared
source/toolchain fingerprints.
Before launching tools, the runner also clears inherited loader injection/debug variables
(`DYLD_INSERT_LIBRARIES`, `DYLD_FORCE_FLAT_NAMESPACE`, `LD_PRELOAD`, `LD_AUDIT`, `LD_DEBUG`,
and `LD_DEBUG_OUTPUT`) and common allocator tuning variables (`GLIBC_TUNABLES`, `MALLOC_*`,
`Malloc*`, `JEMALLOC_*`, `TCMALLOC_*`, and `MIMALLOC_*`). It records the cleared variable
names in `metadata.txt` without recording their values.

Runtime `samples.csv` stores every fresh-process wall and child CPU sample with launch order and
load1 before and after the sample;
`results.csv` records the matched full checksum and exit status, best and median wall and child
CPU times, and repeat count. The checksum preflight uses separate processes and does not warm
process-local state; its executions and the executable hash reads can warm host file caches.
These runs are not cold-start measurements. Timed launch order rotates across variants each
repetition.

After the post-build correctness preflight, `executables.after-build.sha256` records every final
workload executable by its path under the run output directory. Its SHA-256 is included in
`correctness_preflight.json`, tying the validated checksums to those exact binaries. Before timed
runtime samples, the runner verifies that all binaries still match the manifest; after each
sample it verifies the executed binary again. A full runtime run writes
`executables.after-runtime.sha256` and requires it to match the post-build manifest. Compile-only
runs still record the post-build manifest but do not produce an after-runtime manifest.

All variants must agree on the full checksum and process exit status before runtime timing.
The harness also checks independently calculated totals: `matmul` -432360, `sieve` 19937370,
both `darray_sum` and `darray_count_sum` 751804663071387784, `darray_growth` 3759023315128811,
and `darray_counted_fill` 7999998000000. Their exit statuses are respectively 113, 189, 152,
152, 72, and 8.
These fixed values catch a shared implementation mistake that a four-way agreement check
alone would miss.

Linux runs are marked qualified only on x86_64 with at least 64 affinity-available CPUs, a
shared cgroup namespace, a visible controller mount rooted at `/`, and no v1/v2 cgroup quota
below 64. The runner fails closed if it cannot verify those conditions; inspected paths and
the result are saved in `host_qualification.json`. Linux qualification establishes CPU capacity
and quota visibility, not a quiet host; load is recorded around every sample and heavily
contended runs should not support a speed claim. Mac runs are marked exploratory. The
qualification only covers the cgroups visible through `/proc`; outer quotas hidden from both
the process and PID 1 cannot be detected by this check. The
macOS runner selects the newest installed Homebrew LLVM through `brew --prefix llvm`, without
invoking `brew update`, and rejects a `CLANG` override from another toolchain. Stage1
provenance checks the matching `llvm-config`, Clang, and linked shared library or static
archives, including content hashes. Cross-language compile times cover only these kernels;
they do not replace the Stage1 self-compile gate, where phase timers separate parsing,
semantic analysis, LLVM optimization, and object emission.

## Interpretation limits

These are source-level workload comparisons, not a language-wide ranking. Elisa's `darray`
uses its region arena and compiler-generated capacity/bounds logic. The C/Rust/Zig versions
use contiguous allocations from the system allocator. C frees sieve flags on each call but
leaves the final buffers from `matmul.c`, `darray_sum.c`, `darray_count_sum.c`,
`darray_growth.c`, and `darray_counted_fill.c` for process teardown. Rust drops each sieve
`Vec` when the call returns,
and Zig's `defer` frees each sieve buffer; their final buffers in the other workloads are
reclaimed at process exit. Each sieve allocates a length-`n` byte buffer, initializes every
entry to one, clears entries zero and one, then marks composites. Rust initializes its vector
directly at the final length. Rust's `Vec` capacity is pre-sized for matmul, `darray_sum`,
`darray_count_sum`, and `darray_counted_fill`; its matmul inputs are then filled with `push`,
while C and Zig fill preallocated arrays by index. Elisa's matmul builds its three `n * n` arrays with unfiltered
comprehensions, which allocate each result once at its final size. The allocation sizes are
aligned, while the input fill forms differ; this keeps Elisa's source in expression-based style.
The `darray_growth` workload starts empty and appends four million values with geometric
logical capacity growth from 8 by doubling. Elisa's DArray delegates growth to its region arena;
when the backing allocation is the arena tail and the current region has room, `arena_realloc`
extends it in place without copying. Otherwise chained growth allocates a new block and copies
the old contents. C and Zig request each resize through `realloc`, and Rust uses
`Vec::reserve_exact`, so their allocators may also extend in place or may move the buffer. The
benchmark therefore compares each language's native growth path; it does not force equal
physical copy volume. A while loop prevents Elisa's counted-fill pre-reserve optimization from
eliminating the growth path. All four then run one indexed XOR pass and one iterator shift pass. The checksum is
`3759023315128811`, with exit status 72.

Both Elisa DArray sum workloads reserve capacity and push each LCG value once. Rust uses
`Vec::with_capacity` and `Vec::push`; C and Zig use fixture-local arrays with `items`, `count`,
and `capacity`, whose push operations check capacity, store at the next index, and increment
count. All four implementations use one fill pass. `darray_sum` uses an indexed first traversal
and an iterator second traversal; `darray_count_sum` uses two counted indexed traversals in
helpers. The fixed `darray_sum` and `darray_count_sum` workloads reserve room for all four
million values, so capacity exhaustion is not exercised there. `darray_count_sum` moves the two
checksum traversals into helpers that each contain one ordinary counted loop; the ordinary
`darray_sum` keeps both traversals in `main`. An
unreserved `n * n` push loop remains a separate compiler optimization case and is not
represented by the matched matmul comparison.

The `darray_counted_fill` workload starts with an empty Elisa DArray and fills it with one
ordinary `0..<4_000_000` loop that pushes the loop index. A zero-valued scalar declaration
between the DArray declaration and the loop prevents the separate declaration-time fill
optimizer from matching, so this isolates counted-loop pre-reservation without the LCG
arithmetic in `darray_count_sum`. Each language uses the same seed to initialize the sum;
C, Rust, and Zig reserve exactly four million slots before the fill. All four then run one
indexed sum pass. The checksum is `7999998000000`, with exit status 8.

Rust compile and executable-build samples use rustc's default codegen-unit setting, recorded in
the canonical profile and toolchain metadata. Object-only Rust samples write to a fresh output
directory because the default profile may emit multiple objects. Every object-only sample uses
a fresh per-sample output directory, and the runner requires nonempty object output so an old
artifact cannot satisfy a later sample's check. Executable-build samples remove their previous
binary before timing and require a nonempty executable result. The Zig fixtures print their
checksum to stderr while the other variants print to stdout. Preflight accepts either stream and requires
the same bytes, but tiny runtime comparisons include this output-path difference.

Elisa also keeps dynamic darray bounds checks in optimized output. Rust may prove checks
redundant in these indexed loops. Zig `ReleaseFast` disables safety checks and C has no bounds
checks, so the fast profile is not safety-aligned. `-foverflow=wrap` aligns signed-overflow
behavior but does not remove Elisa memory checks. The safe profile uses Rust's bounds-checking
release build, Zig `ReleaseSafe`, and checked arithmetic for Elisa source and runtime.

Elisa links a separately built runtime object; `scripts/build_runtime_object.sh` uses `-O2`
by default even when benchmark objects use `-O3`. The fast profile uses the selected runtime
object; the safe profile builds a separate `-O2` runtime with checked arithmetic. `metadata.txt`
records the runtime path, hash, and build mode. Fixed workload sizes keep signed arithmetic
in range in the fast profile; do not generalize that configuration to arbitrary programs. Use
`BENCH_PROFILE=safe` for checked arithmetic and Zig's safety-enabled release mode.
