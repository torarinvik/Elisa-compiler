# nbody — Rust #3

- Source page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/nbody-rust-3.html
- Source file: `nbody/nbody.rust-3.rust` from https://benchmarksgame-team.pages.debian.net/benchmarksgame/download/benchmarksgame-sourcecode.zip (copied unmodified to `src/main.rs`)
- Ranking page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/performance/nbody.html
- Retrieved: 2026-10-13 (site build 25.03)
- Site measurement: 3.46 s elapsed, 3.46 s cpu, overall rank 7 on the secs-sorted page (rustc 1.84.1, quad-core x86-64 Ubuntu)
- Threads: single-thread
- Selection: Rejected #9 (2.19 s, rank 3; AVX _mm256_*) and #7 (3.24 s, rank 5; SSE _mm_*), both std::arch::x86_64.
- Crates (pinned in Cargo.toml, transitive versions in Cargo.lock): (none). The site does not publish crate versions; these are recent releases with the APIs the source uses.
- Build: edition 2015 (the site invokes plain rustc), `-C opt-level=3 -C codegen-units=1 -C target-cpu=native` (site: target-cpu=ivybridge), no panic=abort. See ../../build_refs.sh.
- Output verified against the site's nbody-output.txt at the small size: yes.
