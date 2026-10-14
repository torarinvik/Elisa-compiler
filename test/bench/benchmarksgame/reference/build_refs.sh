#!/bin/sh
# Build the Rust and Zig Benchmarks Game reference programs (aarch64 / macOS).
#
# usage: build_refs.sh [bench ...]        (default: all ten)
# env:   BUILD_DIR   output root (default: reference/build, git-ignored)
#        JOBS        parallel jobs (default 4)
#
# Binaries land in $BUILD_DIR/bin/{rust,zig}/<bench>.
# Rust flags follow the site's MAKE line (rustc -C opt-level=3 -C codegen-units=1
# -C target-cpu=<host>), with target-cpu=native instead of ivybridge; no
# panic=abort (the site does not use it). Edition 2015 = plain rustc default.
# Zig: -O ReleaseFast -mcpu=native -lc (PLB build.zig uses ReleaseFast + libc).
set -eu
REF="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${BUILD_DIR:-$REF/build}"
JOBS="${JOBS:-4}"
ALL="binarytrees fannkuchredux fasta knucleotide mandelbrot nbody pidigits regexredux revcomp spectralnorm"
[ $# -gt 0 ] && ALL="$*"
mkdir -p "$BUILD_DIR/bin/rust" "$BUILD_DIR/bin/zig"

# Validate names before touching any previous products, then remove products for
# every requested task. A failed or skipped rebuild must never leave an older
# executable looking like the result of this invocation.
for b in $ALL; do
  case "$b" in
    binarytrees|fannkuchredux|fasta|knucleotide|mandelbrot|nbody|pidigits|regexredux|revcomp|spectralnorm) ;;
    *) echo "unknown benchmark: $b" >&2; exit 2 ;;
  esac
done
for b in $ALL; do
  rm -f "$BUILD_DIR/bin/rust/$b" "$BUILD_DIR/bin/zig/$b"
done

GMP="$(brew --prefix gmp 2>/dev/null || echo /opt/homebrew)"
export CARGO_TARGET_DIR="$BUILD_DIR/rust-target"
export RUSTFLAGS="-C target-cpu=native"
# pidigits: rug/gmp-mpfr-sys with use-system-libs links Homebrew GMP.
export CPATH="$GMP/include${CPATH:+:$CPATH}"
export LIBRARY_PATH="$GMP/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"

rc=0
for b in $ALL; do
  if [ -f "$REF/rust/$b/Cargo.toml" ]; then
    if (cd "$REF/rust/$b" && nice -n 10 cargo build --release --locked -q -j "$JOBS"); then
      rust_product="$CARGO_TARGET_DIR/release/$b"
      if [ -s "$rust_product" ] && [ -x "$rust_product" ]; then
        if cp "$rust_product" "$BUILD_DIR/bin/rust/$b" \
            && [ -s "$BUILD_DIR/bin/rust/$b" ] && [ -x "$BUILD_DIR/bin/rust/$b" ]; then
          echo "rust  $b ok"
        else
          rm -f "$BUILD_DIR/bin/rust/$b"
          echo "rust  $b FAILED: copy failed or produced no executable" >&2; rc=1
        fi
      else
        echo "rust  $b FAILED: cargo produced no executable at $rust_product" >&2; rc=1
      fi
    else
      echo "rust  $b FAILED" >&2; rc=1
    fi
  else
    echo "rust  $b FAILED: missing Cargo.toml" >&2; rc=1
  fi
  if [ -f "$REF/zig/$b/$b.zig" ]; then
    if nice -n 10 zig build-exe -O ReleaseFast -mcpu=native -lc -j"$JOBS" \
        --cache-dir "$BUILD_DIR/zig-cache" --dep compat \
        "-Mroot=$REF/zig/$b/$b.zig" "-Mcompat=$REF/zig/compat.zig" \
        -femit-bin="$BUILD_DIR/bin/zig/$b" \
        && [ -s "$BUILD_DIR/bin/zig/$b" ] && [ -x "$BUILD_DIR/bin/zig/$b" ]; then
      echo "zig   $b ok"
    else
      rm -f "$BUILD_DIR/bin/zig/$b"
      echo "zig   $b FAILED: compiler failed or produced no executable" >&2; rc=1
    fi
  else
    case "$b" in
      regexredux|revcomp) echo "zig   $b (no published Zig comparator; skipped)" ;;
      *) echo "zig   $b FAILED: missing Zig source" >&2; rc=1 ;;
    esac
  fi
done
exit $rc
