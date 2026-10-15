# spectralnorm — Rust #5

- Source page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/spectralnorm-rust-5.html
- Source file: `spectralnorm/spectralnorm.rust-5.rust` from https://benchmarksgame-team.pages.debian.net/benchmarksgame/download/benchmarksgame-sourcecode.zip (copied unmodified to `src/main.rs`)
- Ranking page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/performance/spectralnorm.html
- Retrieved: 2026-10-13 (site build 25.03)
- Site measurement: 0.72 s elapsed, 2.85 s cpu, overall rank 4 on the secs-sorted page (rustc 1.84.1, quad-core x86-64 Ubuntu)
- Threads: multi-thread (rayon)
- Selection: Rejected #6 (0.72 s, rank 3): std::arch::x86_64 _mm_* + target_feature.
- Crates (pinned in Cargo.toml, transitive versions in Cargo.lock): rayon 1.10.0. The site does not publish crate versions; these are recent releases with the APIs the source uses.
- Build: edition 2015 (the site invokes plain rustc), `-C opt-level=3 -C codegen-units=1 -C target-cpu=native` (site: target-cpu=ivybridge), no panic=abort. See ../../build_refs.sh.
- Output verified against the site's spectralnorm-output.txt at the small size: yes.
