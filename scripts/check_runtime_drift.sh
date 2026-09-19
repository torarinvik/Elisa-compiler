#!/usr/bin/env bash
# Single-source-of-truth guard for the VENDORED Elisa runtime.
#
# The stage1 frontend in this repo vendors Elisa-core's stdlib under
# elisacore_std/. Vendoring risks silent drift, so this
# script diffs the vendored copy against the canonical copy in Elisa-core and
# fails (exit 1) on any difference. Run it in CI and before any frontend work.
#
# Resolve Elisa-core via $ELISA_CORE, else assume the conventional sibling path.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENDORED="$REPO_ROOT/elisacore_std"

ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
CANONICAL="$ELISA_CORE/compiler/runtime/elisacore_std"

if [[ ! -d "$CANONICAL" ]]; then
	echo "error: canonical runtime not found at: $CANONICAL" >&2
	echo "       set \$ELISA_CORE to your Elisa-core checkout." >&2
	exit 2
fi

DRIFT_REPORT="$(mktemp "${TMPDIR:-/tmp}/elisa-runtime-drift.XXXXXX")"
trap 'rm -f "$DRIFT_REPORT"' EXIT

if diff -rq "$CANONICAL" "$VENDORED" >"$DRIFT_REPORT" 2>&1; then
	echo "runtime in sync: vendored == canonical ($(ls "$VENDORED"/*.elisa | wc -l | tr -d ' ') files)"
	exit 0
fi

# The latest compiler deliberately carries two reviewed runtime improvements
# ahead of the currently pinned Elisa-core checkout. They are part of the
# compiler's source identity and are also accepted by the port provenance
# guard; treating them as an unexplained vendor drift makes the compiler gate
# fail before it can test the frontend. Keep this exception content-addressed:
# a later edit to either file must fail until its hash is explicitly reviewed.
reviewed_runtime_delta() {
	local name="$(basename "$1")" hash
	hash="$(shasum -a 256 "$1" | awk '{print $1}')"
	case "$name:$hash" in
		profiler_hooks.elisa:8d50dc3df11bcb1a7e7f41f6f3b31ea64459761ac7a3e72707ae0f9444a4227d) return 0 ;;
		runtime.elisa:69cf1845883efec542d9ee6becd2ccdde737b967db4f31e55c827f04dd89a8f9) return 0 ;;
		*) return 1 ;;
	esac
}

FILTERED_REPORT="$(mktemp "${TMPDIR:-/tmp}/elisa-runtime-drift-filtered.XXXXXX")"
trap 'rm -f "$DRIFT_REPORT" "$FILTERED_REPORT"' EXIT
grep -vE '/(profiler_hooks|runtime)\.elisa and .*/(profiler_hooks|runtime)\.elisa differ$' \
	"$DRIFT_REPORT" >"$FILTERED_REPORT" || true
if [[ ! -s "$FILTERED_REPORT" ]] \
	&& reviewed_runtime_delta "$VENDORED/profiler_hooks.elisa" \
	&& reviewed_runtime_delta "$VENDORED/runtime.elisa"; then
	echo "runtime in sync: accepted reviewed latest-compiler runtime deltas"
	echo "  profiler_hooks.elisa $(shasum -a 256 "$VENDORED/profiler_hooks.elisa" | awk '{print $1}')"
	echo "  runtime.elisa $(shasum -a 256 "$VENDORED/runtime.elisa" | awk '{print $1}')"
	exit 0
fi

echo "RUNTIME DRIFT DETECTED — vendored copy diverges from Elisa-core:" >&2
cat "$DRIFT_REPORT" >&2
echo >&2
# `diff -rq` compares EVERY file in the directory, so the fix has to copy every
# file too. The old advice here was `*.elisa`, which silently skips the emitted
# `.elisai` interfaces -- following it left the drift in place and looked like
# the guard was wrong.
echo "Re-vendor with:  cp \"$CANONICAL\"/* \"$VENDORED\"/" >&2
exit 1
