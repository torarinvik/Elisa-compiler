# fasta — Rust #9

- Source page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/fasta-rust-9.html
- Source file: `fasta/fasta.rust-9.rust` from https://benchmarksgame-team.pages.debian.net/benchmarksgame/download/benchmarksgame-sourcecode.zip (copied unmodified to `src/main.rs`)
- Ranking page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/performance/fasta.html
- Retrieved: 2026-10-13 (site build 25.03)
- Site measurement: 0.94 s elapsed, 3.20 s cpu, overall rank 10 on the secs-sorted page (rustc 1.84.1, quad-core x86-64 Ubuntu)
- Threads: multi-thread (std::thread)
- Selection: Rejected #7 (0.78 s, overall rank 1): core::arch::x86_64 SSE intrinsics + target_feature.
- Crates (pinned in Cargo.toml, transitive versions in Cargo.lock): num_cpus 1.16.0. The site does not publish crate versions; these are recent releases with the APIs the source uses.
- Build: edition 2015 (the site invokes plain rustc), `-C opt-level=3 -C codegen-units=1 -C target-cpu=native` (site: target-cpu=ivybridge), no panic=abort. See ../../build_refs.sh.
- Output verified against the site's fasta-output.txt at the small size: yes.
