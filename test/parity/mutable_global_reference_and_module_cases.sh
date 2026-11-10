run_case immutable_global_reference_field_write_missing 'accesses a global mutable binding without Global.Write' <<'CASE'
struct Cell:
    value: mutable i64
struct Holder:
    alias: mutable Cell&
global mutable cell: Cell = Cell{value: 1}
global holder: Holder = Holder{alias: &cell}
def main() -> i64:
    can Global.Read:
        holder.alias.value <- 2
    return 0
CASE
run_case immutable_global_reference_field_granted clean <<'CASE'
struct Cell:
    value: mutable i64
struct Holder:
    alias: mutable Cell&
global mutable cell: Cell = Cell{value: 1}
global holder: Holder = Holder{alias: &cell}
def main() -> i64:
    can Global{Read,Write}:
        holder.alias.value <- 2
    return 0
CASE
run_case cross_module_reference_field_uses_declaration_scope 'accesses a global mutable binding without Global.Write' <<'CASE'
module Model:
    public:
        struct Cell:
            value: mutable i64
        struct Holder:
            alias: mutable Cell&
        global mutable cell: Cell = Cell{value: 1}
module Owner:
    public:
        struct Cell:
            value: i64
        global holder: Model::Holder = Model::Holder{alias: &Model::cell}
module Consumer:
    struct Cell:
        value: i64
    def write() -> void:
        can Global.Read:
            Owner::holder.alias.value <- 2
CASE
run_case inferred_cross_module_reference_field_local_missing 'accesses a global mutable binding without Global.Write' <<'CASE'
module Model:
    public:
        struct Cell:
            value: mutable i64
        type LocalCell = mutable Cell&
        struct Holder:
            alias: LocalCell
        global mutable cell: Cell = Cell{value: 1}
module Owner:
    public:
        type LocalCell = i64
        global holder: Model::Holder = Model::Holder{alias: &Model::cell}
module Consumer:
    type LocalCell = i64
    def write() -> void:
        can Global.Read:
            alias = Owner::holder.alias
            alias.value <- 2
CASE
run_case inferred_cross_module_reference_field_local_granted clean <<'CASE'
module Model:
    public:
        struct Cell:
            value: mutable i64
        type LocalCell = mutable Cell&
        struct Holder:
            alias: LocalCell
        global mutable cell: Cell = Cell{value: 1}
module Owner:
    public:
        type LocalCell = i64
        global holder: Model::Holder = Model::Holder{alias: &Model::cell}
module Consumer:
    type LocalCell = i64
    def write() -> void:
        can Global{Read,Write}:
            alias = Owner::holder.alias
            alias.value <- 2
CASE
run_case inferred_cross_module_call_reference_local_missing 'accesses a global mutable binding without Global.Write' <<'CASE'
module Model:
    public:
        struct Cell:
            value: mutable i64
        type CellRef = mutable Cell&
        global mutable cell: Cell = Cell{value: 1}
        def get_ref() -> CellRef:
            can Global{Read,Write}:
                return &cell
module Consumer:
    type CellRef = i64
    def write() -> void:
        alias = Model::get_ref() can Global{Read,Write}
        can Global.Read:
            alias.value <- 2
CASE
run_case inferred_cross_module_call_reference_local_granted clean <<'CASE'
module Model:
    public:
        struct Cell:
            value: mutable i64
        type CellRef = mutable Cell&
        global mutable cell: Cell = Cell{value: 1}
        def get_ref() -> CellRef:
            can Global{Read,Write}:
                return &cell
module Consumer:
    type CellRef = i64
    def write() -> void:
        alias = Model::get_ref() can Global{Read,Write}
        can Global{Read,Write}:
            alias.value <- 2
CASE
run_case immutable_global_mutable_field_local_alias_write_missing 'accesses a global mutable binding without Global.Write' <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    can Global.Read:
        reference: mutable i64& = &state.value
        reference <- 2
    return 0
CASE
run_case immutable_global_mutable_field_local_alias_read_missing 'accesses a global mutable binding without Global.Read' <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    can Global.Write:
        reference: mutable i64& = &state.value
        reference <- 2
    return 0
CASE
run_case immutable_global_mutable_field_local_alias_granted clean <<'CASE'
struct State:
    value: mutable i64
global state: State = State{value: 1}
def main() -> i64:
    can Global{Read,Write}:
        reference: mutable i64& = &state.value
        reference <- 2
    return 0
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
run_case initializer_before_binding 'accesses a global mutable binding without Global.Read' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    hot: i64 = hot
    return hot
CASE
run_case shadow_scope_exit 'accesses a global mutable binding without Global.Read' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    block:
        hot: i64 = 2
    return hot
CASE
run_case qualified_read 'accesses a global mutable binding without Global.Read' <<'CASE'
module Box:
    public:
        global mutable hot: i64 = 1
def main() -> i64:
    return Box::hot
CASE
run_case cast_function_addresses_do_not_alias_globals clean <<'CASE'
module Workers:
    public:
        def work(arg: mutable void&?) -> mutable void&?:
            return arg
using Workers::work
def main() -> i64:
    can Unsafe.PointerCast:
        direct: void& = work.cast[void&]
        qualified: void&? = Workers::work.cast[void&?]
        return 1 if direct == qualified and qualified != null else 0
CASE
run_case imported_read 'accesses a global mutable binding without Global.Read' <<'CASE'
module Box:
    public:
        global mutable hot: i64 = 1
using Box::hot
def main() -> i64:
    return hot
CASE
run_case alias_read 'accesses a global mutable binding without Global.Read' <<'CASE'
module Box:
    public:
        global mutable hot: i64 = 1
using Box as B
def main() -> i64:
    return B::hot
CASE
run_case alias_target_concrete_before_alias 'accesses a global mutable binding without Global.Read' <<'CASE'
module A:
    public:
        module Foo:
            public:
                module Bar:
                    public:
                        global mutable hot: i64 = 1
module Other:
    public:
        module Foo:
            public:
                module Bar:
                    public:
                        global mutable cold: i64 = 2
using Other as A
using A::Foo as F
def main() -> i64:
    return F::Bar::hot
CASE
run_case chained_alias_read 'accesses a global mutable binding without Global.Read' <<'CASE'
module Outer:
    module Inner:
        public:
            global mutable hot: i64 = 1
using Outer as First
using First as Second
def main() -> i64:
    return Second::Inner::hot
CASE
run_case chained_alias_from_import 'accesses a global mutable binding without Global.Read' <<'CASE'
module Outer:
    module Inner:
        public:
            global mutable hot: i64 = 1
using Outer as First
using First as Second
from Second::Inner import hot
def main() -> i64:
    return hot
CASE
run_case chained_alias_wildcard_import 'accesses a global mutable binding without Global.Read' <<'CASE'
module Outer:
    public:
        global mutable hot: i64 = 1
using Outer as First
using First as Second
using Second
def main() -> i64:
    return hot
CASE
run_case index_read 'accesses a global mutable binding without Global.Read' <<'CASE'
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
run_case trusted_firewall 'accesses a global mutable binding without Global.Read' <<'CASE'
global mutable hot: i64 = 1
def reader() -> i64:
    trusted Global.Read:
        return hot
def main() -> i64:
    return reader()
CASE
run_case empty_trusted 'accesses a global mutable binding without Global.Read' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    trusted:
        return hot
CASE
run_case bracketed_wrong_member 'accesses a global mutable binding without Global.Write' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    trusted [Global.Read]:
        hot <- 2
    return 0
CASE
run_case signature_is_not_local_authority 'accesses a global mutable binding without Global.Read' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64 can[Global.Read]:
    return hot
CASE
run_case mutable_reference 'accesses a global mutable binding without Global.Write' <<'CASE'
global mutable hot: i64 = 1
def main() -> i64:
    can Global.Read:
        reference: mutable i64& = &hot
        reference <- 2
    return 0
CASE
run_case mutable_argument 'accesses a global mutable binding without Global.Write' <<'CASE'
global mutable hot: i64 = 1
def update(value: mutable i64&) -> void:
    value <- 2
def main() -> i64:
    can Global.Read:
        update(&hot)
    return 0
CASE
run_case inferred_alias 'accesses a global mutable binding without Global.Write' <<'CASE'
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
run_case mutable_ref_return 'accesses a global mutable binding without Global.Write' <<'CASE'
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
run_case nested_module_import 'accesses a global mutable binding without Global.Read' <<'CASE'
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
run_case nested_module_qualified 'accesses a global mutable binding without Global.Read' <<'CASE'
module Box:
    public:
        module Inner:
            public:
                global mutable hot: i64 = 1
def main() -> i64:
    return Box::Inner::hot
CASE
run_case verbatim_module_qualified 'accesses a global mutable binding without Global.Read' <<'CASE'
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
