#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT INT TERM HUP
"$ROOT/scripts/elisac_stage1.sh" -emit exe -o "$WORK/frame" "$ROOT/test/repro/native_frame_contract.elisa"
"$WORK/frame"
"$ROOT/scripts/elisac_stage1.sh" -emit c-archive -o "$WORK/frame.a" "$ROOT/test/repro/native_frame_contract.elisa"
test -s "$WORK/frame.a"
"$ROOT/scripts/elisac_stage1.sh" -permissive -emit exe -o "$WORK/false-frame" "$ROOT/test/repro/native_frame_contract_false.elisa"
python3 - "$WORK/false-frame" <<'PY'
import signal
import subprocess
import sys
result = subprocess.run([sys.argv[1]], capture_output=True, timeout=30)
assert result.returncode == -signal.SIGABRT, (result.returncode, result.stdout, result.stderr)
PY
printf '%s\n' 'native frame declarations: changes/preserves executable behavior and archive emission passed'
