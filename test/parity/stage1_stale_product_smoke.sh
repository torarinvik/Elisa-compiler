#!/usr/bin/env bash
# A stage1 product predating its compiler sources must be refused before compilation.
# This prevents incompatible cached products from turning parser/lowering drift into an
# unbounded-memory failure with only "Killed: 9" as a symptom.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-stale-stage1.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

[[ -x "$ROOT/bin/elisac-stage1" ]] || {
  echo "stage1 stale-product smoke requires $ROOT/bin/elisac-stage1 (run scripts/elisac_stage1.sh --seed)" >&2
  exit 2
}

install -m 755 "$ROOT/bin/elisac-stage1" "$WORK/elisac-stage1"
touch -t 202001010000 "$WORK/elisac-stage1"

set +e
ELISA_STAGE1_BIN="$WORK/elisac-stage1" \
  "$ROOT/scripts/elisac_stage1.sh" -emit tokens -o "$WORK/tokens" \
  "$ROOT/test/fixtures/machine_from/typed_state_arrows.elisa" \
  >"$WORK/stdout" 2>"$WORK/stderr"
status=$?
set -e

[[ "$status" -eq 2 ]] || {
  echo "stage1 stale-product smoke FAIL: exit $status, expected 2" >&2
  cat "$WORK/stderr" >&2
  exit 1
}
grep -q 'stage1 product binary is stale:' "$WORK/stderr" || {
  echo "stage1 stale-product smoke FAIL: missing stale-product diagnostic" >&2
  cat "$WORK/stderr" >&2
  exit 1
}
grep -q 'run: .*elisac_stage1.sh --seed' "$WORK/stderr" || {
  echo "stage1 stale-product smoke FAIL: missing reseed instruction" >&2
  cat "$WORK/stderr" >&2
  exit 1
}

echo "stage1 stale-product smoke OK: incompatible cached products fail fast with reseed guidance"
