# Scope smoke — BINDINGS and BLOCKS: an or-chain whose alternatives bind the same name at
# different payload slots, a declaration that must not outlive its block, a value block's
# trailing expression, and match ALTERNATION arms. These are the gaps gen2 found by trying to
# compile the compiler; none of them is visible by inspection, because every program here
# compiles clean and then returns the wrong answer.


# 1. An or-chain whose alternatives bind the SAME name at DIFFERENT payload slots
#    (`inner` is slot 1 in Tag, slot 0 in Wrap), so reading the wrong slot is visible.
#    The FIRST alternative matches, so the second's test never runs.
differential or_bind_first_alternative "$(cat <<'EOF'
module Ast:
    enum Node layout(handle: u32):
        pass

    enum Expr is Node:
        Leaf(value: i64)
        Tag(label: i64, inner: Expr)
        Wrap(inner: Expr)


using Ast


def unwrap(node: Expr) -> i64:
    if node is Expr.Tag(label, inner) or node is Expr.Wrap(inner):
        if inner is Expr.Leaf(value):
            return value
        return -1
    return -2


def build_tag() -> Expr:
    leaf: Expr = Expr.Leaf(7)
    return (Expr.Tag(3, leaf))


def main() -> i64:
    return unwrap(build_tag())
EOF
)" 7

# 2. The SECOND alternative matches — the mirror case, so a fix that simply always reads
#    the first alternative's slot fails here.
differential or_bind_second_alternative "$(cat <<'EOF'
module Ast:
    enum Node layout(handle: u32):
        pass

    enum Expr is Node:
        Leaf(value: i64)
        Tag(label: i64, inner: Expr)
        Wrap(inner: Expr)


using Ast


def unwrap(node: Expr) -> i64:
    if node is Expr.Tag(label, inner) or node is Expr.Wrap(inner):
        if inner is Expr.Leaf(value):
            return value
        return -1
    return -2


def build_wrap() -> Expr:
    leaf: Expr = Expr.Leaf(9)
    return (Expr.Wrap(leaf))


def main() -> i64:
    return unwrap(build_wrap())
EOF
)" 9

# 3. A block-local declaration must not outlive its block: the trailing `return outer`
#    is emitted AFTER the branch's shadowing declaration, so a flat scope resolves it to
#    the branch's slot. main() takes the path that never entered the branch.
differential sibling_block_shadow "$(cat <<'EOF'
def pick(n: i64) -> i64:
    outer: i64 = 33
    if n > 0:
        outer: i64 = 11
        return outer
    return outer


def main() -> i64:
    return pick(0)
EOF
)" 33

# 4. The shadowed branch still has to work when it IS taken.
differential sibling_block_shadow_taken "$(cat <<'EOF'
def pick(n: i64) -> i64:
    outer: i64 = 33
    if n > 0:
        outer: i64 = 11
        return outer
    return outer


def main() -> i64:
    return pick(1)
EOF
)" 11

# 5. A VALUE block's trailing expression is still INSIDE the block, so it must see the
#    block's own locals. This is the case that must NOT be scoped away — getting it wrong
#    makes the compiler decline the function rather than miscompile it.
differential block_value_sees_block_locals "$(cat <<'EOF'
def compute(n: i64) -> i64:
    scale: mutable i64 = n
    total: i64 = |scale|
        doubled: i64 = scale * 2
        doubled + 1
    return total


def main() -> i64:
    return compute(20)
EOF
)" 41

# 6. An alternation arm over an sview scrutinee. `width("i16")` takes the second arm's
#    SECOND option and `width("u8")` the first arm's first, so an implementation that only
#    ever compares one option per arm fails.
differential match_alternation_arms "$(cat <<'EOF'
def width(type_name: sview) -> i64:
    return match type_name:
        "u8" | "i8" | "bool": 1
        "u16" | "i16": 2
        "u32" | "i32": 4
        _: 8


def main() -> i64:
    return width("i16") * 10 + width("u8")
EOF
)" 21

# 7. The alternation fall-through: nothing matches, so the catch-all arm has to win.
differential match_alternation_default "$(cat <<'EOF'
def width(type_name: sview) -> i64:
    return match type_name:
        "u8" | "i8" | "bool": 1
        "u16" | "i16": 2
        _: 8


def main() -> i64:
    return width("f64")
EOF
)" 8
