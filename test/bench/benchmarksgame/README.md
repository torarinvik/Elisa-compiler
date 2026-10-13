# Benchmarks Game code generation campaign

The target set is the ten programs listed on the [Benchmarks Game index](https://benchmarksgame-team.pages.debian.net/benchmarksgame/index.html): fannkuch-redux, n-body, spectral-norm, mandelbrot, fasta, k-nucleotide, reverse-complement, binary-trees, pidigits, and regex-redux.

For each task, implement the specified algorithm in ordinary Elisa, with the specified command-line input and byte-for-byte expected output. Keep any workload-specific intrinsics, inline assembly, unsafe indexing, and hand-written SIMD out of the Elisa source. Record the exact source URL, revision or retrieval date, input size, compiler flags, and output hash for every comparator. The fastest published entry is the performance target, but its published elapsed time is **not** a directly comparable measurement on another machine. Compare Elisa and that entry on the same host, with identical input, output handling, CPU entitlement, and repeated runs. Also retain a simple scalar C or Rust version when the leader uses vector intrinsics or threads; this isolates code generation from algorithm and parallelism differences.

## When timing is unavailable

Keep the correctness preflight and inspect generated code instead. Elisa's `-emit ir -O3` writes optimized LLVM IR; use `-emit obj -O3` followed by `llvm-objdump -d` for assembly. For C/C++, compile the exact comparator source with its published flags plus `-S -emit-llvm` for IR, or `-S` for assembly. For Rust, use `--emit=llvm-ir,asm` with the comparator's release flags. For Zig, use `-femit-llvm-ir` and `-femit-asm` with its release mode. Pin toolchain versions and target CPU flags; where possible, compile both sides through the same LLVM release. Inspect the hot loop for bounds checks, heap allocations, calls, integer division, vectorization, alias metadata, and loop structure. Preserve the emitted files and command lines beside each case. IR/assembly differences are diagnostic evidence, not a substitute for measured speed.

For the current user-directed run, do not collect elapsed or CPU timings, run timing A/Bs, use `time -l`, capture profiles, or count retired instructions. Complete correctness checks first, then use static IR and assembly inspection only.

## Completion criteria per task

1. Elisa output matches the task's reference output at a small and official performance input.
2. The leading published program and a scalar algorithm peer have source provenance and reproduce the expected output locally.
3. A quiet host run records repeated elapsed and CPU times, peak memory, full output hashes, versions, flags, and host details. If the host is busy, record IR and assembly observations and leave the performance result pending.
4. Any compiler improvement is tested against this case and the existing full parity gate. A speed claim requires a same-host measurement with the same work and output.

The site's own [measurement notes](https://benchmarksgame-team.pages.debian.net/benchmarksgame/how-programs-are-measured.html) describe its isolated host and repeated measurements. Its rankings mix serial and parallel programs and mark some entries that may contain handwritten vector instructions or unsafe code; inspect source before selecting a comparison.
