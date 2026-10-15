# Benchmarks Game code generation campaign

The target set is the ten programs listed on the [Benchmarks Game index](https://benchmarksgame-team.pages.debian.net/benchmarksgame/index.html): fannkuch-redux, n-body, spectral-norm, mandelbrot, fasta, k-nucleotide, reverse-complement, binary-trees, pidigits, and regex-redux.

For each task, implement the specified algorithm in ordinary Elisa, with the specified command-line input and byte-for-byte expected output. Keep any workload-specific intrinsics, inline assembly, unsafe indexing, and hand-written SIMD out of the Elisa source. Record the exact source URL, revision or retrieval date, input size, compiler flags, and output hash for every comparator. Compare Elisa with the selected Rust and Zig programs by inspecting their generated LLVM IR and assembly under matched target flags. The current comparator set mixes single-threaded and multithreaded programs and does not provide a scalar peer for every task, so it cannot isolate language code generation or support an overall ranking.

## Review and measurement for the current run

Keep the correctness preflight and inspect generated code. Elisa's `-emit ir -O3` writes optimized LLVM IR; use `-emit obj -O3` followed by `llvm-objdump -d` for assembly. For C/C++, compile the exact comparator source with its published flags plus `-S -emit-llvm` for IR, or `-S` for assembly. For Rust, use `--emit=llvm-ir,asm` with the comparator's release flags. For Zig, use `-femit-llvm-ir` and `-femit-asm` with its release mode. Pin toolchain versions and target CPU flags; where possible, compile both sides through the same LLVM release. Inspect the hot loop for bounds checks, heap allocations, calls, integer division, vectorization, alias metadata, and loop structure. Preserve the emitted files and command lines beside each case. IR/assembly differences show code-shape differences only and do not establish performance.

Use the correctness preflight and compare generated IR and assembly before measuring. Collect runtime timings, profiles, cycles, or instruction counts only for a user-authorized paired run after exact source/toolchain provenance and output checks pass. Follow the paired runner's host-load and isolation requirements; on macOS, report instruction counts as exploratory evidence and wall/CPU time separately. These mixed serial/parallel comparators do not support an overall language ranking.

## Completion criteria per task

1. Elisa output matches the task's reference output at a small and official performance input.
2. Each selected Rust and Zig comparator has source provenance and reproduces the expected output locally; document missing peers and unsupported tasks.
3. Preserve exact toolchain and target provenance with the IR and assembly observations.
4. Check compiler improvements against this case and the existing full parity gate. Keep any performance claim within the evidence and host qualification recorded by the paired runner.

The site's own [measurement notes](https://benchmarksgame-team.pages.debian.net/benchmarksgame/how-programs-are-measured.html) describe its isolated host and repeated measurements. Its rankings mix serial and parallel programs and mark some entries that may contain handwritten vector instructions or unsafe code; inspect source before selecting a comparison.
