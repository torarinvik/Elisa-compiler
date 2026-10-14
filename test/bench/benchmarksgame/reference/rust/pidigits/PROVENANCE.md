# pidigits — Rust #4

- Source page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/pidigits-rust-4.html
- Source file: `pidigits/pidigits.rust-4.rust` from https://benchmarksgame-team.pages.debian.net/benchmarksgame/download/benchmarksgame-sourcecode.zip (copied unmodified to `src/main.rs`)
- Ranking page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/performance/pidigits.html
- Retrieved: 2026-10-13 (site build 25.03)
- Site measurement: 0.71 s elapsed, 0.71 s cpu, overall rank 1 on the secs-sorted page (rustc 1.84.1, quad-core x86-64 Ubuntu)
- Threads: single-thread
- Selection: #4 is the fastest Rust entry and is portable.
- Crates (pinned in Cargo.toml, transitive versions in Cargo.lock): rug 1.26.1 (integer only) + gmp-mpfr-sys 1.6.4 with use-system-libs (Homebrew GMP). The site does not publish crate versions; these are recent releases with the APIs the source uses.
- Build: edition 2015 (the site invokes plain rustc), `-C opt-level=3 -C codegen-units=1 -C target-cpu=native` (site: target-cpu=ivybridge), no panic=abort. See ../../build_refs.sh.
- Output verified against the site's pidigits-output.txt at the small size: yes.
