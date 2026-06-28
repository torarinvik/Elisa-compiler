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

if diff -rq "$CANONICAL" "$VENDORED" >/tmp/runtime_drift.txt 2>&1; then
	echo "runtime in sync: vendored == canonical ($(ls "$VENDORED"/*.elisa | wc -l | tr -d ' ') files)"
	exit 0
fi

echo "RUNTIME DRIFT DETECTED — vendored copy diverges from Elisa-core:" >&2
cat /tmp/runtime_drift.txt >&2
echo >&2
echo "Re-vendor with:  cp \"$CANONICAL\"/*.elisa \"$VENDORED\"/" >&2
exit 1
