#!/usr/bin/env bash
# docs/122 §5.7 named variant patterns, `Enum.Variant(field: p, _)`, against stage0.
# Runnable fixtures must exit with the same code under both compilers; each .neg fixture
# must be rejected by both, with stage0's message text in stage1's output.
#   STAGE1=<elisac-stage1> RUNTIME_OBJ=<elisacore_runtime.o> bash test/parity/named_variant_pattern_smoke.sh
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${STAGE1:-$REPO_ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${RUNTIME_OBJ:-$REPO_ROOT/build/runtime/elisacore_runtime.o}"
DIR="$REPO_ROOT/test/fixtures/named_variant_patterns"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
failures=0
fail() { echo "named-variant-pattern smoke FAIL: $1" >&2; failures=$((failures + 1)); }

for src in "$DIR"/*.elisa; do
	name="$(basename "$src" .elisa)"
	if [[ "$name" == *.neg ]]; then
		s0_out="$("$ELISACORE_BIN" "$src" -emit obj -o "$WORK/s0.o" 2>&1)" && fail "$name: stage0 accepted"
		s1_out="$(ELISA_ALLOW_STALE_STAGE1=1 "$STAGE1" "$src" -o "$WORK/s1.o" 2>&1)" && fail "$name: stage1 accepted"
		message="$(grep -m1 -o 'match arm .*' <<< "$s0_out")"
		# stage1 has no file positions to name the first duplicate with.
		message="${message%% (first at*}"
		grep -qF "$message" <<< "$s1_out" || fail "$name: stage1 lacks \"$message\": $s1_out"
		continue
	fi
	"$ELISACORE_BIN" "$src" -emit obj -o "$WORK/s0.o" && clang -o "$WORK/s0" "$WORK/s0.o" || { fail "$name: stage0 build"; continue; }
	ELISA_ALLOW_STALE_STAGE1=1 "$STAGE1" "$src" -o "$WORK/s1.o" && clang -o "$WORK/s1" "$WORK/s1.o" "$RUNTIME_OBJ" || { fail "$name: stage1 build"; continue; }
	"$WORK/s0"; s0_rc=$?
	"$WORK/s1"; s1_rc=$?
	[[ "$s0_rc" == "$s1_rc" ]] || fail "$name: stage0 exit $s0_rc, stage1 exit $s1_rc"
done
[[ "$failures" == 0 ]] || exit 1
echo "named-variant-pattern smoke: OK"
