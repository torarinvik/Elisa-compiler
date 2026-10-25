#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/emit_parity_lib.sh"

fail() {
    echo "Catch match module identity smoke FAIL: $1" >&2
    exit 1
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
FIXTURE="$REPO_ROOT/test/repro/catch_match_module_identity.elisa"

s0 -emit progress "$FIXTURE" > "$WORK/stage0.progress" 2> "$WORK/stage0.stderr" || fail "Stage0 could not produce the progress report: $(cat "$WORK/stage0.stderr")"
s1 -emit progress -o "$WORK/stage1.progress" "$FIXTURE" > "$WORK/stage1.stdout" 2> "$WORK/stage1.stderr" || fail "Stage1 could not produce the progress report: $(cat "$WORK/stage1.stderr")"

for report in "$WORK/stage0.progress" "$WORK/stage1.progress"; do
    grep -q '^  catch_loop: obligations=Loop:1 evidence=progress ' "$report" || fail "catch_loop lost progress evidence in $report: $(cat "$report")"
    grep -q '^  match_loop: obligations=Loop:1 evidence=progress ' "$report" || fail "match_loop lost ordinary match progress evidence in $report: $(cat "$report")"
done

echo "Catch match module identity smoke OK" >&2
