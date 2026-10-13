# Benchmarks Game code generation campaign

The target set is the ten programs listed on the [Benchmarks Game index](https://benchmarksgame-team.pages.debian.net/benchmarksgame/index.html): fannkuch-redux, n-body, spectral-norm, mandelbrot, fasta, k-nucleotide, reverse-complement, binary-trees, pidigits, and regex-redux.

For each task, implement the specified algorithm in ordinary Elisa, with the specified command-line input and byte-for-byte expected output. Keep any workload-specific intrinsics, inline assembly, unsafe indexing, and hand-written SIMD out of the Elisa source. Record the exact source URL, revision or retrieval date, input size, compiler flags, and output hash for every comparator. Compare Elisa with the leading published program and a scalar C or Rust peer by inspecting their generated LLVM IR and assembly under matched target flags. This isolates code generation from algorithm and parallelism differences; collect performance measurements only when the user authorizes them.

## Review and measurement for the current run

Keep the correctness preflight and inspect generated code. Elisa's `-emit ir -O3` writes optimized LLVM IR; use `-emit obj -O3` followed by `llvm-objdump -d` for assembly. For C/C++, compile the exact comparator source with its published flags plus `-S -emit-llvm` for IR, or `-S` for assembly. For Rust, use `--emit=llvm-ir,asm` with the comparator's release flags. For Zig, use `-femit-llvm-ir` and `-femit-asm` with its release mode. Pin toolchain versions and target CPU flags; where possible, compile both sides through the same LLVM release. Inspect the hot loop for bounds checks, heap allocations, calls, integer division, vectorization, alias metadata, and loop structure. Preserve the emitted files and command lines beside each case. IR/assembly differences show code-shape differences only and do not establish performance.

The user has authorized cache validation and instruction-count A/B measurements for the current compiler-optimization work. Use the paired runner in `test/bench/codegen_perf/` after the baseline and candidate pass provenance and correctness preflights. On macOS, it records retired instructions and cycles with `/usr/bin/time -l`; prioritize those counts, report wall/CPU time separately, and label local Mac results exploratory. Keep this authorization scoped to the current work; future runs need their own user direction before collecting measurements.

## Completion criteria per task

1. Elisa output matches the task's reference output at a small and official performance input.
2. The leading published program and a scalar algorithm peer have source provenance and reproduce the expected output locally.
3. When measurement is authorized, preserve paired raw samples, hardware-counter availability, correctness hashes, and exact compiler/source provenance; otherwise record only IR and assembly observations.
4. Check compiler improvements against this case and the existing full parity gate. Keep any performance claim within the evidence and host qualification recorded by the paired runner.

The site's own [measurement notes](https://benchmarksgame-team.pages.debian.net/benchmarksgame/how-programs-are-measured.html) describe its isolated host and repeated measurements. Its rankings mix serial and parallel programs and mark some entries that may contain handwritten vector instructions or unsafe code; inspect source before selecting a comparison.
