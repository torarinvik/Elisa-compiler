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
# Round 2 (views stored into containers, closures, nested rows, dstr):
#   container_*_view_grow        a view pushed/extended/`keep(&vs, s)` into a container,
#                                then its source grows (stage0 segfaulted; fixed 0296d61e)
#   container_push_closure_*     a closure capturing a view pushed into a container
#   struct_lambda_return_view    `return H{f: fn() => s[0]}` with s a local view
#   *lambda_region_store         a closure capturing a region view stored out of the region
#   nested_row_replace_view      `grid[0] <- [7]` while a view of grid[0] is live
#   dstr_reassign_view           a dstr reassigned while a view of it is live
# Round 3 (holders and rebinds; stage0 473e9c2c):
#   field/index_store_view_grow  `h.s <- view` / `vs[0] <- view`, then the source grows
#   holder_*copy_view_grow       a copy of a holder (`ws = vs`, `ws <- vs`, `g = h`) keeps
#                                the views stored in it
#   larrow_call/cast_view_grow   `s <- buf.as_sview()` / `c <- (&buf[0]).cast[cstr]`
#   larrow_cast_branch_rebind    `name <- f(storage)` rebinds a value-typed local: not a use
# Round 4 (field-path keys; a view of `p.storage` from `bytes_view_range`):
#   field_sibling_*_grow.pos     growing/replacing a sibling `p.lines` whose darray element
#                                type differs from the viewed field's keeps the view
#   field_sibling_same_elem_*    same-typed siblings may share one buffer after a shallow
#                                copy (`P{storage: b, lines: b}`, run-proven stale read), so
#                                growing either still invalidates
#   field_viewed_* / root_replace growing or replacing `p.storage`, or replacing `p`
# Round 5 (call-derived views; callee return-origin summaries, view returns only):
#   call_*_return                a local view returned through an identity/generic/protocol
#                                callee (`return id(local_view)`)
#   call_*_view_grow             a view obtained through a method/generic/protocol/field call,
#                                read after its source grows; spawn args likewise
#   comprehension/match_value    views carried through a comprehension body or match arm value
#   darray_elem_*_alias          `P{lines: shared}` / `lines: darray[i8] = shared` with a
#                                differently-typed scalar darray: two element types, one buffer
#   call_field_view_sibling_grow.pos  a call-derived view of h.buf survives h.marks.push
#   darray_elem_call_*           a `darray[u8]` local passed to a `darray[i8]` / `darray[i8]&` /
#                                `mutable darray[u64]&` parameter (generic and same-type twins pass)
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
