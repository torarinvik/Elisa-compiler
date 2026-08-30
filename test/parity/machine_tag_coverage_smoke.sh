#!/usr/bin/env bash
# docs/125 §9 Tier-2 machine tag-coverage — stage1 FEATURE parity with stage0. A `machine over`
# whose input is a free-function classifier returning a CLOSED const enum (classified dispatch)
# must, per state, spell every variant as an explicit tag (missing = error) and REJECT a `_`
# wildcard (on a closed domain a wildcard erases the add-a-variant safety net). stage1-OWNED via
# a parser side-record (File.machine_coverage, one flat row per arm-atom) resolved in semantic
# (check_machine_tag_coverage) once the classifier's return type is known. Mirrors stage0's
# checkMachineCoverage.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
# shellcheck source=/dev/null
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
# shellcheck source=/dev/null
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "machine tag-coverage smoke FAIL: $1" >&2; exit 1; }

base='const enum NC:\n    Digit\n    Other\n\nstruct Lx:\n    bytes: darray[char]\n    pos: usize\n\ndef current_char(lx: Lx&) -> char:\n    can Abort.Panic:\n        return lx.bytes[lx.pos]\n\ndef is_end_of_source(lx: Lx&) -> bool:\n    return lx.pos >= lx.bytes.count\n\ndef classify(c: char) -> NC:\n    return NC.Digit if c >= 48.char() and c <= 57.char() else NC.Other\n\ndef scan(lx: mutable Lx&) -> i64:\n    can Abort.Panic:\n        result: i64 =\n            machine over classify(lx.current_char()) while not lx.is_end_of_source() -> out:\n                state Run(out: i64)\n                start Run(0)\n'

# 1. WILDCARD on a closed const enum is rejected.
out=$(printf "$base                Run(out), NC.Digit:\n                    break\n                Run(out), _:\n                    break\n        return result\n" | "$RPT")
echo "$out" | grep -qi "wildcard" || fail "closed-enum \"_\" wildcard not rejected: $out"

# 2. A MISSING variant is flagged.
out=$(printf "$base                Run(out), NC.Digit:\n                    break\n        return result\n" | "$RPT")
echo "$out" | grep -qi "missing variant \"Other\"" || fail "missing variant not flagged: $out"

# 3. A tag-complete state (no wildcard, every variant spelled) is CLEAN of Tier-2 diagnostics.
out=$(printf "$base                Run(out), NC.Digit:\n                    break\n                Run(out), NC.Other:\n                    break\n        return result\n" | "$RPT")
echo "$out" | grep -qi "closed enum" && fail "tag-complete machine wrongly flagged Tier-2: $out"

echo "machine tag-coverage smoke OK: wildcard rejected, missing variant flagged, complete passes (docs/125 §9)"
