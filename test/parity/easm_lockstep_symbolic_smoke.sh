#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
Z3="${Z3:-$(command -v z3 || true)}"
if [ -z "$Z3" ]; then
    echo "easm_lockstep_symbolic_smoke SKIP: z3 not found"
    exit 0
fi
equiv=$(python3 "$ROOT/scripts/easm_lockstep_symbolic.py" "$ROOT/test/fixtures/easm/lockstep_equiv.easm" --z3 "$Z3")
python3 -c 'import json,sys; assert json.loads(sys.argv[1])["results"][0]["status"] == "proved"' "$equiv" || { echo "easm_lockstep_symbolic_smoke FAILED: equivalent lockstep was not proved"; echo "$equiv"; exit 1; }
if python3 "$ROOT/scripts/easm_lockstep_symbolic.py" "$ROOT/test/fixtures/easm/lockstep_diverged.easm" --z3 "$Z3" >/tmp/easm_lockstep_diverged.json; then
    echo "easm_lockstep_symbolic_smoke FAILED: divergent lockstep was accepted"
    exit 1
fi
python3 -c 'import json; assert json.load(open("/tmp/easm_lockstep_diverged.json"))["results"][0]["status"] == "diverged"'
extended=$(python3 "$ROOT/scripts/easm_lockstep_symbolic.py" "$ROOT/test/fixtures/easm/lockstep_symbolic_extended.easm" --z3 "$Z3")
python3 -c 'import json,sys; assert json.loads(sys.argv[1])["results"][0]["status"] == "proved"' "$extended" || { echo "easm_lockstep_symbolic_smoke FAILED: extended ALU body was not proved"; echo "$extended"; exit 1; }
flags=$(python3 "$ROOT/scripts/easm_lockstep_symbolic.py" "$ROOT/test/fixtures/easm/lockstep_branch_flags.easm" --z3 "$Z3")
python3 -c 'import json,sys; assert json.loads(sys.argv[1])["results"][0]["status"] == "proved"' "$flags" || { echo "easm_lockstep_symbolic_smoke FAILED: flag-branch lockstep was not proved"; echo "$flags"; exit 1; }
ambient=$(python3 "$ROOT/scripts/easm_lockstep_symbolic.py" "$ROOT/test/fixtures/easm/lockstep_ambient.easm" --z3 "$Z3")
python3 -c 'import json,sys; assert json.loads(sys.argv[1])["results"][0]["status"] == "proved"' "$ambient" || { echo "easm_lockstep_symbolic_smoke FAILED: ambient-state lockstep was not proved"; echo "$ambient"; exit 1; }
loop=$(python3 "$ROOT/scripts/easm_lockstep_symbolic.py" "$ROOT/test/fixtures/easm/lockstep_loop_equiv.easm" --z3 "$Z3")
python3 -c 'import json,sys; assert json.loads(sys.argv[1])["results"][0]["status"] == "proved"' "$loop" || { echo "easm_lockstep_symbolic_smoke FAILED: counted-loop lockstep was not proved"; echo "$loop"; exit 1; }
echo "easm_lockstep_symbolic_smoke OK"
