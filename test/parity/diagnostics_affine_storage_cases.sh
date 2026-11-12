echo "-- joined_view_lifetime --"
require_diagnostic_count joined_view_lifetime "$FIXTURES/submit_local_mutable_ref.pos.elisa" 'argument to "pool_submit1" is not structurally shareable across threads: non-static reference' 2

echo "-- affine_move_sites --"
run_case affine_move_nested_call pos "$FIXTURES/affine_move_nested_call.pos.elisa" 'linear value "t" must be moved explicitly before argument to call "sink"'
run_case affine_move_struct_field pos "$FIXTURES/affine_move_struct_field.pos.elisa" 'linear value "t" must be moved explicitly before move into struct literal field "a"'
run_case affine_move_tuple_element pos "$FIXTURES/affine_move_tuple_element.pos.elisa" 'linear value "t" must be moved explicitly before move into tuple element "_0"'
run_case affine_move_array_element pos "$FIXTURES/affine_move_array_element.pos.elisa" 'linear value "t" must be moved explicitly before move into array literal element'
run_case affine_move_darray_literal pos "$FIXTURES/affine_move_darray_literal.pos.elisa" 'linear value "t" must be moved explicitly before move into darray literal element'
run_case affine_move_darray_push pos "$FIXTURES/affine_move_darray_push.pos.elisa" 'linear value "t" must be moved explicitly before move into darray push'
run_case affine_move_sites neg "$FIXTURES/affine_move_sites.neg.elisa" "must be moved explicitly"
run_case affine_move_enum_payload pos "$FIXTURES/affine_move_enum_payload.pos.elisa" 'linear value "t" must be moved explicitly before move into enum payload "Box.Full" argument 1'
run_case affine_move_enum_payload_label pos "$FIXTURES/affine_move_enum_payload_label.pos.elisa" 'linear value "u" must be moved explicitly before move into enum payload "Box.Tagged.h"'
run_case affine_move_discard pos "$FIXTURES/affine_move_discard.pos.elisa" 'linear value "t" must be moved explicitly before discard'
run_case affine_move_enum_payload neg "$FIXTURES/affine_move_enum_payload.neg.elisa" "must be moved explicitly"
run_case affine_move_dict_put pos "$FIXTURES/affine_move_dict_put.pos.elisa" 'linear value "t" must be moved explicitly before move into dict put'
run_case affine_move_record_update pos "$FIXTURES/affine_move_record_update.pos.elisa" 'linear value "t" must be moved explicitly before move into record update field "a"'
run_case affine_move_record_update pos "$FIXTURES/affine_move_record_update.pos.elisa" 'value containing linear handles "p" must be moved explicitly before record update'
run_case affine_move_dict_record neg "$FIXTURES/affine_move_dict_record.neg.elisa" "must be moved explicitly"
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "p.h" must be moved explicitly before move into local "u"'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "o.p.h" must be moved explicitly before argument to call "sink"'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "p.h" must be moved explicitly before return'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "p.h" must be moved explicitly before assignment'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "p.h" must be moved explicitly before move into struct literal field "h"'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'must be moved explicitly before move into enum payload "Box.Full" argument 1'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "<value>" must be moved explicitly before argument to call "sink"'
run_case affine_move_projection pos "$FIXTURES/affine_move_projection.pos.elisa" 'linear value "<value>" must be moved explicitly before move into local "u"'
run_case affine_move_projection neg "$FIXTURES/affine_move_projection.neg.elisa" "must be moved explicitly"
echo "-- affine_move_in_loop --"
loop_msg='declared outside the loop is consumed on every iteration'
run_case affine_move_in_for_loop pos "$FIXTURES/affine_move_in_for_loop.pos.elisa" "$loop_msg"
run_case affine_move_in_while_loop pos "$FIXTURES/affine_move_in_while_loop.pos.elisa" "$loop_msg"
run_case affine_move_in_loop_drop pos "$FIXTURES/affine_move_in_loop_drop.pos.elisa" "$loop_msg"
run_case affine_use_after_loop_move pos "$FIXTURES/affine_use_after_loop_move.pos.elisa" 'linear handle value "t" cannot be used after ownership was consumed'
run_case affine_use_in_loop_after_move pos "$FIXTURES/affine_use_in_loop_after_move.pos.elisa" 'linear handle value "t" cannot be used after ownership was consumed'
run_case affine_move_in_loop neg "$FIXTURES/affine_move_in_loop.neg.elisa" "$loop_msg"
run_case affine_move_in_loop neg "$FIXTURES/affine_move_in_loop.neg.elisa" "after ownership was consumed"
abs_pos="$FIXTURES/affine_break_state.pos.elisa"
abs_neg="$FIXTURES/affine_break_state.neg.elisa"
run_case affine_break_state pos "$abs_pos" 'L16 linear handle value "t" cannot be used after ownership was consumed'
run_case affine_break_state pos "$abs_pos" "L21 linear handle value \"t\" $loop_msg"
run_case affine_break_state pos "$abs_pos" 'L33 linear handle value "t" cannot be used after ownership was consumed'
run_case affine_break_state neg "$abs_neg" "$loop_msg"
run_case affine_break_state neg "$abs_neg" "after ownership was consumed"
# Early exits (continue/break/return, also from a loop or a match arm) drop a live
# linear local; matches stage0 (Elisa-core, exit-leak check) line for line.
lel_pos="$FIXTURES/linear_exit_leak.pos.elisa"
lel_neg="$FIXTURES/linear_exit_leak.neg.elisa"
lel_msg='linear value "g" must be consumed before scope exit'
for lel_line in 12 18 23 29 34; do
    run_case linear_exit_leak pos "$lel_pos" "L$lel_line $lel_msg"
done
run_case linear_exit_leak neg "$lel_neg" "must be consumed before scope exit"
# Error exits (a propagating `try`, `raise`, `else return`/`else raise`, an
# `else err:` block that returns) drop a live linear local too; a diverging
# recovery consumes nothing on the fall-through path. Matches stage0 line for line.
leel_pos="$FIXTURES/linear_error_exit_leak.pos.elisa"
leel_neg="$FIXTURES/linear_error_exit_leak.neg.elisa"
for leel_line in 16 21 26 32 37 42; do
    run_case linear_error_exit_leak pos "$leel_pos" "L$leel_line $lel_msg"
done
run_case linear_error_exit_leak neg "$leel_neg" "must be consumed before scope exit"
atr_pos="$FIXTURES/affine_try_recovery.pos.elisa"
atr_neg="$FIXTURES/affine_try_recovery.neg.elisa"
run_case affine_try_recovery pos "$atr_pos" 'L15 linear handle value "h" declared outside the loop is consumed on every iteration'
run_case affine_try_recovery pos "$atr_pos" 'L24 linear handle value "h" cannot be used after ownership was consumed'
run_case affine_try_recovery neg "$atr_neg" "after ownership was consumed"
# A builtin darray method that writes its receiver (push/pop/extend/reserve/
# clear/truncate/as_cstr) through a readonly `T&` or onto a non-`mutable` field;
# matches stage0 line for line.
dmr_pos="$FIXTURES/darray_mutable_receiver.pos.elisa"
dmr_neg="$FIXTURES/darray_mutable_receiver.neg.elisa"
for dmr_case in "9 pop" "12 clear" "14 extend" "16 reserve" "18 push" "20 truncate" "22 push" "24 push" "29 clear"; do
    run_case darray_mutable_receiver pos "$dmr_pos" "L${dmr_case% *} darray ${dmr_case#* } requires a mutable darray receiver"
done
run_case darray_mutable_receiver pos "$dmr_pos" "L26 darray cstr requires a mutable darray receiver (it NUL-terminates in place)"
run_case darray_mutable_receiver neg "$dmr_neg" "requires a mutable darray receiver"
dba_pos="$FIXTURES/darray_builtin_arity.pos.elisa"
for dba_case in "6 push expects 1 argument, got 2" "7 clear expects 0 arguments, got 1" "8 truncate expects 1 argument, got 0" "9 reserve expects 1 argument, got 3" "13 resize expects 1 argument, got 2" "14 extend expects 1 argument, got 0"; do
    run_case darray_builtin_arity pos "$dba_pos" "L${dba_case%% *} darray ${dba_case#* }"
done
run_case darray_builtin_arity neg "$FIXTURES/darray_builtin_arity.neg.elisa" "darray push expects"
dir_pos="$FIXTURES/darray_index_receiver.pos.elisa"
for dir_case in "5 clear" "8 clear" "11 clear" "14 clear" "17 truncate"; do
    run_case darray_index_receiver pos "$dir_pos" "L${dir_case% *} darray ${dir_case#* } requires a mutable darray receiver"
done
run_case darray_index_receiver pos "$dir_pos" "L20 darray push expects 1 argument, got 2"
run_case darray_index_receiver neg "$FIXTURES/darray_index_receiver.neg.elisa" "requires a mutable darray receiver"
# A `continue` is a second back edge; the neg (consumed then continue, per
# iteration) must stay silent.
acs_pos="$FIXTURES/affine_continue_state.pos.elisa"
acs_neg="$FIXTURES/affine_continue_state.neg.elisa"
run_case affine_continue_state neg "$acs_neg" "$loop_msg"
run_case affine_continue_state neg "$acs_neg" "after ownership was consumed"
run_case affine_continue_state pos "$acs_pos" "L11 linear handle value \"h\" $loop_msg"
run_case affine_continue_state pos "$acs_pos" 'L16 linear handle value "h" cannot be used after ownership was consumed'
run_case affine_move_after_if_move pos "$FIXTURES/affine_move_after_if_move.pos.elisa" 'linear handle value "t" cannot be used after ownership was consumed'
run_case affine_use_after_if_else_move pos "$FIXTURES/affine_use_after_if_else_move.pos.elisa" 'linear handle value "t" cannot be used after ownership was consumed'
run_case affine_move_conditional_in_loop pos "$FIXTURES/affine_move_conditional_in_loop.pos.elisa" "$loop_msg"
run_case affine_move_conditional neg "$FIXTURES/affine_move_conditional.neg.elisa" "after ownership was consumed"
run_case affine_move_conditional neg "$FIXTURES/affine_move_conditional.neg.elisa" "$loop_msg"
echo "-- captured_loop_checks --"
cl_pos="$FIXTURES/captured_loop_checks.pos.elisa"
cl_neg="$FIXTURES/captured_loop_checks.neg.elisa"
run_case captured_loop_checks pos "$cl_pos" 'linear value "t" must be moved explicitly before argument to call "sink"'
run_case captured_loop_checks pos "$cl_pos" 'cannot mutate "xs" while it is being iterated'
run_case captured_loop_checks pos "$cl_pos" 'linear value "k" must be consumed before scope exit'
run_case captured_loop_checks pos "$cl_pos" 'linear handle value "u" cannot be used after ownership was consumed'
run_case captured_loop_checks neg "$cl_neg" "must be moved explicitly"
run_case captured_loop_checks neg "$cl_neg" "while it is being iterated"
run_case captured_loop_checks neg "$cl_neg" "must be consumed before scope exit"
run_case captured_loop_checks neg "$cl_neg" "cannot be used after ownership was consumed"
echo "-- linear_partial_consume --"
lp_pos="$FIXTURES/linear_partial_consume.pos.elisa"
lp_neg="$FIXTURES/linear_partial_consume.neg.elisa"
run_case linear_partial_consume pos "$lp_pos" 'linear value "g" must be consumed before scope exit'
run_case linear_partial_consume pos "$lp_pos" 'linear value "h" must be consumed before scope exit'
run_case linear_partial_consume pos "$lp_pos" 'linear value "m" must be consumed before scope exit'
run_case linear_partial_consume neg "$lp_neg" "must be consumed before scope exit"
run_case linear_partial_consume neg "$lp_neg" "cannot be used after ownership was consumed"
echo "-- value_block_nested_loop --"
vn_pos="$FIXTURES/value_block_nested_loop.pos.elisa"
vn_neg="$FIXTURES/value_block_nested_loop.neg.elisa"
run_case value_block_nested_loop pos "$vn_pos" 'value block may not mutate the outer binding "outer" (docs/119 E4)'
run_case value_block_nested_loop pos "$vn_pos" 'value block may not mutate the outer binding "total" (docs/119 E4)'
run_case value_block_nested_loop pos "$vn_pos" 'value block may not mutate the outer binding "deep" (docs/119 E4)'
run_case value_block_nested_loop pos "$vn_pos" 'value block may not mutate the outer binding "ys" through a call'
run_case value_block_nested_loop neg "$vn_neg" "value block may not mutate"
run_case value_block_nested_loop neg "$vn_neg" "names no binding in scope"
# The rendered TYPE must be the type, not whatever bytes now sit where a dead buffer was
# (these printed 'got set ele' / 'got ment' while the substring above still matched).
echo "-- affine_set_key (rendered types) --"
run_case affine_set_key pos "$FIXTURES/affine_set_key.pos.elisa" 'set elements cannot contain linear handles, got Handle?'
run_case affine_set_key pos "$FIXTURES/affine_set_key.pos.elisa" 'dict keys cannot contain linear handles, got Pair'
run_case affine_set_key pos "$FIXTURES/affine_set_key.pos.elisa" 'set elements cannot contain linear handles, got darray[Handle]'

echo "-- call_argument_alias --"
ca_pos="$FIXTURES/call_argument_alias.pos.elisa"
ca_neg="$FIXTURES/call_argument_alias.neg.elisa"
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "x" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "read_write" passes "y" to mutable reference parameter "a" while argument for "b" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "grow" passes "v" to mutable reference parameter "v" while argument for "first" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "whole" passes "p" to mutable reference parameter "p" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "q" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "w" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "z" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "r" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "s" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "u" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "t" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "grow" passes "vv" to mutable reference parameter "v" while argument for "first" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "poke" passes "c" to mutable reference parameter "other" while argument for "self" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "m" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
run_case call_argument_alias pos "$ca_pos" 'call "f" passes "source" to mutable reference parameter "b" while argument for "a" refers to overlapping memory'
returned_alias_out="$("$RPT" < "$ca_pos" 2>&1)"
returned_alias_count="$(grep -Fc 'call "f" passes "source" to mutable reference parameter "b" while argument for "a" refers to overlapping memory' <<< "$returned_alias_out")"
if [[ "$returned_alias_count" -eq 3 ]]; then
    echo "  PASS call_argument_alias.pos (direct, wrapped and conditional returned-ref origins rejected)"
else
    echo "  FAIL call_argument_alias.pos: expected 3 returned-ref origin diagnostics, got $returned_alias_count" >&2
    failed=$((failed + 1))
fi
run_case call_argument_alias neg "$ca_neg" "refers to overlapping memory"
echo "-- affine_container_reference --"
acr_pos="$FIXTURES/affine_container_reference.pos.elisa"
acr_neg="$FIXTURES/affine_container_reference.neg.elisa"
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[Handle]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got view[Handle]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got Handle[2]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got dict[i64, Handle]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[darray[Handle]]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[Handle?]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[Pair]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got Box[Handle]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got Pair[2]&'
run_case affine_container_reference pos "$acr_pos" 'references to values containing linear handles are not supported; got darray[Handle[2]]&'
run_case affine_container_reference neg "$acr_neg" "references to values containing linear handles"
echo "-- affine_container_address --"
aca_pos="$FIXTURES/affine_container_address.pos.elisa"
aca_neg="$FIXTURES/affine_container_address.neg.elisa"
aca_out="$("$RPT" < "$aca_pos" 2>&1)"
total=$((total + 1))
if [[ "$(grep -c 'cannot take address of value containing linear handles' <<< "$aca_out")" == 8 ]]; then
    echo "  PASS affine_container_address.pos (all 8 address sites fired)"
else
    echo "  FAIL affine_container_address.pos: want all 8 address sites: $aca_out" >&2
    failed=$((failed + 1))
fi
run_case affine_container_address neg "$aca_neg" "cannot take address"

echo "-- affine_darray_consume --"
adc_pos="$FIXTURES/affine_darray_consume.pos.elisa"
adc_neg="$FIXTURES/affine_darray_consume.neg.elisa"
adc_out="$("$RPT" < "$adc_pos" 2>&1)"
total=$((total + 1))
if [[ "$(grep -c 'must be consumed before scope exit' <<< "$adc_out")" == 6 && "$(grep -c 'would drop must-consume element' <<< "$adc_out")" == 5 ]]; then
    echo "  PASS affine_darray_consume.pos (6 unconsumed containers, 5 element drops)"
else
    echo "  FAIL affine_darray_consume.pos: want 6 unconsumed + 5 drops: $adc_out" >&2
    failed=$((failed + 1))
fi
run_case affine_darray_consume pos "$adc_pos" 'darray of must-consume elements (drain with `for x in move c:`) "xs" must be consumed before scope exit'
run_case affine_darray_consume pos "$adc_pos" 'darray of must-consume elements (drain with `for x in move c:`) "d" must be consumed before scope exit'
run_case affine_darray_consume pos "$adc_pos" 'indexed assignment would drop must-consume element(s) of type Handle'
run_case affine_darray_consume pos "$adc_pos" 'darray clear would drop must-consume element(s) of type Tracked'
run_case affine_darray_consume neg "$adc_neg" "must-consume"

echo "-- affine_set_key --"
ask_pos="$FIXTURES/affine_set_key.pos.elisa"
ask_neg="$FIXTURES/affine_set_key.neg.elisa"
run_case affine_set_key pos "$ask_pos" "set elements cannot contain linear handles, got Handle?"
run_case affine_set_key pos "$ask_pos" "dict keys cannot contain linear handles, got Pair"
run_case affine_set_key pos "$ask_pos" "set elements cannot contain linear handles, got darray[Handle]"
run_case affine_set_key pos "$ask_pos" "dict keys cannot contain linear handles, got Handle?"
run_case affine_set_key neg "$ask_neg" "cannot contain linear handles"
run_case affine_set_key neg "$ask_neg" "must be consumed before scope exit"

echo "-- affine_comprehension --"
acm_pos="$FIXTURES/affine_comprehension.pos.elisa"
acm_neg="$FIXTURES/affine_comprehension.neg.elisa"
run_case affine_comprehension pos "$acm_pos" "list comprehension value iteration does not support affine element type Handle"
run_case affine_comprehension pos "$acm_pos" "list comprehension value iteration does not support affine element type Pair"
run_case affine_comprehension pos "$acm_pos" "linear value \"g\" must be moved explicitly before move into list comprehension element"
run_case affine_comprehension neg "$acm_neg" "list comprehension"
run_case affine_comprehension neg "$acm_neg" "consumed on every iteration"
run_case affine_comprehension neg "$acm_neg" "must be consumed before scope exit"
run_case affine_comprehension_repeat pos "$FIXTURES/affine_comprehension_repeat.pos.elisa" "consumed on every iteration"

echo "-- affine_container_return --"
acr_pos="$FIXTURES/affine_container_return.pos.elisa"
acr_neg="$FIXTURES/affine_container_return.neg.elisa"
for acr_name in xs made t ps; do
    run_case affine_container_return pos "$acr_pos" "value containing linear handles \"$acr_name\" must be moved explicitly before return"
    run_case affine_container_return pos "$acr_pos" "\"$acr_name\" must be consumed before scope exit"
done
run_case affine_container_return neg "$acr_neg" "must be moved explicitly before return"
run_case affine_container_return neg "$acr_neg" "must be consumed before scope exit"
run_case affine_container_return neg "$acr_neg" "value backed by a short-lived region escapes via return"

echo "-- affine_bulk_copy --"
abc_pos="$FIXTURES/affine_bulk_copy.pos.elisa"
abc_neg="$FIXTURES/affine_bulk_copy.neg.elisa"
for abc_element in Handle Pair; do
    run_case affine_bulk_copy pos "$abc_pos" "darray extend does not support affine element type $abc_element; push elements individually with explicit move"
done
for abc_element in Handle "darray[Handle]"; do
    run_case affine_bulk_copy pos "$abc_pos" "bulk darray push does not support affine element type $abc_element; push elements individually with explicit move"
done
run_case affine_bulk_copy pos "$abc_pos" "query expression value iteration does not support affine element type Handle"
run_case affine_bulk_copy neg "$abc_neg" "darray extend does not support affine element type"
run_case affine_bulk_copy neg "$abc_neg" "bulk darray push does not support affine element type"

echo "-- affine_spread_copy --"
asc_pos="$FIXTURES/affine_spread_copy.pos.elisa"
asc_neg="$FIXTURES/affine_spread_copy.neg.elisa"
asc_tail='; push elements individually with explicit move'
for asc_case in "22 Handle" "31 Handle" "32 Pair" "33 Handle" "34 Handle"; do
    asc_line=${asc_case%% *}
    asc_element=${asc_case#* }
    run_case affine_spread_copy pos "$asc_pos" "L$asc_line spread darray literal does not support affine element type $asc_element$asc_tail"
done
run_case affine_spread_copy neg "$asc_neg" "spread darray literal does not support affine element type"

echo "-- affine_bulk_copy_field --"
abf_pos="$FIXTURES/affine_bulk_copy_field.pos.elisa"
abf_neg="$FIXTURES/affine_bulk_copy_field.neg.elisa"
abf_tail=' does not support affine element type Handle; push elements individually with explicit move'
run_case affine_bulk_copy_field pos "$abf_pos" "L23 darray extend$abf_tail"
run_case affine_bulk_copy_field pos "$abf_pos" "L24 bulk darray push$abf_tail"
run_case affine_bulk_copy_field pos "$abf_pos" "L25 spread darray literal$abf_tail"
run_case affine_bulk_copy_field pos "$abf_pos" "L26 spread darray literal$abf_tail"
run_case affine_bulk_copy_field neg "$abf_neg" "does not support affine element type"

echo "-- drain_discipline --"
dd_pos="$FIXTURES/drain_discipline.pos.elisa"
dd_neg="$FIXTURES/drain_discipline.neg.elisa"
dd_message='a `for ... in move` drain must consume every element'
for dd_line in 13 22 29 36 43; do
    run_case drain_discipline pos "$dd_pos" "L$dd_line $dd_message"
done
run_case drain_discipline neg "$dd_neg" "$dd_message"
run_case drain_discipline neg "$dd_neg" "must be consumed before scope exit"

echo "-- shift_match_guards --"
guard_pos="$FIXTURES/shift_match_guards.pos.elisa"
guard_neg="$FIXTURES/shift_match_guards.neg.elisa"
guard_expectations=(
    "shift count is out of range for every integer width (valid range 0..63)"
    "shift count is negative"
    "shift by zero has no effect"
    "operator requires numeric operands"
    "operator requires integral operands"
)
for guard_case in pos neg; do
    guard_file="$guard_pos"
    [[ "$guard_case" == "neg" ]] && guard_file="$guard_neg"
    total=$((total + ${#guard_expectations[@]}))
    guard_out="$("$RPT" < "$guard_file" 2>&1)"
    if ! check_parses "$guard_file" "$guard_out"; then
        failed=$((failed + ${#guard_expectations[@]}))
        continue
    fi
    for guard_expect in "${guard_expectations[@]}"; do
        guard_count="$(grep -oF -- "$guard_expect" <<< "$guard_out" | wc -l | tr -d ' ')"
        if [[ "$guard_case" == "pos" && "$guard_count" -ge 2 ]]; then
            echo "  PASS shift_match_guards.pos (found $guard_count: \"$guard_expect\")"
        elif [[ "$guard_case" == "neg" && "$guard_count" -eq 0 ]]; then
            echo "  PASS shift_match_guards.neg (silent: \"$guard_expect\")"
        else
            echo "  FAIL shift_match_guards.$guard_case for \"$guard_expect\" (found $guard_count)" >&2
            echo "$guard_out" | sed 's/^/    /' >&2
            failed=$((failed + 1))
        fi
    done
done

echo "-- local_borrow_container_escape --"
lbe_pos="$FIXTURES/local_borrow_container_escape.pos.elisa"
lbe_neg="$FIXTURES/local_borrow_container_escape.neg.elisa"
for lbe_message in \
    "L16 darray push stores a reference to function-local storage into longer-lived storage" \
    "L22 darray push stores a reference to function-local storage into longer-lived storage" \
    "L29 returning an aggregate or helper result that contains a reference into function-local storage" \
    "L33 storing an aggregate that contains a reference to function-local storage into longer-lived storage" \
    "L38 storing an aggregate that contains a reference to function-local storage into longer-lived storage" \
    "L43 storing a forwarded reference into longer-lived storage"; do
    run_case local_borrow_container_escape pos "$lbe_pos" "$lbe_message"
done
for lbe_message in "stores a reference to function-local storage" "storing an aggregate that contains" "storing a forwarded reference" "contains a reference into function-local storage"; do
    run_case local_borrow_container_escape neg "$lbe_neg" "$lbe_message"
done

echo "-- local_borrow_ref_alias_store --"
lra_pos="$FIXTURES/local_borrow_ref_alias_store.pos.elisa"
lra_neg="$FIXTURES/local_borrow_ref_alias_store.neg.elisa"
for lra_message in \
    "L19 storing an aggregate that contains a reference to function-local storage into longer-lived storage" \
    "L28 storing an aggregate that contains a reference to function-local storage into longer-lived storage" \
    "L36 storing an aggregate that contains a reference to function-local storage into longer-lived storage" \
    "L43 storing an aggregate that contains a reference to function-local storage into longer-lived storage"; do
    run_case local_borrow_ref_alias_store pos "$lra_pos" "$lra_message"
done
run_case local_borrow_ref_alias_store neg "$lra_neg" "function-local storage"

# A mutating builtin collection method on a field/index place rooted at an `lmut`
# parameter (`p.items.clear()`) is a hidden mutation of `p`: it must be written as a
# reassignment of the root. A `for` capture does not license it, a `while` capture
# does; matches stage0 line for line (and column for column at the CLI).
lfb_pos="$FIXTURES/lmut_field_builtin_mutation.pos.elisa"
lfb_neg="$FIXTURES/lmut_field_builtin_mutation.neg.elisa"
# The diagnostic names the mutated field PLACE (stage0 lmutMutatedPlaceName).
for lfb_case in 16:p.items 18:p.items 20:p.q.items 22:p.d 23:p.s 25:p.name 27:p.items 29:p.items 32:p.items; do
    lfb_line="${lfb_case%%:*}"
    lfb_place="${lfb_case#*:}"
    run_case lmut_field_builtin_mutation pos "$lfb_pos" "L$lfb_line mutation of \`lmut\` value \"$lfb_place\" must be a reassignment (docs/120 §10): write \`$lfb_place <- …\` so the dataflow is visible"
done
run_case lmut_field_builtin_mutation neg "$lfb_neg" "must be a reassignment"

# Nested bodies have no contract prologue: stage0 rejects every `requires`/`ensure`
# inside a block/if/loop/match arm, so wrapping one in `can E:` must not hide it.
cnn_pos="$FIXTURES/contract_not_first_nested.pos.elisa"
cnn_neg="$FIXTURES/contract_not_first_nested.neg.elisa"
for cnn_line in 5 9 13 18 24 30; do
    run_case contract_not_first_nested pos "$cnn_pos" "L$cnn_line \`requires\`/\`ensure\` contracts must be the first statements of the function body"
done
run_case contract_not_first_nested neg "$cnn_neg" "must be the first statements"

# A struct that reaches its grown container only through a `&` field owns no region of its
# own, so stage0 cannot thread `@__rg_p` into the grower (stage1 used to miscompile: SIGBUS).
echo "-- region_param_ref_field --"
run_case region_param_ref_field pos "$REPO_ROOT/test/repro/region_param_ref_field.pos.elisa" "L14 cannot infer region parameter \"__rg_p\" for call to \"add\""
run_case region_param_ref_field pos "$REPO_ROOT/test/repro/region_param_ref_field.pos.elisa" "L15 cannot infer region parameter \"__rg_p\" for call to \"add\""
run_case region_param_ref_field pos "$REPO_ROOT/test/repro/region_param_ref_field.pos.elisa" "L17 cannot infer region parameter \"__rg_p\" for call to \"add\""
run_case region_param_ref_field neg "$REPO_ROOT/test/repro/region_param_ref_field.neg.elisa" "cannot infer region parameter"

echo "-- region_param_value_arg_owner_line_zero --"
run_case region_param_value_arg_owner_line_zero pos "$REPO_ROOT/test/repro/region_param_value_arg_owner_line_zero.pos.elisa" 'argument 1 to "put" expects i64& @r, got i64'
run_case region_param_value_arg_owner_line_zero pos "$REPO_ROOT/test/repro/region_param_value_arg_owner_line_zero.pos.elisa" 'cannot infer region parameter "r" for call to "put"'
run_case region_param_value_arg_owner_line_zero neg "$REPO_ROOT/test/repro/region_param_value_arg_owner_line_zero.neg.elisa" "cannot infer region parameter"

echo "-- global_storage_return --"
run_case global_storage_return pos "$FIXTURES/global_storage_return.pos.elisa" "L16 value backed by global \"store\" cannot be returned by value with a region-less type"
run_case global_storage_return pos "$FIXTURES/global_storage_return.pos.elisa" "L19 value backed by global \"gitems\" cannot be returned by value with a region-less type"
run_case global_storage_return pos "$FIXTURES/global_storage_return.pos.elisa" "L22 value backed by global \"nested\" cannot be returned by value with a region-less type"
run_case global_storage_return pos "$FIXTURES/global_storage_return.pos.elisa" "L25 value backed by global \"gitems\" cannot be returned by value with a region-less type"
run_case global_storage_return pos "$FIXTURES/global_storage_return.pos.elisa" "L29 value backed by global \"gitems\" cannot be returned by value with a region-less type"
run_case global_storage_return pos "$FIXTURES/global_storage_return.pos.elisa" "L34 value backed by global \"store\" cannot be returned by value with a region-less type"
run_case global_storage_return pos "$FIXTURES/global_storage_return.pos.elisa" "L37 value backed by global \"name\" cannot be returned by value with a region-less type"
run_case global_storage_return pos "$FIXTURES/global_storage_return.pos.elisa" "L40 value backed by global \"store\" cannot be returned by value with a region-less type"
run_case global_storage_return neg "$FIXTURES/global_storage_return.neg.elisa" "cannot be returned by value with a region-less type"
run_case global_storage_return_owner_collision neg "$FIXTURES/global_storage_return.owner_collision.neg.elisa" "value backed by global \"results\" cannot be returned by value with a region-less type"
run_case global_storage_return_owner_return pos "$FIXTURES/global_storage_return.owner_return.pos.elisa" "L8 value backed by global \"stored\" cannot be returned by value with a region-less type"
run_case global_storage_return_owner_return pos "$FIXTURES/global_storage_return.owner_return.pos.elisa" "L11 value backed by global \"stored\" cannot be returned by value with a region-less type"
run_case global_storage_return_nested_owner pos "$FIXTURES/global_storage_return.nested_owner.pos.elisa" "L32 value backed by global \"nested_stored\" cannot be returned by value with a region-less type"
run_case global_storage_return_nested_owner pos "$FIXTURES/global_storage_return.nested_owner.pos.elisa" "L35 value backed by global \"alias_stored\" cannot be returned by value with a region-less type"
run_case global_storage_return_nested_owner pos "$FIXTURES/global_storage_return.nested_owner.pos.elisa" "L38 value backed by global \"other_alias_stored\" cannot be returned by value with a region-less type"
run_case global_storage_return_nested_owner pos "$FIXTURES/global_storage_return.nested_owner.pos.elisa" "L41 value backed by global \"parent_alias_stored\" cannot be returned by value with a region-less type"
run_case global_storage_return_nested_owner pos "$FIXTURES/global_storage_return.nested_owner.pos.elisa" "L44 value backed by global \"root_stored\" cannot be returned by value with a region-less type"
run_case global_storage_return_nested_owner pos "$FIXTURES/global_storage_return.nested_owner.pos.elisa" "L61 value backed by global \"relative_stored\" cannot be returned by value with a region-less type"
run_case global_storage_return_nested_collision neg "$FIXTURES/global_storage_return.nested_collision.neg.elisa" "value backed by global \"results\" cannot be returned by value with a region-less type"
run_case global_storage_return_nested_collision neg "$FIXTURES/global_storage_return.nested_collision.neg.elisa" "value backed by global \"alias_results\" cannot be returned by value with a region-less type"
echo
