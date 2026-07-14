#!/usr/bin/env bash
# docs/125 step 15 — GRADUATION of the strict-flow discipline.
#
# The strict block-`if` ban (-Wflow-strict, docs/125 §6b: "every decision must be a value, an
# exit, an arm, or a transition") is now a GATE-ENFORCED standard for the compiler's own source
# (src/ + elisacore_std/, via the parse_report breadth driver). The whole codebase was remodelled
# to ZERO strict block-`if` sites (census 465 -> 0) using postfix guards, value selection, match,
# machine, and the generalized panic/as-ref/can-annotated guards. This smoke fails if any block-`if`
# regresses, so "control flow is modelling" can no longer rot silently.
#
# NOTE: this is NOT a global compiler default — other Elisa projects keep FlowLintOff and are
# unaffected. It enforces -Wflow-strict for the compiler project only.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
# shellcheck source=/dev/null
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

target="$REPO_ROOT/test/breadth/parse_report.elisa"
out=$("$ELISACORE_BIN" -emit obj -Wflow-strict -o /dev/null "$target" 2>&1)

# Guard against a false PASS on a broken build: a parse/type error aborts before the flow lint
# runs, silently yielding 0 findings (the -permissive census trap). Any non-flow build error here
# means the census is inconclusive.
othererr=$(printf '%s\n' "$out" | grep -E 'error:|expected |unexpected ' | grep -v 'block `if`' | grep -v 'avoidable padding' | grep -c .)
if [[ "$othererr" -ne 0 ]]; then
	echo "flow-strict census INCONCLUSIVE: parse_report did not build cleanly (a broken build would false-pass):"
	printf '%s\n' "$out" | grep -E 'error:|expected |unexpected ' | grep -v 'block `if`' | grep -v 'avoidable padding' | head -5 | sed 's/^/  /'
	exit 1
fi

blockifs=$(printf '%s\n' "$out" | grep -c 'block `if`')
if [[ "$blockifs" -eq 0 ]]; then
	echo "flow-strict census OK: 0 block-\`if\` sites across compiler src + std (docs/125 step 15 graduation)"
	exit 0
fi
echo "flow-strict census FAILED: $blockifs block-\`if\` site(s) reintroduced — remodel per docs/125 §6b:"
printf '%s\n' "$out" | grep 'block `if`' | grep -oE '(src|std|test)/[^ ]+\.elisa:[0-9]+' | sort -u | sed 's/^/  - /'
exit 1
