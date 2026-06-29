#!/usr/bin/env bash
# Lexer throughput benchmark for the self-hosted (stage1) Elisa lexer.
#
# Compiles a tiny harness that drives frontend_lexer_stream_checksums_with_len
# (the pure token-stream path — no darray accumulation) over a large input file
# for N iterations, then times it from C with CLOCK_MONOTONIC and reports MB/s.
#
# This exists to keep lexer-perf decisions data-driven rather than by intuition.
# Notably, it is what showed that the lexer's `@inline(always)` annotations are
# worth ~10% throughput: the `-O2` inliner alone is too conservative to inline
# the hot per-char/per-token helpers (advance_char, read_type_suffix, the
# unicode-width helpers). Re-run this before adding or removing those.
#
# By default this builds the latest compiler from source (via resolve_elisac.sh)
# so the numbers always reflect current HEAD. Set ELISACORE_BIN to bench a
# specific prebuilt binary instead.
#
# Usage:
#   test/parity/lexer_bench.sh                 # build latest, default input + iters
#   ITERS=8000 test/parity/lexer_bench.sh      # more iterations
#   test/parity/lexer_bench.sh path/to/input.elisa
#   ELISACORE_BIN=/path/to/elisac test/parity/lexer_bench.sh   # pin a binary
#
# Output (stderr), three runs after a warmup:
#   <seconds> s  <MB/s>  (checksum <n>)
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

# Always bench a freshly built compiler (sets ELISACORE_BIN).
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

FIXTURE="$REPO_ROOT/test/fixtures/lexer/frontend_lexer.elisa"
# A large, realistic Elisa source (throughput is size-normalized, so any sizable
# real file works). The stream lexer only reads bytes, so semantics are
# irrelevant. Override by passing a path as $1.
INPUT="${1:-$REPO_ROOT/elisacore_std/collections.elisa}"
ITERS="${ITERS:-4000}"

command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
[[ -f "$INPUT" ]] || { echo "error: input not found: $INPUT" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/bench_harness.elisa" <<EOF
include "$FIXTURE"

def stage1_lexer_bench(source: u8&, source_len: usize, iters: u64) -> u64:
    can Memory.Allocate, Abort.Panic:
        acc: mutable u64 = 0
        i: mutable u64 = 0
        while i < iters:
            c: FrontendLexerChecksums = frontend_lexer_stream_checksums_with_len(source, source_len)
            acc <- acc ^ c.kind ^ (c.full * i)
            i <- i + 1
        return acc


export func stage1_lexer_bench_export(source: u8&, source_len: usize, iters: u64) -> u64 = stage1_lexer_bench
EOF

cat > "$WORK/bench_driver.c" <<'EOF'
#include "bench_harness.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static uint8_t *slurp(const char *path, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *buf = (uint8_t *)malloc((size_t)n + 1);
    if (!buf) { fclose(f); return NULL; }
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(buf); return NULL; }
    fclose(f);
    buf[n] = 0;
    *out_len = (size_t)n;
    return buf;
}

int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: %s <file> <iters>\n", argv[0]); return 2; }
    size_t n = 0;
    uint8_t *s = slurp(argv[1], &n);
    if (!s) { fprintf(stderr, "read failed: %s\n", argv[1]); return 3; }
    unsigned long long iters = strtoull(argv[2], NULL, 10);

    stage1_lexer_bench_export(s, n, iters > 100 ? 100 : iters); /* warmup */

    for (int run = 0; run < 3; run++) {
        struct timespec a, b;
        clock_gettime(CLOCK_MONOTONIC, &a);
        uint64_t r = stage1_lexer_bench_export(s, n, iters);
        clock_gettime(CLOCK_MONOTONIC, &b);
        double sec = (b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) / 1e9;
        double mb = (double)n * (double)iters / 1e6;
        fprintf(stderr, "%.4f s  %.1f MB/s  (checksum %llu)\n",
                sec, mb / sec, (unsigned long long)r);
    }
    free(s);
    return 0;
}
EOF

"$ELISACORE_BIN" -emit header -o "$WORK/bench_harness.h" "$WORK/bench_harness.elisa" >/dev/null
"$ELISACORE_BIN" -emit obj -O2 -o "$WORK/bench_harness.o" "$WORK/bench_harness.elisa" >/dev/null

link_flags=(-O2 -I "$WORK" "$WORK/bench_driver.c" "$WORK/bench_harness.o" -o "$WORK/bench")
# See run_parity.sh: non-PIC Elisa objects need dynamic_lookup on macOS, -no-pie on Linux.
[[ "$(uname -s)" == "Darwin" ]] && link_flags=(-Wl,-undefined,dynamic_lookup "${link_flags[@]}")
[[ "$(uname -s)" == "Linux" ]] && link_flags=(-no-pie "${link_flags[@]}")
clang "${link_flags[@]}"

echo "lexer bench: input=$(basename "$INPUT") ($(wc -l <"$INPUT" | tr -d ' ') lines), iters=$ITERS" >&2
"$WORK/bench" "$INPUT" "$ITERS"
