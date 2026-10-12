#!/usr/bin/env bash
# Run exact-parity preflights for two Elisa compiler binaries, then sample them
# in A-B-B-A order and report paired per-workload ratios.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
RUNNER="$SCRIPT_DIR/cross_language.sh"

if (( $# < 2 || $# > 3 )); then
  echo "usage: paired_cross_language.sh REFERENCE_STAGE1 CANDIDATE_STAGE1 [OUTPUT_DIR]" >&2
  exit 2
fi
REFERENCE_BIN="$(cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")"
CANDIDATE_BIN="$(cd -- "$(dirname -- "$2")" && pwd)/$(basename -- "$2")"
OUT="${3:-$ROOT/build/codegen-perf-paired}"
mkdir -p "$OUT"
OUT="$(cd -- "$OUT" && pwd -P)"
if [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "output directory is not empty: $OUT (choose a fresh directory)" >&2
  exit 2
fi
[[ -x "$REFERENCE_BIN" ]] || { echo "reference compiler is not executable: $REFERENCE_BIN" >&2; exit 2; }
[[ -x "$CANDIDATE_BIN" ]] || { echo "candidate compiler is not executable: $CANDIDATE_BIN" >&2; exit 2; }

PAIRED_BLOCKS="${PAIRED_BLOCKS:-1}"
[[ "$PAIRED_BLOCKS" =~ ^[1-9][0-9]*$ ]] || { echo "PAIRED_BLOCKS must be a positive integer" >&2; exit 2; }

mark_incomplete_pair() {
  local status=$?
  if (( status != 0 )) && [[ ! -f "$OUT/PAIRED_COMPLETE" ]] && [[ ! -f "$OUT/ABORTED.txt" ]]; then
    printf 'ABORTED — paired runner exited with status %d. Partial runs are unusable.\n' "$status" >"$OUT/ABORTED.txt" || true
  fi
  return "$status"
}
trap mark_incomplete_pair EXIT

echo "Preparing reference compiler preflight: $REFERENCE_BIN"
ELISA_STAGE1_BIN="$REFERENCE_BIN" ELISA_BENCH_PREFLIGHT_ONLY=1 \
  "$RUNNER" "$OUT/reference-preflight"

REFERENCE_FINGERPRINT="$OUT/reference-preflight/canonical_workload_fingerprint.json"
echo "Preparing candidate compiler preflight: $CANDIDATE_BIN"
ELISA_STAGE1_BIN="$CANDIDATE_BIN" \
ELISA_BENCH_PREFLIGHT_ONLY=1 \
ELISA_BENCH_EXPECT_CANONICAL_FINGERPRINT="$REFERENCE_FINGERPRINT" \
  "$RUNNER" "$OUT/candidate-preflight"

# Recheck the preflight identity before allowing any timed pair to start.
python3 - "$OUT" "$REFERENCE_BIN" "$CANDIDATE_BIN" "$SCRIPT_DIR/paired_cross_language.sh" "$SCRIPT_DIR/paired_report.py" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
reference_bin = Path(sys.argv[2]).resolve()
candidate_bin = Path(sys.argv[3]).resolve()
paired_runner = Path(sys.argv[4]).resolve()
paired_reporter = Path(sys.argv[5]).resolve()

def read_preflight(name, compiler):
    directory = out / name
    if not (directory / "PREFLIGHT_COMPLETE").is_file() or (directory / "ABORTED.txt").exists():
        raise SystemExit(f"{name} did not complete its exact correctness preflight")
    metadata = {}
    for line in (directory / "metadata.txt").read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            metadata[key] = value
    expected_hash = hashlib.sha256(compiler.read_bytes()).hexdigest()
    if metadata.get("elisa_product_sha256") != expected_hash:
        raise SystemExit(f"{name} metadata does not identify the requested compiler binary")
    record = json.loads((directory / "canonical_workload_fingerprint.json").read_text())
    return record

reference = read_preflight("reference-preflight", reference_bin)
candidate = read_preflight("candidate-preflight", candidate_bin)
if reference.get("fingerprint_sha256") != candidate.get("fingerprint_sha256"):
    raise SystemExit("reference and candidate canonical workload fingerprints differ; no timed pairs were started")
if reference.get("payload") != candidate.get("payload"):
    raise SystemExit("reference and candidate workload payloads differ; no timed pairs were started")
if hashlib.sha256(reference_bin.read_bytes()).digest() == hashlib.sha256(candidate_bin.read_bytes()).digest():
    raise SystemExit("reference and candidate compiler binaries are identical; choose distinct builds")

record = {
    "schema": "paired-cross-language-v1",
    "reference_binary": str(reference_bin),
    "reference_binary_sha256": hashlib.sha256(reference_bin.read_bytes()).hexdigest(),
    "candidate_binary": str(candidate_bin),
    "candidate_binary_sha256": hashlib.sha256(candidate_bin.read_bytes()).hexdigest(),
    "paired_runner": str(paired_runner),
    "paired_runner_sha256": hashlib.sha256(paired_runner.read_bytes()).hexdigest(),
    "paired_reporter": str(paired_reporter),
    "paired_reporter_sha256": hashlib.sha256(paired_reporter.read_bytes()).hexdigest(),
    "canonical_workload_fingerprint_sha256": reference["fingerprint_sha256"],
    "canonical_workload_payload": reference["payload"],
    "paired_order": "A-B-B-A",
}
(out / "paired_metadata.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
print(f"Exact parity confirmed: {reference['fingerprint_sha256']}")
PY

run_one() {
  local compiler="$1"
  local output="$2"
  ELISA_STAGE1_BIN="$compiler" \
  ELISA_BENCH_EXPECT_CANONICAL_FINGERPRINT="$REFERENCE_FINGERPRINT" \
    "$RUNNER" "$output"
}

for ((block = 1; block <= PAIRED_BLOCKS; block++)); do
  printf -v block_name '%02d' "$block"
  echo "Paired block $block_name (A-B-B-A)"
  run_one "$REFERENCE_BIN" "$OUT/block-$block_name-A1-reference"
  run_one "$CANDIDATE_BIN" "$OUT/block-$block_name-B1-candidate"
  run_one "$CANDIDATE_BIN" "$OUT/block-$block_name-B2-candidate"
  run_one "$REFERENCE_BIN" "$OUT/block-$block_name-A2-reference"
done

python3 "$SCRIPT_DIR/paired_report.py" "$OUT"
date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ' >"$OUT/PAIRED_COMPLETE"
echo "Paired comparison complete: $OUT/paired_ab_summary.csv"
