# fannkuchredux — Zig (2-m.zig)

The Computer Language Benchmarks Game has never published Zig programs (no zig
entries in its source zip or its git history at
https://salsa.debian.org/benchmarksgame-team/benchmarksgame). The Zig comparator is
taken from the closest maintained collection, hanabi1224's Programming Language
Benchmarks, which reuses the Benchmarks Game task definitions.

- Source: https://github.com/hanabi1224/Programming-Language-Benchmarks/blob/ad18b203dd1769724f4eea94fc3ac1e99f6593e0/bench/algorithm/fannkuch-redux/2-m.zig
- Original file kept as `fannkuchredux.orig.zig`; ported file is `fannkuchredux.zig` (diff them for the exact changes).
- Ranking page: https://programming-language-benchmarks.vercel.app/zig
- Retrieved: 2026-10-13
- PLB measurement (zig 0.14.1, their host): 639 ms @ 11 (2410 ms user); fastest published Zig variant for this task.
- Threads: multi-thread (std.Thread)
- Port to Zig 0.17: `main` takes std.process.Init and calls compat.setup (../compat.zig) for args/stdout/stdin. args/stdout via compat.zig. 3-i.zig (x86_64 inline asm pshufb) is not portable; 2-m is the fastest anyway. Bug fix: `applyMask` and `factorialComptime` looped `i < max_n`, so n == 12 (the official size) hit `unreachable` (silently wrong output in ReleaseFast); changed to `<=`. PLB only runs n <= 11.
- Build: `zig build-exe -O ReleaseFast -mcpu=native -lc` (PLB: ReleaseFast + libc). See ../../build_refs.sh.
- Output verified against the Benchmarks Game fannkuchredux-output.txt at the small size: yes.
