# Scope smoke — BINDINGS and BLOCKS: an or-chain whose alternatives bind the same name at
# different payload slots, a declaration that must not outlive its block, a value block's
# trailing expression, match ALTERNATION arms, and a `while` loop expression's yield. These are the gaps gen2 found by trying to
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

# 8. A `while` loop expression yields its header accumulator exactly as a `for` does: in tail
#    position, bound to a name, as a value block's tail, past an early `return`, with captured
#    outer mutables beside the declared counter (repo-health rh_pylock's shape), and when it
#    yields a second accumulator rather than the counter. 77 = every check agreed; anything
#    else is the bitmask of the checks that failed.
differential while_loop_expression_yields "$(cat <<'EOF'
def count_to(n: usize) -> usize:
    while i < n |i: usize = 0| -> i:
        i <- i + 1


def count_bound(n: usize) -> usize:
    x: usize = while i < n |i: usize = 0| -> i:
        i <- i + 1
    x


def in_block(n: usize) -> usize:
    y: usize =
        base: usize = 10
        while i < n |i: usize = base| -> i:
            i <- i + 1
    y


def first_negative(values: i64[3]) -> usize:
    while i < 3 |i: usize = 0| -> i:
        return i if values[i] < 0
        i <- i + 1


def scan_end(data: i64[4], start: usize, end: usize) -> usize:
    limit: mutable usize = end
    quote: mutable i64 = 0
    while i < limit |i: usize = start, limit, quote| -> i:
        return i if data[i] == 35 and quote == 0
        quote <- data[i] if data[i] == 34 and quote == 0
        i <- i + 1


def sum_while(values: i64[3]) -> i64:
    while i < 3 |i: usize = 0, sum: i64 = 0| -> sum:
        sum <- sum + values[i]
        i <- i + 1


def for_count(n: usize) -> usize:
    for k in 0..<n |c: usize = 0| -> c:
        c <- c + 1


def main() -> i64:
    fails: mutable i64 = 0
    fails <- fails + 1 if count_to(5) != 5 or count_to(5) != for_count(5)
    fails <- fails + 2 if count_bound(7) != 7
    fails <- fails + 4 if in_block(13) != 13
    negative: i64[3] = [1, -1, 3]
    positive: i64[3] = [1, 2, 3]
    fails <- fails + 8 if first_negative(negative) != 1 or first_negative(positive) != 3
    hash: i64[4] = [1, 35, 2, 3]
    plain: i64[4] = [1, 2, 3, 4]
    fails <- fails + 16 if scan_end(hash, 0, 4) != 1 or scan_end(plain, 0, 4) != 4 or scan_end(plain, 3, 2) != 3
    fails <- fails + 32 if sum_while(positive) != 6
    return 77 if fails == 0 else fails
EOF
)" 77

# 36. An `is` binding in a VALUE-position `if` condition, read by a later `and` conjunct and
#     by the true value. This is the shape of codegen_target_machine's
#     `2 if getenv(…) is pic and pic.cast[cstr] == "1" else 0`. stage1's resolver walked a
#     ternary condition as one plain expression, so the conjunct reported `undefined
#     identifier "pic"`, and stage1 could not compile its own compiler. stage0 scopes it
#     like an `if` statement (analyzeCondExpr). An `or` of two alternatives that each bind
#     `inner` still binds it, and each call takes a different branch, so a wrong slot or
#     a dropped conjunct changes the sum: 70 + 1 + 5 + 5 + 0 + 2 + 0 + 0.
differential ternary_condition_and_binding "$(cat <<'EOF'
enum Expr:
    Leaf(value: i64)
    Tag(label: i64, inner: i64)
    Wrap(inner: i64)


def score(node: Expr) -> i64:
    return value * 10 if node is Expr.Leaf(value) and value > 3 else 1


def either(node: Expr) -> i64:
    return inner + 3 if (node is Expr.Tag(label, inner) or node is Expr.Wrap(inner)) and inner == 2 else 0


def present(p: i64&?) -> i64:
    return 2 if p is q and q > 3 else 0


def main() -> i64:
    x: i64 = 7
    small: i64 = 1
    return score(Expr.Leaf(7)) + score(Expr.Leaf(2)) + either(Expr.Wrap(2)) + either(Expr.Tag(9, 2)) + either(Expr.Wrap(3)) + present(&x) + present(&small) + present(null)
EOF
)" 83
