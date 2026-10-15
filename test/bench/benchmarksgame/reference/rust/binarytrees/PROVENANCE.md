# binarytrees — Rust #5

- Source page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/binarytrees-rust-5.html
- Source file: `binarytrees/binarytrees.rust-5.rust` from https://benchmarksgame-team.pages.debian.net/benchmarksgame/download/benchmarksgame-sourcecode.zip (copied unmodified to `src/main.rs`)
- Ranking page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/performance/binarytrees.html
- Retrieved: 2026-10-13 (site build 25.03)
- Site measurement: 1.07 s elapsed, 3.72 s cpu, overall rank 2 on the secs-sorted page (rustc 1.84.1, quad-core x86-64 Ubuntu)
- Threads: multi-thread (rayon)
- Selection: #5 is the fastest Rust entry and is portable.
- Crates (pinned in Cargo.toml, transitive versions in Cargo.lock): bumpalo 3.16.0, rayon 1.10.0. The site does not publish crate versions; these are recent releases with the APIs the source uses.
- Build: edition 2015 (the site invokes plain rustc), `-C opt-level=3 -C codegen-units=1 -C target-cpu=native` (site: target-cpu=ivybridge), no panic=abort. See ../../build_refs.sh.
- Output verified against the site's binarytrees-output.txt at the small size: yes.
