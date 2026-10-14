# pidigits — Zig (1.zig)

The Computer Language Benchmarks Game has never published Zig programs (no zig
entries in its source zip or its git history at
https://salsa.debian.org/benchmarksgame-team/benchmarksgame). The Zig comparator is
taken from the closest maintained collection, hanabi1224's Programming Language
Benchmarks, which reuses the Benchmarks Game task definitions.

- Source: https://github.com/hanabi1224/Programming-Language-Benchmarks/blob/ad18b203dd1769724f4eea94fc3ac1e99f6593e0/bench/algorithm/pidigits/1.zig
- Original file kept as `pidigits.orig.zig`; ported file is `pidigits.zig` (diff them for the exact changes).
- Ranking page: https://programming-language-benchmarks.vercel.app/zig
- Retrieved: 2026-10-13
- PLB measurement (zig 0.14.1, their host): 2446 ms @ 8000; fastest published Zig variant for this task.
- Threads: single-thread
- Port to Zig 0.17: `main` takes std.process.Init and calls compat.setup (../compat.zig) for args/stdout/stdin. argsAlloc -> compat.argv. Uses std.math.big.int (no GMP), so it is far slower than GMP-based programs.
- Build: `zig build-exe -O ReleaseFast -mcpu=native -lc` (PLB: ReleaseFast + libc). See ../../build_refs.sh.
- Output verified against the Benchmarks Game pidigits-output.txt at the small size: yes.
