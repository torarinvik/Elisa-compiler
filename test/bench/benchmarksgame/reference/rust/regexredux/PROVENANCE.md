# regexredux — Rust #7

- Source page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/regexredux-rust-7.html
- Source file: `regexredux/regexredux.rust-7.rust` from https://benchmarksgame-team.pages.debian.net/benchmarksgame/download/benchmarksgame-sourcecode.zip (copied unmodified to `src/main.rs`)
- Ranking page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/performance/regexredux.html
- Retrieved: 2026-10-13 (site build 25.03)
- Site measurement: 0.78 s elapsed, 2.00 s cpu, overall rank 1 on the secs-sorted page (rustc 1.84.1, quad-core x86-64 Ubuntu)
- Threads: multi-thread (rayon)
- Selection: #7 is the fastest Rust entry and is portable.
- Crates (pinned in Cargo.toml, transitive versions in Cargo.lock): libc 0.2.169, pcre2-sys 0.2.9 (vendored PCRE2, JIT), rayon 1.10.0. The site does not publish crate versions; these are recent releases with the APIs the source uses.
- Build: edition 2015 (the site invokes plain rustc), `-C opt-level=3 -C codegen-units=1 -C target-cpu=native` (site: target-cpu=ivybridge), no panic=abort. See ../../build_refs.sh.
- Output verified against the site's regexredux-output.txt at the small size: yes.
