run_case inline_span_direct_positive clean <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    return hot can Global.Read
CASE
run_case inline_span_direct_sibling_negative 'accesses a global mutable binding without Global.Read' <<'CASE'
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
run_case grouped_signature_only 'accesses a global mutable binding without Global.Write' <<'CASE'
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
run_case direct_read 'accesses a global mutable binding without Global.Read' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    return hot
CASE
run_case direct_write 'accesses a global mutable binding without Global.Write' <<'CASE'
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
run_case wrong_member 'accesses a global mutable binding without Global.Write' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read:
        hot <- 2
    return 0
CASE
run_case compound_read 'accesses a global mutable binding without Global.Read' <<'CASE'
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
run_case immutable_global_mutable_field_read 'accesses a global mutable binding without Global.Read' <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    return state.value
CASE
run_case immutable_global_mutable_field_read_granted clean <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    can Global.Read:
        return state.value
CASE
run_case immutable_global_field_uses_declaration_scope 'accesses a global mutable binding without Global.Read' <<'CASE'
module Owner:
    public:
        struct State:
            value: mutable i64
        global state: State = State{value: 1}
module Consumer:
    struct State:
        value: i64
    def read() -> i64:
        return Owner::state.value
CASE
run_case immutable_global_readonly_alias_field clean <<'CASE'
type Scalar = i64
struct State:
    value: Scalar
global state: State = State{value: 1}
def main() -> i64:
    return state.value
CASE
run_case immutable_global_mutable_field_write 'accesses a global mutable binding without Global.Write' <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    state.value <- 2
    return 0
CASE
run_case immutable_global_mutable_field_write_granted clean <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    can Global.Write:
        state.value <- 2
    return 0
CASE
run_case immutable_global_mutable_field_compound_write_only 'accesses a global mutable binding without Global.Read' <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    can Global.Write:
        state.value += 2
    return 0
CASE
run_case immutable_global_mutable_field_compound_read_only 'accesses a global mutable binding without Global.Write' <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    can Global.Read:
        state.value += 2
    return 0
CASE
run_case immutable_global_mutable_field_compound_both_grants clean <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    can Global{Read,Write}:
        state.value += 2
    return 0
CASE
run_case immutable_global_nested_mutable_field_compound_write_only 'accesses a global mutable binding without Global.Read' <<'CASE'
struct Inner:
    value: mutable i64
struct State:
    inner: Inner
global state: State = State{inner: Inner{value: 1}}
def main() -> i64:
    can Global.Write:
        state.inner.value += 2
    return 0
CASE
run_case immutable_global_parenthesized_mutable_field_read_missing 'accesses a global mutable binding without Global.Read' <<'CASE'
struct State:
    value: (mutable i64)
global state: State = State{value: 1}
def main() -> i64:
    return state.value
CASE
run_case immutable_global_parenthesized_mutable_field_read_granted clean <<'CASE'
struct State:
    value: (mutable i64)
global state: State = State{value: 1}
def main() -> i64:
    can Global.Read:
        return state.value
CASE
run_case immutable_global_parenthesized_mutable_field_write_missing 'accesses a global mutable binding without Global.Write' <<'CASE'
struct State:
    value: (mutable i64)
global state: State = State{value: 1}
def main() -> i64:
    state.value <- 2
    return 0
CASE
run_case immutable_global_parenthesized_mutable_field_write_granted clean <<'CASE'
struct State:
    value: (mutable i64)
global state: State = State{value: 1}
def main() -> i64:
    can Global.Write:
        state.value <- 2
    return 0
CASE
run_case immutable_global_refined_mutable_field_read_missing 'accesses a global mutable binding without Global.Read' <<'CASE'
struct State:
    value: mutable i64 where value > 0
global state: State = State{value: 1}
def main() -> i64:
    return state.value
CASE
run_case immutable_global_refined_mutable_field_read_granted clean <<'CASE'
struct State:
    value: mutable i64 where value > 0
global state: State = State{value: 1}
def main() -> i64:
    can Global.Read:
        return state.value
CASE
run_case immutable_global_refined_mutable_field_write_missing 'accesses a global mutable binding without Global.Write' <<'CASE'
struct State:
    value: mutable i64 where value > 0
global state: State = State{value: 1}
def main() -> i64:
    state.value <- 2
    return 0
CASE
run_case immutable_global_refined_mutable_field_write_granted clean <<'CASE'
struct State:
    value: mutable i64 where value > 0
global state: State = State{value: 1}
def main() -> i64:
    can Global.Write:
        state.value <- 2
    return 0
CASE
run_case immutable_global_reference_field_read_missing 'accesses a global mutable binding without Global.Read' <<'CASE'
struct Cell:
    value: mutable i64
struct Holder:
    alias: mutable Cell&
global mutable cell: Cell = Cell{value: 1}
global holder: Holder = Holder{alias: &cell}
def main() -> i64:
    can Global.Write:
        holder.alias.value <- 2
    return 0
CASE
