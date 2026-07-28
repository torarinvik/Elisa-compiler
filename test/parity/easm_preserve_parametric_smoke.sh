#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
good=$(python3 "$ROOT/scripts/easm_preserve_parametric.py" "$ROOT/test/fixtures/easm/preserve_good.easm")
python3 -c 'import json,sys; a=json.loads(sys.argv[1]); assert a["results"][0]["status"] == "proved"' "$good"
set +e
bad=$(python3 "$ROOT/scripts/easm_preserve_parametric.py" "$ROOT/test/fixtures/easm/preserve_bad.easm")
status=$?
set -e
python3 -c 'import json,sys; a=json.loads(sys.argv[1]); assert a["results"][0]["status"] == "diverged"' "$bad"
[ "$status" -eq 1 ]
echo "easm_preserve_parametric_smoke OK"
