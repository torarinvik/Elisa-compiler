#!/usr/bin/env bash
# A stage1 product predating its compiler sources must be refused before compilation.
# This prevents incompatible cached products from turning parser/lowering drift into an
# unbounded-memory failure with only "Killed: 9" as a symptom.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "$ROOT/bin/.elisa-stale-stage1.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

[[ -x "$ROOT/bin/elisac-stage1" ]] || {
  echo "stage1 stale-product smoke requires $ROOT/bin/elisac-stage1 (run scripts/elisac_stage1.sh --seed)" >&2
  exit 2
}
[[ -s "$ROOT/bin/elisac-stage1.provenance.json" ]] || {
  echo "stage1 stale-product smoke requires the Stage1 provenance record (run scripts/elisac_stage1.sh --seed)" >&2
  exit 2
}

install -m 755 "$ROOT/bin/elisac-stage1" "$WORK/elisac-stage1"
cp "$ROOT/bin/elisac-stage1.provenance.json" "$WORK/elisac-stage1.provenance.json"
python3 - "$WORK/elisac-stage1.provenance.json" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text())
# Model a product built against a different source snapshot. The deliberately mismatched
# stat-cache key forces the routine path to recompute the real content digest.
manifest["source_tree_sha256"] = "0" * 64
manifest["source_tree_stat_fingerprint"] = "0" * 64
manifest_path.write_text(json.dumps(manifest))
PY

# This check EXISTS to prove the guard refuses. An environment that has already opted out
# (`ELISA_ALLOW_STALE_STAGE1=1`) would turn the refusal into a success and the check would
# pass vacuously, which is how it once read as a FAIL on both hosts. The verification env no
# longer exports it — every check runs against the NEWEST product — but an interactive shell
# may still carry it, so clear it for this invocation.
unset ELISA_ALLOW_STALE_STAGE1
set +e
ELISA_STAGE1_BIN="$WORK/elisac-stage1" ELISA_ALLOW_STALE_STAGE1=0 \
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
grep -q 'stage1 product is stale: provenance mismatch in source_tree_sha256' "$WORK/stderr" || {
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
