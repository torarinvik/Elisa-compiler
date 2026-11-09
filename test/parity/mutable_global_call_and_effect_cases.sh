run_case explicit_global_arena 'accesses a global mutable binding without Global.Write' <<'CASE'
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
run_case wrapped_inferred_ref 'accesses a global mutable binding without Global.Write' <<'CASE'
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
run_case writable_cast 'accesses a global mutable binding without Global.Write' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read, Unsafe.PointerCast:
        reference: mutable i64& = (&hot).cast[mutable i64&]
        reference <- 2
    return 0
CASE
run_case default_reader 'accesses a global mutable binding without Global.Read' <<'CASE'
global mutable hot: i64 = 1
def reader(value: i64 = hot) -> i64:
    return value
def main() -> i64:
    return reader()
CASE
run_case collection_mutation 'accesses a global mutable binding without Global.Write' <<'CASE'
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
run_case qualified_global_arena 'accesses a global mutable binding without Global.Write' <<'CASE'
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
run_case aliased_global_arena 'accesses a global mutable binding without Global.Write' <<'CASE'
module Stores:
    global mutable arena: Arena = zeroed
using Stores as Storage
def grow(out: mutable darray[i32]&) -> void:
    can Global.Read:
        in Storage::arena:
            out.push(1)
CASE
run_case scoped_alias_wrong_member 'accesses a global mutable binding without Global.Write' <<'CASE'
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
run_case scoped_nested_alias_body_wrong_member 'accesses a global mutable binding without Global.Write' <<'CASE'
global mutable hot: i64 = 0
module Writers:
    alias Member = Global.Read
    alias Access = Member
    def bad() -> void:
        can Access:
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
