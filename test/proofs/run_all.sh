#!/usr/bin/env bash
set -euo pipefail

PROOF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKER_COUNT=0

for checker in "$PROOF_DIR"/check_*.py; do
    [[ -f "$checker" ]] || continue
    CHECKER_COUNT=$((CHECKER_COUNT + 1))
    printf '==> %s\n' "$(basename "$checker")"
    python3 "$checker"
done

if [[ "$CHECKER_COUNT" -eq 0 ]]; then
    printf 'no proof admission checkers found in %s\n' "$PROOF_DIR" >&2
    exit 2
fi

printf 'all %s proof admission checkers passed\n' "$CHECKER_COUNT"
