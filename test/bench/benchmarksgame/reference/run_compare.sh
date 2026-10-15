#!/bin/sh
# Compare Rust and Zig reference programs (and optionally an Elisa binary) on
# one Benchmarks Game task. Every output must match a checked-in oracle.
#
# usage: run_compare.sh <bench> [N|official] [elisa-binary]
#   bench: binarytrees fannkuchredux fasta knucleotide mandelbrot nbody
#          pidigits regexredux revcomp spectralnorm
#   N:     the program argument; for knucleotide/regexredux/revcomp it is the
#          fasta size used to generate stdin. Default: the site's small size.
#   Use N=official for the site's measured size.
# env:   BUILD_DIR (default reference/build), ORACLE_DIR (default reference/expected),
#        DATA_DIR for generated fasta inputs (default $TMPDIR/benchmarksgame-data),
#        RUNS (default 3; best wall time is reported).
#
# For small sizes, ORACLE_DIR/<bench>-output.txt is required. Other sizes need
# either <bench>-<N>-output.txt or <bench>-<N>-output.sha256. Hash files must
# contain exactly one lowercase or uppercase 64-digit SHA-256. No cross-only
# fallback is allowed when an oracle is missing.
set -eu
REF="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${BUILD_DIR:-$REF/build}"
ORACLE_DIR="${ORACLE_DIR:-$REF/expected}"
DATA_DIR="${DATA_DIR:-${TMPDIR:-/tmp}/benchmarksgame-data}"
RUNS="${RUNS:-3}"
b="${1:?usage: run_compare.sh <bench> [N|official] [elisa-binary]}"
N="${2:-}"
ELISA="${3:-}"

die() { echo "$*" >&2; exit 2; }
sha256_file() { shasum -a 256 < "$1" | awk '{print $1}'; }

case "$RUNS" in
  ''|*[!0-9]*) die "RUNS must be a positive integer (got '$RUNS')" ;;
esac
while [ "${RUNS#0}" != "$RUNS" ]; do RUNS=${RUNS#0}; done
[ -n "$RUNS" ] || die "RUNS must be greater than zero"

case "$b" in
  binarytrees)   small=10;   official=21 ;;
  fannkuchredux) small=7;    official=12 ;;
  fasta)         small=1000; official=25000000 ;;
  knucleotide)   small=1000; official=25000000 ;;
  mandelbrot)    small=200;  official=16000 ;;
  nbody)         small=1000; official=50000000 ;;
  pidigits)      small=30;   official=10000 ;;
  regexredux)    small=1000; official=5000000 ;;
  revcomp)       small=1000; official=100000000 ;;
  spectralnorm)  small=100;  official=5500 ;;
  *) die "unknown bench: $b" ;;
esac
[ -z "$N" ] && N=$small
[ "$N" = official ] && N=$official
case "$N" in
  ''|*[!0-9]*) die "N must be a positive integer or 'official' (got '$N')" ;;
esac
while [ "${N#0}" != "$N" ]; do N=${N#0}; done
[ -n "$N" ] || die "N must be greater than zero"
if [ "$b" = mandelbrot ] && ! printf '%s\n' "$N" | awk '
  { remainder = 0; for (i = 1; i <= length($0); i++) remainder = (remainder * 10 + substr($0, i, 1)) % 8 }
  END { exit remainder != 0 }
'; then
  die "mandelbrot requires N divisible by 8 for this port"
fi

# These tasks have no published Zig comparator. Refuse a one-language run so a
# successful exit always means the requested Rust/Zig comparison actually ran.
case "$b" in
  regexredux|revcomp)
    die "$b has no published Zig comparator; a Rust/Zig comparison is unavailable"
    ;;
esac

RUST_BIN="$BUILD_DIR/bin/rust/$b"
ZIG_BIN="$BUILD_DIR/bin/zig/$b"
[ -s "$RUST_BIN" ] && [ -x "$RUST_BIN" ] || die "missing Rust executable: $RUST_BIN (run build_refs.sh successfully first)"
[ -s "$ZIG_BIN" ] && [ -x "$ZIG_BIN" ] || die "missing Zig executable: $ZIG_BIN (run build_refs.sh successfully first)"
if [ -n "$ELISA" ]; then
  [ -s "$ELISA" ] && [ -x "$ELISA" ] || die "missing or non-executable Elisa binary: $ELISA"
fi

ORACLE_FILE=""
ORACLE_SHA256=""
ORACLE_DESCRIPTION=""
resolve_oracle() {
  oracle_bench=$1
  oracle_n=$2
  case "$oracle_bench" in
    binarytrees) oracle_small=10 ;;
    fannkuchredux) oracle_small=7 ;;
    fasta|knucleotide|nbody|regexredux|revcomp) oracle_small=1000 ;;
    mandelbrot) oracle_small=200 ;;
    pidigits) oracle_small=30 ;;
    spectralnorm) oracle_small=100 ;;
    *) die "no oracle size table for $oracle_bench" ;;
  esac
  if [ "$oracle_n" = "$oracle_small" ]; then
    file_oracle="$ORACLE_DIR/$oracle_bench-output.txt"
  else
    file_oracle="$ORACLE_DIR/$oracle_bench-$oracle_n-output.txt"
  fi
  hash_oracle="$ORACLE_DIR/$oracle_bench-$oracle_n-output.sha256"
  if [ -f "$file_oracle" ]; then
    [ -s "$file_oracle" ] || die "canonical output oracle is empty: $file_oracle"
    ORACLE_FILE=$file_oracle
    ORACLE_SHA256=$(sha256_file "$file_oracle")
    ORACLE_DESCRIPTION="file:$file_oracle"
  elif [ -f "$hash_oracle" ]; then
    if ! ORACLE_SHA256=$(awk '
      NF == 1 && length($1) == 64 && $1 ~ /^[0123456789abcdefABCDEF]+$/ {
        if (found) bad = 1
        value = tolower($1)
        found = 1
      }
      END { if (!found || bad) exit 1; print value }
    ' "$hash_oracle"); then
      die "invalid SHA-256 oracle file (expected one 64-digit hash): $hash_oracle"
    fi
    ORACLE_FILE=""
    ORACLE_DESCRIPTION="sha256:$hash_oracle"
  else
    die "missing canonical oracle for $oracle_bench N=$oracle_n; expected $file_oracle or $hash_oracle"
  fi
}
oracle_matches() {
  output_path=$1
  if [ -n "$ORACLE_FILE" ]; then
    cmp -s "$output_path" "$ORACLE_FILE"
  else
    actual_sha=$(sha256_file "$output_path") || return 1
    [ "$actual_sha" = "$ORACLE_SHA256" ]
  fi
}

resolve_oracle "$b" "$N"
TASK_ORACLE_FILE=$ORACLE_FILE
TASK_ORACLE_SHA256=$ORACLE_SHA256
TASK_ORACLE_DESCRIPTION=$ORACLE_DESCRIPTION

stdin_bench=0
case "$b" in knucleotide|regexredux|revcomp) stdin_bench=1 ;; esac

WORK="$(mktemp -d "${TMPDIR:-/tmp}/bgcmp.XXXXXX")"
INPUT_TMP=""
META_TMP=""
cleanup() {
  [ -z "$INPUT_TMP" ] || rm -f "$INPUT_TMP"
  [ -z "$META_TMP" ] || rm -f "$META_TMP"
  rm -rf "$WORK"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

INPUT=/dev/null
INPUT_SHA256=""
INPUT_BYTES=""
GENERATOR_SHA256=""
if [ "$stdin_bench" -eq 1 ]; then
  # The FASTA bytes are themselves checked against a canonical oracle. The
  # sidecar binds the cache to N, the exact generator binary, oracle, byte count,
  # and content hash; unproven or altered cache entries are regenerated.
  resolve_oracle fasta "$N"
  FASTA_ORACLE_FILE=$ORACLE_FILE
  FASTA_ORACLE_SHA256=$ORACLE_SHA256
  DATA_GENERATOR="$BUILD_DIR/bin/rust/fasta"
  [ -s "$DATA_GENERATOR" ] && [ -x "$DATA_GENERATOR" ] || die "missing Rust FASTA input generator: $DATA_GENERATOR"
  GENERATOR_SHA256=$(sha256_file "$DATA_GENERATOR")
  mkdir -p "$DATA_DIR"
  INPUT="$DATA_DIR/fasta-$N.txt"
  INPUT_META="$INPUT.provenance"
  INPUT_TMP="$INPUT.tmp.$$"
  META_TMP="$INPUT_META.tmp.$$"

  input_metadata() {
    printf 'format=benchmarksgame-fasta-input-v1\n'
    printf 'size=%s\n' "$N"
    printf 'generator_sha256=%s\n' "$GENERATOR_SHA256"
    printf 'oracle_sha256=%s\n' "$FASTA_ORACLE_SHA256"
    printf 'input_bytes=%s\n' "$INPUT_BYTES"
    printf 'input_sha256=%s\n' "$INPUT_SHA256"
  }

  cache_valid=0
  if [ -s "$INPUT" ] && [ -f "$INPUT_META" ]; then
    INPUT_SHA256=$(sha256_file "$INPUT")
    INPUT_BYTES=$(wc -c < "$INPUT" | tr -d '[:space:]')
    expected_metadata=$(input_metadata)
    if [ "$(cat "$INPUT_META")" = "$expected_metadata" ] && oracle_matches "$INPUT"; then
      cache_valid=1
    fi
  fi
  if [ "$cache_valid" -ne 1 ]; then
    echo "generating canonical FASTA input $INPUT" >&2
    if ! nice -n 10 "$DATA_GENERATOR" "$N" > "$INPUT_TMP"; then
      die "Rust FASTA input generation failed for N=$N"
    fi
    if ! oracle_matches "$INPUT_TMP"; then
      die "generated FASTA input does not match canonical oracle for N=$N"
    fi
    INPUT_SHA256=$(sha256_file "$INPUT_TMP")
    INPUT_BYTES=$(wc -c < "$INPUT_TMP" | tr -d '[:space:]')
    mv "$INPUT_TMP" "$INPUT"
    INPUT_TMP=""
    input_metadata > "$META_TMP"
    mv "$META_TMP" "$INPUT_META"
    META_TMP=""
  fi
  echo "input_provenance: path=$INPUT size=$N bytes=$INPUT_BYTES sha256=$INPUT_SHA256 generator_sha256=$GENERATOR_SHA256 fasta_oracle_sha256=$FASTA_ORACLE_SHA256" >&2
  ARG=0
else
  ARG=$N
fi

# Input generation temporarily selects the FASTA oracle. Restore the task's
# output oracle before checking any Rust, Zig, or Elisa benchmark run.
ORACLE_FILE=$TASK_ORACLE_FILE
ORACLE_SHA256=$TASK_ORACLE_SHA256
ORACLE_DESCRIPTION=$TASK_ORACLE_DESCRIPTION

printf 'canonical_oracle: task=%s N=%s sha256=%s source=%s\n' \
  "$b" "$N" "$TASK_ORACLE_SHA256" "$TASK_ORACLE_DESCRIPTION"
if [ -n "$INPUT_SHA256" ]; then
  printf 'canonical_input: fasta N=%s bytes=%s sha256=%s generator_sha256=%s\n' \
    "$N" "$INPUT_BYTES" "$INPUT_SHA256" "$GENERATOR_SHA256"
fi
printf '%-6s %-10s %9s %10s %9s  %s\n' impl bench wall_s usr+sys_s rss_MB output

run_one() {  # name binary
  name=$1
  bin=$2
  best=""
  best_cpu=""
  best_rss=""
  i=1
  while [ "$i" -le "$RUNS" ]; do
    output_path="$WORK/$name-$i.out"
    time_path="$WORK/$name-$i.time"
    if nice -n 10 /usr/bin/time -l "$bin" "$ARG" < "$INPUT" > "$output_path" 2> "$time_path"; then
      :
    else
      run_status=$?
      echo "$name: exit status $run_status on run $i" >&2
      tail -5 "$time_path" >&2 || true
      exit 1
    fi
    if ! oracle_matches "$output_path"; then
      echo "$name: output from run $i does not match canonical oracle $TASK_ORACLE_DESCRIPTION" >&2
      exit 1
    fi
    if ! parsed=$(awk '
      / real / { r = $1; u = $3; s = $5 }
      /maximum resident set size/ { m = $1 }
      END {
        if (r == "" || u == "" || s == "" || m == "") exit 1
        printf "%.3f %.2f %.1f", r, u + s, m / 1048576
      }
    ' "$time_path"); then
      echo "$name: could not parse wall/CPU/RSS from /usr/bin/time output on run $i" >&2
      exit 1
    fi
    set -- $parsed
    wall=$1
    cpu=$2
    rss=$3
    if [ -z "$best" ] || awk "BEGIN { exit !($wall < $best) }"; then
      best=$wall
      best_cpu=$cpu
      best_rss=$rss
    fi
    i=$((i + 1))
  done
  printf '%-6s %-10s %9s %10s %9s  %s\n' \
    "$name" "$b" "$best" "$best_cpu" "$best_rss" "all $RUNS runs match canonical oracle"
}

run_one rust "$RUST_BIN"
run_one zig "$ZIG_BIN"
if [ -n "$ELISA" ]; then run_one elisa "$ELISA"; fi
