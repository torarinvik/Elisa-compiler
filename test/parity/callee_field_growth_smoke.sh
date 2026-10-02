#!/usr/bin/env bash
# Per-callee field-growth summaries (src/semantic/param_growth_summary.elisa): a call that
# passes a whole struct through `mutable T&` invalidates only views of the fields the callee
# (transitively) grows, pushes, clears or replaces. .pos: a view of `p.source` survives a
# callee that grows only `p.names` (directly or through a recursive helper). .neg: the
# callee grows / clears `p.source`, directly or through a helper.
# retired_generation.neg: each darray buffer generation is its own lifetime (retired buffers
# are never exempt), so a view from one generator call dies at the next. stage0 accepts it.
# stage0 also accepts the two field .neg cases: it does not invalidate through a whole-struct
# `mutable T&` argument at all (arena-backed, so not run-observable; stage1 is stricter).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISAC_STAGE1:-$ROOT/bin/elisac-stage1}"
DIR="$ROOT/test/fixtures/semantic/callee_field_growth"
TMP="$(mktemp -d "$HOME/.callee_field_growth.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
fail=0; n=0
for f in "$DIR"/*.elisa; do
    name="$(basename "$f" .elisa)"; n=$((n + 1))
    rm -f "$TMP/o.o"
    "$BIN" -emit obj "$f" -o "$TMP/o.o" >"$TMP/log" 2>&1
    rc=$?
    accepted=0; [ $rc -eq 0 ] && [ -s "$TMP/o.o" ] && accepted=1
    case "$name" in
        *.neg)
            if [ $accepted -eq 1 ]; then echo "FAIL $name: accepted"; fail=1
            elif ! grep -v 'warning:' "$TMP/log" | grep -q "$name.elisa:[0-9]*:[0-9-]*: view \"v\" cannot be used"; then
                echo "FAIL $name: not rejected for the view"; grep -v 'warning:' "$TMP/log" | head -2; fail=1; fi ;;
        *.pos)
            if [ $accepted -ne 1 ]; then echo "FAIL $name: rejected (rc=$rc)"; grep -v 'warning:' "$TMP/log" | head -3; fail=1; fi ;;
    esac
done
[ $fail -eq 0 ] && echo "callee-field-growth OK ($n cases)" || exit 1
