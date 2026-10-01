#!/usr/bin/env bash
# Adversarial differential sweep (2026-10): one-feature escape/UAF probes stage0 rejects
# and stage1 used to accept, each with a run-proven wrong answer or dangling store:
#   ufcs_grow / receiver_grow    a ref read after `xs.grow()` / `b.add(i)` grows the
#                                receiver through `mutable T&` (stale 41)
#   closure_*_return             a returned closure capturing a local container, a view of
#                                it, or a `&` borrow of it (returned 0, not 65)
#   enum_payload / tuple store   `out.push(Tok.Word(local_view))` / `out.push((1, v))`
#   region_enum_escape           `t <- Tok.Word(buf.as_sview())` out of a region block
#   enum_payload_view_grow       a view in an enum payload read after its source grows
#   *ref_alias_interior_grow     `r = &b.items; x = &r[0]; b.items.push` (stale 41)
#   enum_return_view*            a local view returned inside an enum payload (read 0)
# Each .neg must be REJECTED by the semantic layer (not a backend decline); each .pos twin
# (same shape, no escape) must still compile to a non-empty object.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISAC_STAGE1:-$ROOT/bin/elisac-stage1}"
DIR="$ROOT/test/fixtures/semantic/adversarial_escape"
TMP="$(mktemp -d "$HOME/.adversarial_escape.XXXXXX")"
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
            elif grep -v 'warning:' "$TMP/log" | grep -q 'declined'; then
                echo "FAIL $name: rejected only by a backend decline"; fail=1
            elif ! grep -v 'warning:' "$TMP/log" | grep -q "$name.elisa:[0-9]"; then
                echo "FAIL $name: no positioned diagnostic"; grep -v 'warning:' "$TMP/log" | head -2; fail=1; fi ;;
        *.pos)
            if [ $accepted -ne 1 ]; then echo "FAIL $name: rejected (rc=$rc)"; grep -v 'warning:' "$TMP/log" | head -3; fail=1; fi ;;
    esac
done
[ $fail -eq 0 ] && echo "adversarial-escape OK ($n cases)" || exit 1
