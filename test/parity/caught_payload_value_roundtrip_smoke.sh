#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-payload-roundtrip.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
for level in 0 2; do
    bash "$ROOT/scripts/elisac_stage1.sh" -O"$level" -emit exe -o "$WORK/control-$level" "$ROOT/test/repro/caught_payload_value_roundtrip.elisa"
    "$WORK/control-$level"
done
echo "caught payload value roundtrip smoke OK"
