#!/usr/bin/env bash
# Runtime and postcondition quantifiers must use the same short-circuit range semantics.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT INT TERM HUP
"$ROOT/scripts/elisac_stage1.sh" -emit exe -o "$WORK/quantified-range" "$ROOT/test/repro/quantified_range_contract.elisa"
"$WORK/quantified-range"
"$ROOT/scripts/elisac_stage1.sh" -emit c-archive -o "$WORK/quantified-range.a" "$ROOT/test/repro/quantified_range_contract.elisa"
test -s "$WORK/quantified-range.a"
"$ROOT/scripts/elisac_stage1.sh" -permissive -emit exe -o "$WORK/false-contract" "$ROOT/test/repro/quantified_range_contract_false.elisa"
python3 - "$WORK/false-contract" <<'PY'
import signal
import subprocess
import sys
result = subprocess.run([sys.argv[1]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
assert result.returncode == -signal.SIGABRT, (result.returncode, result.stdout, result.stderr)
PY
printf '%s\n' 'quantified range contract: runtime true/false, empty identities, inclusive bounds, array predicate and archive emission passed'
