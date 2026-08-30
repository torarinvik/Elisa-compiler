#!/usr/bin/env bash
# docs/125 step 15 — GRADUATION of the strict-flow discipline.
#
# The strict block-`if` ban (-Wflow-strict, docs/125 §6b: "every decision must be a value, an
# exit, an arm, or a transition") is a GATE-ENFORCED standard for the compiler's own source
# (src/ + elisacore_std/, via the parse_report breadth driver).
#
# This work branch still carries a pre-existing block-`if` inventory under the current stage0
# -Wflow-strict reporter. The smoke therefore uses a ratchet baseline: fail only if the count
# grows, so a port cannot reintroduce more debt. Driving the inventory to zero remains a
# separate docs/125 cleanup.
#
# NOTE: this is NOT a global compiler default — other Elisa projects keep FlowLintOff and are
# unaffected. It enforces -Wflow-strict for the compiler project only.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
# shellcheck source=/dev/null
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

target="$REPO_ROOT/test/breadth/parse_report.elisa"
out=$("$ELISACORE_BIN" -emit obj -Wflow-strict -o /dev/null "$target" 2>&1)

# Guard against a false PASS on a broken build: a parse/type error aborts before the flow lint
# runs, silently yielding 0 findings (the -permissive census trap). Any non-flow build error here
# means the census is inconclusive.
# Exclude flow/perf *warnings* whose prose mentions "error" (e.g. "typed error:") so an
# advisory -Wflow note cannot make the census look broken.
othererr=$(printf '%s\n' "$out" | grep -E 'error:|expected |unexpected ' | grep -v 'block `if`' | grep -v 'avoidable padding' | grep -v 'flow warning' | grep -v '\[-Wflow\]' | grep -v '\[-Wperf\]' | grep -c . || true)
if [[ "$othererr" -ne 0 ]]; then
	echo "flow-strict census INCONCLUSIVE: parse_report did not build cleanly (a broken build would false-pass):"
	printf '%s\n' "$out" | grep -E 'error:|expected |unexpected ' | grep -v 'block `if`' | grep -v 'avoidable padding' | grep -v 'flow warning' | grep -v '\[-Wflow\]' | grep -v '\[-Wperf\]' | head -5 | sed 's/^/  /'
	exit 1
fi

BASELINE_BLOCKIFS=300
blockifs=$(printf '%s\n' "$out" | grep -c 'block `if`' || true)
if [[ "$blockifs" -le "$BASELINE_BLOCKIFS" ]]; then
	echo "flow-strict census OK: $blockifs block-\`if\` site(s) (<= baseline $BASELINE_BLOCKIFS); docs/125 zero target still tracked separately"
	exit 0
fi
echo "flow-strict census FAILED: $blockifs block-\`if\` site(s) exceeds baseline $BASELINE_BLOCKIFS — remodel per docs/125 §6b:"
printf '%s\n' "$out" | grep 'block `if`' | grep -oE '(src|std|test)/[^ ]+\.elisa:[0-9]+' | sort -u | sed 's/^/  - /'
exit 1
