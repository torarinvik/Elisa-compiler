# mandelbrot — Rust #4

- Source page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/mandelbrot-rust-4.html
- Source file: `mandelbrot/mandelbrot.rust-4.rust` from https://benchmarksgame-team.pages.debian.net/benchmarksgame/download/benchmarksgame-sourcecode.zip (copied unmodified to `src/main.rs`)
- Ranking page: https://benchmarksgame-team.pages.debian.net/benchmarksgame/performance/mandelbrot.html
- Retrieved: 2026-10-13 (site build 25.03)
- Site measurement: 0.95 s elapsed, 3.78 s cpu, overall rank 3 on the secs-sorted page (rustc 1.84.1, quad-core x86-64 Ubuntu)
- Threads: multi-thread (rayon)
- Selection: #4 is the fastest Rust entry; uses portable [f64; N] lane arrays, no intrinsics.
- Crates (pinned in Cargo.toml, transitive versions in Cargo.lock): rayon 1.10.0. The site does not publish crate versions; these are recent releases with the APIs the source uses.
- Build: edition 2015 (the site invokes plain rustc), `-C opt-level=3 -C codegen-units=1 -C target-cpu=native` (site: target-cpu=ivybridge), no panic=abort. See ../../build_refs.sh.
- Output verified against the site's mandelbrot-output.txt at the small size: yes.
