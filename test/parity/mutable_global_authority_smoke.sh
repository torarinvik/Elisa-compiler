#!/usr/bin/env bash
# Default mutable-global authority: direct operations and transitive callers must
# reject without a local member grant. No #globals/-Wglobals opt-in is used.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
if [ "${ELISA_GLOBAL_AUTHORITY_REPORTER_PREBUILT:-0}" != 1 ]; then
    source "$REPO_ROOT/test/parity/build_parse_report.sh"
fi
RPT="${ELISA_PARSE_REPORT:-$REPO_ROOT/build/parse_report}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
cases=0
run_case() {
    local name="$1" expected="$2" output
    cases=$((cases+1))
    cat > "$WORK/$name.elisa"
    output="$("$RPT" < "$WORK/$name.elisa")"
    if ! printf '%s\n' "$output" | grep -q '^P 0$'; then
        printf 'FAIL %s: source did not parse\n%s\n' "$name" "$output" >&2
        failed=$((failed+1))
        return
    fi
    if [ "$expected" = clean ]; then
        if ! printf '%s\n' "$output" | grep -q '^D 0$'; then
            printf 'FAIL %s: expected no diagnostics\n%s\n' "$name" "$output" >&2
            failed=$((failed+1))
        fi
    elif ! printf '%s\n' "$output" | grep -Fq "$expected"; then
        printf 'FAIL %s: missing %s\n%s\n' "$name" "$expected" "$output" >&2
        failed=$((failed+1))
    fi
    if printf '%s\n' "$output" | grep -q '^S '; then
        if ! printf '%s\n' "$output" | awk -v expected="$expected" -v name="$name" '/^S /{severity=$2} /requires can\[Global\]/{if(severity==1)global_error=1} /requires can\[Unsafe\]/{if(severity==1)unsafe_error=1} END{if(expected ~ /requires can\[Global\]/ && name!="immutable_call_legacy_opt_in" && !global_error)exit 1; if(expected ~ /requires can\[Unsafe\]/ && !unsafe_error)exit 1}'; then
            printf 'FAIL %s: mandatory effect diagnostic is not severity 1\n%s\n' "$name" "$output" >&2
            failed=$((failed+1))
        fi
    fi
}
run_case inline_span_direct_positive clean <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    return hot can Global.Read
CASE
run_case inline_span_direct_sibling_negative 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    return (hot can Global.Read) + hot
CASE
run_case inline_span_nested_positive clean <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    can Global.Read:
        return hot
def main() -> i64:
    return (reader() + 1) can Global.Read
CASE
run_case inline_span_sibling_negative 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    can Global.Read:
        return hot
def main() -> i64:
    return (reader() can Global.Read) + reader()
CASE
run_case inline_span_wrong_axis_negative 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    can Global.Read:
        return hot
def main() -> i64:
    return reader() can Global.Write
CASE
run_case nested_trusted_same_member 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader(depth: i64) -> i64:
    if depth > 0:
        return reader(depth - 1)
    trusted Global.Read:
        can Global.Read:
            return hot
def main() -> i64:
    callback: fn(i64)->i64 = reader
    return callback(0)
CASE
run_case nested_trusted_other_member 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def writer() -> i64:
    trusted Global.Read:
        can Global.Write:
            hot <- 2
    return 0
def main() -> i64:
    callback: fn()->i64 can[Global.Write] = writer
    can Global.Read:
        return callback()
CASE
run_case trusted_unsafe_same_member clean <<'CASE'
def helper() -> i64:
    trusted Unsafe.PointerCast:
        can Unsafe.PointerCast:
            return 1
def main() -> i64:
    callback: fn()->i64 = helper
    return callback()
CASE
run_case trusted_unsafe_other_member 'got fn() -> i64 can[Unsafe]' <<'CASE'
def helper() -> i64:
    trusted Unsafe.PointerCast:
        can Unsafe.UncheckedIndex:
            return 1
def main() -> i64:
    callback: fn()->i64 = helper
    return callback()
CASE
run_case grouped_signature_only 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def update() -> i64 can[Global{Read,Write}]:
    hot <- hot + 1
    return hot
CASE
run_case grouped_signature_local_grant clean <<'CASE'
global mutable hot: i64 = 1
def update() -> i64 can[Global{Read,Write}]:
    can Global{Read,Write}:
        hot <- hot + 1
        return hot
def main() -> i64:
    can Global{Read,Write}:
        return update()
CASE
run_case unused_block_can_export 'requires can[Global]' <<'CASE'
def reader() -> i64:
    can Global.Read:
        return 1
def main() -> i64:
    return reader()
CASE
run_case unused_inline_can_export 'requires can[Global]' <<'CASE'
def reader() -> i64:
    return 1 can Global.Read
def main() -> i64:
    return reader()
CASE
run_case colliding_receiver_pure clean <<'CASE'
global mutable hot: i64 = 1
struct Item:
    value: i64
struct Other:
    value: i64
impl Item:
    def read(self: Item) -> i64:
        return self.value
impl Other:
    def read(self: Other) -> i64:
        can Global.Read:
            return hot
def main(item: Item) -> i64:
    return item.read()
CASE
run_case colliding_receiver_effectful 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
struct Item:
    value: i64
struct Other:
    value: i64
impl Item:
    def read(self: Item) -> i64:
        return self.value
impl Other:
    def read(self: Other) -> i64:
        can Global.Read:
            return hot
def main(item: Other) -> i64:
    return item.read()
CASE
run_case grouped_global_grant clean <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global{Read,Write}:
        hot <- hot + 1
        return hot
CASE
run_case grouped_global_export 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def update() -> i64 can[Global{Read,Write}]:
    can Global{Read,Write}:
        hot <- hot + 1
        return hot
def main() -> i64:
    return update()
CASE
run_case runtime_unsafe_can_operation clean <<'CASE'
# std
# unsafe
def main() -> i64:
    local: mutable i64 = 1
    can Unsafe.PointerCast:
        pointer: i64& = (&local).cast[i64&]
        return pointer
CASE
run_case runtime_unsafe_trusted_operation clean <<'CASE'
# std
# unsafe
def main() -> i64:
    local: mutable i64 = 1
    trusted Unsafe.PointerCast:
        pointer: i64& = (&local).cast[i64&]
        return pointer
CASE
run_case runtime_unsafe_can_exports 'requires can[Unsafe]' <<'CASE'
# std
# unsafe
def helper() -> i64:
    can Unsafe.PointerCast:
        return 1
def main() -> i64:
    return helper()
CASE
run_case unsafe_can_operation clean <<'CASE'
# unsafe
def main() -> i64:
    local: mutable i64 = 1
    can Unsafe.PointerCast:
        pointer: i64& = (&local).cast[i64&]
        return pointer
CASE
run_case unsafe_trusted_operation clean <<'CASE'
# unsafe
def main() -> i64:
    local: mutable i64 = 1
    trusted Unsafe.PointerCast:
        pointer: i64& = (&local).cast[i64&]
        return pointer
CASE
run_case direct_read 'mutable global read requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    return hot
CASE
run_case direct_write 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    hot <- 2
    return 0
CASE
run_case member_read_grant clean <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read:
        return hot
CASE
run_case wrong_member 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read:
        hot <- 2
    return 0
CASE
run_case compound_read 'mutable global read requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Write:
        hot += 2
    return 0
CASE
run_case plain_store clean <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Write:
        hot <- 2
    return 0
CASE
run_case immutable clean <<'CASE'
global cold: i64 = 2
const frozen: i64 = 3
def main() -> i64:
    return cold + frozen
CASE
run_case parameter_shadow clean <<'CASE'
global mutable hot: i64 = 1
def identity(hot: i64) -> i64:
    return hot
def main() -> i64:
    return identity(3)
CASE
run_case local_shadow clean <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    hot: i64 = 7
    return hot
CASE
run_case initializer_before_binding 'mutable global read requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    hot: i64 = hot
    return hot
CASE
run_case shadow_scope_exit 'mutable global read requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    block:
        hot: i64 = 2
    return hot
CASE
run_case qualified_read 'mutable global read requires can[Global]' <<'CASE'
module Box:
    public:
        global mutable hot: i64 = 1
def main() -> i64:
    return Box::hot
CASE
run_case imported_read 'mutable global read requires can[Global]' <<'CASE'
module Box:
    public:
        global mutable hot: i64 = 1
using Box::hot
def main() -> i64:
    return hot
CASE
run_case alias_read 'mutable global read requires can[Global]' <<'CASE'
module Box:
    public:
        global mutable hot: i64 = 1
using Box as B
def main() -> i64:
    return B::hot
CASE
run_case index_read 'mutable global read requires can[Global]' <<'CASE'
global mutable slots: array[i64, 4] = [0, 0, 0, 0]
global mutable cursor: i64 = 0
def main() -> i64:
    can Global.Write:
        slots[cursor] <- 1
    return 0
CASE
run_case can_exports 'call to "reader" requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    can Global.Read:
        return hot
def main() -> i64:
    return reader()
CASE
run_case trusted_firewall 'mutable global read requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    trusted Global.Read:
        return hot
def main() -> i64:
    return reader()
CASE
run_case empty_trusted 'mutable global read requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    trusted:
        return hot
CASE
run_case bracketed_wrong_member 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    trusted [Global.Read]:
        hot <- 2
    return 0
CASE
run_case signature_is_not_local_authority 'mutable global read requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64 can[Global.Read]:
    return hot
CASE
run_case mutable_reference 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read:
        reference: mutable i64& = &hot
        reference <- 2
    return 0
CASE
run_case mutable_argument 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def update(value: mutable i64&) -> void:
    value <- 2
def main() -> i64:
    can Global.Read:
        update(&hot)
    return 0
CASE
run_case inferred_alias 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read:
        reference = &hot
        reference <- 2
    return 0
CASE
run_case readonly_alias clean <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read:
        reference: i64& = &hot
        return reference
CASE
run_case mutable_ref_return 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def expose() -> mutable i64&:
    can Global.Read:
        return &hot
CASE
run_case function_alias_call 'call to "callback" requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    can Global.Read:
        return hot
def main() -> i64:
    callback = reader
    return callback()
CASE
run_case callback_handoff 'callback argument requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    can Global.Read:
        return hot
def apply(callback: fn() -> i64 can[Global.Read]) -> i64:
    can Global.Read:
        return callback()
def main() -> i64:
    return apply(reader)
CASE
run_case callback_handoff_granted clean <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    can Global.Read:
        return hot
def apply(callback: fn() -> i64 can[Global.Read]) -> i64:
    can Global.Read:
        return callback()
def main() -> i64:
    can Global.Read:
        return apply(reader)
CASE
run_case immutable_call_default clean <<'CASE'
global cold: i64 = 1
def reader() -> i64:
    return cold
def main() -> i64:
    return reader()
CASE
run_case immutable_call_legacy_opt_in 'warning: call to "reader" requires can[Global]' <<'CASE'
# globals
global cold: i64 = 1
def reader() -> i64:
    return cold
def main() -> i64:
    return reader()
CASE
run_case immutable_callback 'argument 1 to "apply" expects fn() -> i64' <<'CASE'
global cold: i64 = 1
def reader() -> i64:
    return cold
def apply(callback: fn() -> i64) -> i64:
    return callback()
def main() -> i64:
    return apply(reader)
CASE
run_case qualified_overload clean <<'CASE'
global mutable hot: i64 = 1
def choose(value: bool) -> i64:
    can Global.Read:
        return hot
def choose(value: i64) -> i64:
    return value
def main() -> i64:
    value: i64 = 2
    return choose(value)
CASE
run_case qualified_overload_mutable 'call to "choose" requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def choose(value: bool) -> i64:
    can Global.Read:
        return hot
def choose(value: i64) -> i64:
    return value
def main() -> i64:
    return choose(true)
CASE
run_case nested_module_import 'mutable global read requires can[Global]' <<'CASE'
module Box:
    public:
        module Inner:
            public:
                global mutable hot: i64 = 1
using Box::Inner as B
def main() -> i64:
    return B::hot
CASE
run_case immutable_callback_compatible clean <<'CASE'
global cold: i64 = 1
def reader() -> i64:
    return cold
def apply(callback: fn() -> i64 can[Global.Read]) -> i64:
    return 0
def main() -> i64:
    return apply(reader)
CASE
run_case nested_module_qualified 'mutable global read requires can[Global]' <<'CASE'
module Box:
    public:
        module Inner:
            public:
                global mutable hot: i64 = 1
def main() -> i64:
    return Box::Inner::hot
CASE
run_case verbatim_module_qualified 'mutable global read requires can[Global]' <<'CASE'
module Box::Inner:
    public:
        global mutable hot: i64 = 1
def main() -> i64:
    return Box::Inner::hot
CASE
run_case same_name_global_identity clean <<'CASE'
module Mutable:
    public:
        global mutable hot: i64 = 1
module Immutable:
    public:
        global hot: i64 = 2
def main() -> i64:
    return Immutable::hot
CASE
run_case explicit_global_arena 'mutable global write requires can[Global]' <<'CASE'
global mutable arena: Arena = zeroed
def grow(out: mutable darray[i32]&) -> void:
    can Global.Read:
        in arena:
            out.push(1)
CASE
run_case wrapped_reader 'call to "reader" requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    can Global.Read:
        return hot
def main() -> i64:
    return (reader)()
CASE
run_case generic_reader_local 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader[T](value: T) -> i64:
    can Global.Read:
        return hot
def main() -> i64:
    value: i64 = 0
    return reader[i64](value)
CASE
run_case wrapped_inferred_ref 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read:
        reference = (&hot)
        reference <- 2
    return 0
CASE
run_case method_reader 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
struct Item:
    value: i64
impl Item:
    def read(self: Item) -> i64:
        can Global.Read:
            return hot
def main() -> i64:
    item: Item = Item{value: 0}
    return item.read()
CASE
run_case qualified_method_reader 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
module Box:
    public:
        struct Item:
            value: i64
        impl Item:
            def read(self: Item) -> i64:
                can Global.Read:
                    return hot
def main(item: Box::Item) -> i64:
    return item.read()
CASE
run_case imported_method_reader 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
module Box:
    public:
        struct Item:
            value: i64
        impl Item:
            def read(self: Item) -> i64:
                can Global.Read:
                    return hot
from Box import Item
def main(item: Item) -> i64:
    return item.read()
CASE
run_case writable_cast 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read, Unsafe.PointerCast:
        reference: mutable i64& = (&hot).cast[mutable i64&]
        reference <- 2
    return 0
CASE
run_case default_reader 'mutable global read requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader(value: i64 = hot) -> i64:
    return value
def main() -> i64:
    return reader()
CASE
run_case collection_mutation 'mutable global write requires can[Global]' <<'CASE'
global mutable values: darray[i64] = []
def main() -> i64:
    can Global.Read:
        values.push(1)
    return 0
CASE
run_case lambda_handoff 'callback argument requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def apply(callback: fn()->i64 can[Global.Read]) -> i64:
    can Global.Read:
        return callback()
def main() -> i64:
    callback: fn()->i64 can[Global.Read] = fn() -> i64:
        can Global.Read:
            return hot
    return apply(callback)
CASE
run_case supplied_default clean <<'CASE'
global mutable hot: i64 = 1
def reader(value: i64 = hot) -> i64:
    return value
def main() -> i64:
    return reader(3)
CASE
run_case granted_default clean <<'CASE'
global mutable hot: i64 = 1
def reader(value: i64 = hot) -> i64:
    return value
def main() -> i64:
    can Global.Read:
        return reader()
CASE
run_case callback_factory_creation clean <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64 can[Global.Read]:
    can Global.Read:
        return hot
def factory() -> fn()->i64 can[Global.Read]:
    return reader
def main() -> i64:
    callback = factory()
    return 0
CASE
run_case callback_factory_invocation 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64 can[Global.Read]:
    can Global.Read:
        return hot
def factory() -> fn()->i64 can[Global.Read]:
    return reader
def main() -> i64:
    callback = factory()
    return callback()
CASE
run_case callback_branch_union 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64 can[Global.Read]:
    can Global.Read:
        return hot
def pure() -> i64:
    return 0
def main(flag: bool) -> i64:
    callback: mutable fn()->i64 can[Global.Read] = pure
    if flag:
        callback <- reader
    else:
        callback <- pure
    return callback()
CASE
run_case effect_alias_callback 'requires can[Global]' <<'CASE'
alias ReadState = Global.Read
def reader() -> i64 can[ReadState]:
    return 1
def factory() -> fn()->i64 can[ReadState]:
    return reader
def main() -> i64:
    callback = factory()
    return callback()
CASE
run_case effect_alias_callback_granted clean <<'CASE'
alias ReadState = Global.Read
def reader() -> i64 can[ReadState]:
    return 1
def factory() -> fn()->i64 can[ReadState]:
    return reader
def main() -> i64:
    callback = factory()
    can ReadState:
        return callback()
CASE
run_case alias_callback_factory 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def writer() -> i64 can[Global.Write]:
    can Global.Write:
        hot <- 2
    return 0
type Action = fn()->i64 can[Global.Write]
def factory() -> Action:
    return writer
def main() -> i64:
    action = factory()
    can Global.Read:
        return action()
CASE
run_case optional_callback_factory 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def writer() -> i64 can[Global.Write]:
    can Global.Write:
        hot <- 2
    return 0
type Action = fn()->i64 can[Global.Write]
def factory(flag: bool) -> Action?:
    if flag:
        return writer
    return null
def main(flag: bool) -> i64:
    action = factory(flag)
    if action is callback:
        can Global.Read:
            return callback()
    return 0
CASE
run_case callback_loop_union 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def writer() -> i64 can[Global.Write]:
    can Global.Write:
        hot <- 2
    return 0
def pure() -> i64:
    return 0
def main(flag: bool) -> i64:
    callback: mutable fn()->i64 can[Global.Write] = pure
    while flag:
        callback <- writer
        break
    can Global.Read:
        return callback()
CASE
run_case inline_read clean <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    return hot can Global.Read
CASE
run_case inline_exports 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    return hot can Global.Read
def main() -> i64:
    return reader()
CASE
run_case inline_default clean <<'CASE'
global mutable hot: i64 = 1
def reader(value: i64 = hot) -> i64:
    return value
def main() -> i64:
    return reader() can Global.Read
CASE
run_case qualified_global_arena 'mutable global write requires can[Global]' <<'CASE'
module Stores:
    global mutable arena: Arena = zeroed
def grow(out: mutable darray[i32]&) -> void:
    can Global.Read:
        in Stores::arena:
            out.push(1)
CASE
run_case qualified_global_arena_granted clean <<'CASE'
# nopath
module Stores:
    global mutable arena: Arena = zeroed
def grow(out: mutable darray[i32]&) -> void:
    can Global{Read,Write}:
        in Stores::arena:
            out.push(1)
CASE
run_case aliased_global_arena 'mutable global write requires can[Global]' <<'CASE'
module Stores:
    global mutable arena: Arena = zeroed
using Stores as Storage
def grow(out: mutable darray[i32]&) -> void:
    can Global.Read:
        in Storage::arena:
            out.push(1)
CASE
run_case scoped_alias_wrong_member 'mutable global write requires can[Global]' <<'CASE'
global mutable hot: i64 = 0
module ReadOnly:
    alias Access = Global.Read
    def wrong() -> void:
        can Access:
            hot <- 1
module Writable:
    alias Access = Global.Write
CASE
run_case scoped_alias_read clean <<'CASE'
global mutable hot: i64 = 0
module ReadOnly:
    alias Access = Global.Read
    def read() -> i64:
        can Access:
            return hot
module Writable:
    alias Access = Global.Write
CASE
run_case grouped_alias_members clean <<'CASE'
global mutable hot: i64 = 0
alias Access = Global{Read,Write}
def update() -> i64:
    can Access:
        hot <- hot + 1
        return hot
CASE
run_case qualified_callback_leaf_collision 'variable "callback" expects' <<'CASE'
global mutable hot: i64 = 0
module Effectful:
    def reader() -> i64:
        return hot can Global.Read
module Pure:
    def reader() -> i64:
        return 0
def main() -> i64:
    callback: fn() -> i64 = Effectful::reader
    return 0
CASE
run_case pure_callback_leaf_collision clean <<'CASE'
global mutable hot: i64 = 0
module Effectful:
    def reader() -> i64:
        return hot can Global.Read
module Pure:
    def reader() -> i64:
        return 0
def main() -> i64:
    callback: fn() -> i64 = Pure::reader
    return 0
CASE
run_case callback_read_before_local_declaration 'variable "callback" expects' <<'CASE'
global mutable hot: i64 = 0
def reader() -> i64:
    return hot can Global.Read
def main() -> i64:
    callback: fn() -> i64 = reader
    reader: i64 = 0
    return reader
CASE
run_case grouped_multifamily_inline clean <<'CASE'
global mutable hot: i64 = 0
def reader() -> i64:
    return hot can Global{Read,Write}, Memory.Allocate
def main() -> i64:
    return reader() can Global{Read,Write}, Memory.Allocate
CASE
run_case grouped_multiple_aliases clean <<'CASE'
global mutable hot: i64 = 0
alias ReadState = Global.Read
alias WriteState = Global.Write
alias Storage = Memory.Allocate
def reader() -> i64:
    return hot can ReadState, WriteState, Storage
def main() -> i64:
    return reader() can ReadState, WriteState, Storage
CASE
run_case scoped_nested_alias_body_wrong_member 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 0
module Readers:
    alias Member = Global.Read
    alias Access = Member
module Writers:
    alias Member = Global.Write
    def main() -> void:
        can Readers::Access:
            hot <- 1
CASE
run_case returned_callback_keeps_actual_write 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 0
def writer() -> i64:
    can Global.Write:
        hot <- 1
    return 1
def factory() -> fn() -> i64 can[Global.Read]:
    return writer
def main() -> i64:
    callback = factory()
    return callback() can Global.Read
CASE
run_case returned_callback_granted clean <<'CASE'
global mutable hot: i64 = 0
def writer() -> i64:
    can Global.Write:
        hot <- 1
    return 1
def factory() -> fn() -> i64 can[Global.Read]:
    return writer
def main() -> i64:
    callback = factory()
    return callback() can Global{Read,Write}
CASE
run_case callback_factory_creation_pure clean <<'CASE'
global mutable hot: i64 = 0
def writer() -> i64:
    can Global.Write:
        hot <- 1
    return 1
def factory() -> fn() -> i64 can[Global.Read]:
    return writer
def main() -> i64:
    callback = factory()
    return 0
CASE
run_case transitive_callback_factory_keeps_actual_write 'requires can[Global]' <<'CASE'
global mutable hot: i64 = 0
def writer() -> i64:
    can Global.Write:
        hot <- 1
    return 1
def factory() -> fn() -> i64 can[Global.Read]:
    return writer
def relay() -> fn() -> i64 can[Global.Read]:
    return factory()
def main() -> i64:
    callback = relay()
    return callback() can Global.Read
CASE
run_case returned_callback_keeps_actual_unsafe 'requires can[Unsafe]' <<'CASE'
# unsafe
def forge() -> i64:
    return 1 can Unsafe.PointerCast
def factory() -> fn() -> i64 can[Unsafe.UncheckedIndex]:
    return forge
def main() -> i64:
    callback = factory()
    return callback() can Unsafe.UncheckedIndex
CASE
run_case returned_callback_unsafe_granted clean <<'CASE'
# unsafe
def forge() -> i64:
    return 1 can Unsafe.PointerCast
def factory() -> fn() -> i64 can[Unsafe.UncheckedIndex]:
    return forge
def main() -> i64:
    callback = factory()
    return callback() can Unsafe{UncheckedIndex,PointerCast}
CASE
run_case unsafe_callback_factory_creation_pure clean <<'CASE'
# unsafe
def forge() -> i64:
    return 1 can Unsafe.PointerCast
def factory() -> fn() -> i64 can[Unsafe.UncheckedIndex]:
    return forge
def main() -> i64:
    callback = factory()
    return 0
CASE
[ "$failed" -eq 0 ] || exit 1
echo "mutable global authority smoke OK: $cases cases" >&2
