# knucleotide — Rust #7

- Source page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/knucleotide-rust-7.html
- Source file: `knucleotide/knucleotide.rust-7.rust` from https://benchmarksgame-team.pages.debian.net/benchmarksgame/download/benchmarksgame-sourcecode.zip (copied unmodified to `src/main.rs`)
- Ranking page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/performance/knucleotide.html
- Retrieved: 2026-10-13 (site build 25.03)
- Site measurement: 2.57 s elapsed, 8.01 s cpu, overall rank 2 on the secs-sorted page (rustc 1.84.1, quad-core x86-64 Ubuntu)
- Threads: multi-thread (tokio-threadpool)
- Selection: #7 is the fastest Rust entry and is portable.
- Crates (pinned in Cargo.toml, transitive versions in Cargo.lock): futures 0.1.31, tokio-threadpool 0.1.18, itertools 0.13.0, num 0.4.3, hashbrown 0.15.2. The site does not publish crate versions; these are recent releases with the APIs the source uses.
- Build: edition 2015 (the site invokes plain rustc), `-C opt-level=3 -C codegen-units=1 -C target-cpu=native` (site: target-cpu=ivybridge), no panic=abort. See ../../build_refs.sh.
- Output verified against the site's knucleotide-output.txt at the small size: yes.
