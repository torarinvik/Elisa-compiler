# Scope smoke — FUNCTION types, packed matches and COMPREHENSIONS: a `fn` type alias cast and
# called, `fn` refs in struct fields, matching a packed AST through a struct field, brace-set
# membership, sview comprehensions, and the loop accumulators they are built from.


# `sb.extend([0.u8()])` — a LITERAL source (no address to take, so both existing loop paths
# declined on darray_address_of_expr) and `extend` in VALUE position (`return sb.extend(…)`,
# which mutates in place and yields the target). Checks the appended BYTES and the resulting
# count, so a push that drops or duplicates an element fails rather than merely compiling.
differential extend_with_literal_source "$(cat <<'EOF'
def add_two(sb: mutable darray[u8]&) -> void:
    can Memory.Allocate, Abort.Panic:
        sb.extend([7.u8(), 9.u8()])


def add_via_arena(a: mutable Arena&, sb: mutable darray[u8, shape_in]&) -> mutable darray[u8, shape_out]&:
    can Memory.Allocate, Abort.Panic:
        in a:
            return sb.extend([5.u8()])


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[u8] = [1.u8()]
        add_two(&xs)
        total: mutable i64 = 0
        for b in xs |total|:
            total <- total + b.i64()
        return total + xs.count.i64() * 8 + 1
EOF
)" 42

# A fn TYPE reached three ways that all previously failed, because looks_like_lambda only
# treats `fn(A) -> R` (arrow, no `:`/`=>` body) as a TYPE inside a type annotation, and neither
# a `type X = …` RHS nor a `[...]` reinterpret bracket marked itself as one — so both parsed as
# a CALL to a function named `fn` plus a trailing binary `->`, and no Expr.Lambda ever reached
# annotation_value_type. Covers the alias spelling, `cast` to a fn type, and `call_as`.
# `call_as` is checked by RESULT, so a wrong indirect callee or arity fails rather than compiles.
differential fn_type_alias_cast_and_call_as "$(cat <<'EOF'
type Handler = fn(i64) -> i64


def double(x: i64) -> i64:
    return x * 2


def add_one(x: i64) -> i64:
    return x + 1


def through_alias_param(f: Handler, n: i64) -> i64:
    return f(n)


def through_cast(p: void&, n: i64) -> i64 can[Abort.Panic, Unsafe.PointerCast]:
    f: Handler = p.cast[Handler]
    return f(n)


def through_call_as(p: void&, n: i64) -> i64 can[Abort.Panic, Unsafe.PointerCast, Unsafe.IndirectCall]:
    trusted Unsafe.IndirectCall:
        return p.call_as[fn(i64) -> i64](n)


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast, Unsafe.IndirectCall:
        a: i64 = through_alias_param(double, 10)
        b: i64 = through_cast(double.cast[void&], 5)
        c: i64 = through_call_as(add_one.cast[void&], 11)
        return a + b + c
EOF
)" 42

# Fn TYPES with REFERENCE params/returns, held in struct FIELDS and called through them.
# Three separate gaps met here: lambda_signature_probe did not consume a bare parameter's
# postfix `&` (so `fn(Cell&) -> Cell&` was not recognized as a fn type at all); the return
# type was recorded as a head TOKEN, so `-> Cell&` resolved to the POINTEE — a wrong type
# rather than a decline, which for an indirect call is an ABI mismatch; and a struct member's
# annotation was not marked a type position, so a fn-typed field silently took the i64
# placeholder. Asserted by VALUE precisely because the return-type bug is silent.
differential fn_type_ref_params_in_struct_fields "$(cat <<'EOF'
struct Cell:
    v: mutable i64


struct Work:
    scale: i64
    op: fn(i64) -> i64
    pick: fn(Cell&) -> Cell&


def triple(x: i64) -> i64:
    return x * 3


def identity(c: Cell&) -> Cell&:
    return c


def run(w: Work&, c: Cell&) -> i64 can[Abort.Panic]:
    got: Cell& = w.pick(c)
    return w.op(got.v) + w.scale


def main() -> i64:
    can Abort.Panic:
        c: mutable Cell = Cell{v: 12}
        w: Work = Work{scale: 6, op: triple, pick: identity}
        return run(&w, &c)
EOF
)" 42

differential static_storage_qualifier "$(cat <<'ELISAEOF'
def from_static(value: static u8&) -> u8&:
    return value.cast[u8&]


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        text: static u8& = "*"
        a: u8& = from_static(text)
        return a.i64()
ELISAEOF
)" 42

# `match` on a packed-AST node reached through a struct FIELD. The hidden AST-store parameter
# was decided from the DIRECT parameter types only, so a function touching AST nodes only via a
# struct parameter got no store: runtime.active_store_enum stayed -1 and the match declined.
# `via_local` (an AST node passed directly) is the control — it always worked, and adding an
# unused AST parameter to `via_field` also made it compile, which is how the STORE rather than
# the type was identified as the gate. Asserted by value: both arms must contribute.
differential match_packed_ast_through_struct_field "$(cat <<'ELISAEOF'
module Ast:
    enum Node layout(handle: u32):
        pass

    enum Decl is Node:
        Enum(name: sview, count: i64)
        Other(x: i64)

    struct Holder:
        d: Decl
        tag: i64


using Ast


def via_field(h: Ast::Holder&) -> i64:
    can Memory.Allocate, Abort.Panic:
        match h.d:
            Ast::Decl.Enum(name, count):
                return count
            _:
                return 0


def via_local(d: Ast::Decl) -> i64:
    can Memory.Allocate, Abort.Panic:
        match d:
            Ast::Decl.Enum(name, count):
                return count
            _:
                return 0


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        d: Ast::Decl = (Ast::Decl.Enum("E", 21))
        h: Ast::Holder = Ast::Holder{d: d, tag: 0}
        return via_field(&h) + via_local(d)
ELISAEOF
)" 42

# `x in {A, B, C}` — membership over a BRACE SET. The OR-chain lowering existed but matched
# only an ARRAY literal (Expr.Array); the brace form is Expr.SetLit, so every such test
# declined. The semantic layer uses the brace form heavily
# (`operator in {TokenKind.EqEq, TokenKind.BangEq, …}`). `by_or` is the control: the same
# predicate spelled as an explicit or-chain, so the two must agree, and a member that is NOT
# in the set must yield false.
differential membership_over_brace_set "$(cat <<'ELISAEOF'
enum Kind:
    A
    B
    C
    D


def in_set(k: Kind) -> i64:
    can Abort.Panic:
        return 1 if k in {Kind.A, Kind.B, Kind.C} else 0


def by_or(k: Kind) -> i64:
    can Abort.Panic:
        return 1 if k == Kind.A or k == Kind.B or k == Kind.C else 0


def main() -> i64:
    can Abort.Panic:
        hits: mutable i64 = 0
        hits <- hits + in_set(Kind.A) * 10
        hits <- hits + in_set(Kind.D) * 100
        hits <- hits + by_or(Kind.B) * 30
        hits <- hits + in_set(Kind.C) * 2
        return hits
ELISAEOF
)" 42

# `[c for c in s]` — a list comprehension over an SVIEW (not a range, not a darray).
# The semantic layer's sview_equal collects bytes this way. Checks the COUNT and the
# byte VALUES, so a lowering that walked the wrong length or loaded the wrong stride
# gives a different ANSWER rather than merely compiling.
differential sview_comprehension "$(cat <<'ELISAEOF'
def count_bytes(a: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    bs: darray[u8] = [c for c in a]
    return bs.count.i64()


def sum_bytes(a: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    bs: darray[u8] = [c for c in a]
    t: mutable i64 = 0
    i: mutable usize = 0
    while i < bs.count:
        t <- t + bs[i].i64()
        i <- i + 1
    return t


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return count_bytes("hello") * 20 + sum_bytes("abc") - 194
ELISAEOF
)" 200

# `name in {"i8", "u8", ...}` — set membership over STRING candidates, the shape the
# semantic layer's type predicates (is_primitive_type, literal_fits_in_type) all use.
# Checks hits AND misses, and a near-miss ("i3", a prefix of a member) so a length-blind
# comparison fails.
#
# LIMIT, on purpose: every probe here is a literal, and identical literals may be merged to
# one global, so this case can NOT distinguish a content comparison from a pointer one.
# Building a pointer-distinct sview needs string_view_slice, which lives in std source these
# self-contained fixtures do not include. The discriminating check is the parse_report
# differential against stage0.
differential sview_set_membership "$(cat <<'ELISAEOF'
def is_prim(name: sview) -> bool:
    can Abort.Panic:
        return name in {"i8", "i16", "i32", "bool", "sview"}


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        hits: mutable i64 = 0
        hits <- hits + 1 if is_prim("i8") else hits
        hits <- hits + 10 if is_prim("i32") else hits
        hits <- hits + 100 if is_prim("nope") else hits
        hits <- hits + 1000 if is_prim("sview") else hits
        hits <- hits + 10000 if is_prim("i3") else hits
        return hits
ELISAEOF
)" 243   # 1011 truncated mod 256 by the exit code

# `dst.extend([x for x in src])` — extend from a COMPREHENSION. The source is a value with
# no address, and the extend loop re-emits its source once per element as `src[i]`, so a
# lowering that passed the comprehension through unchanged would rebuild the list every
# iteration. This case makes that visible as a WRONG ANSWER rather than just slow code: the
# comprehension filters, so a per-iteration rebuild changes which elements land where.
differential extend_from_comprehension "$(cat <<'ELISAEOF'
def add_evens(dst: mutable darray[i64]&, src: darray[i64]) -> void can[Memory.Allocate, Abort.Panic]:
    dst.extend([x for x in src if x % 2 == 0])


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        src: mutable darray[i64] = []
        i: mutable i64 = 1
        while i <= 6:
            src.push(i)
            i <- i + 1
        out: mutable darray[i64] = []
        out.push(99)
        add_evens(out, src)
        total: mutable i64 = 0
        j: mutable usize = 0
        while j < out.count:
            total <- total + out[j]
            j <- j + 1
        return out.count.i64() * 10 + total
ELISAEOF
)" 151   # 4 elements (99,2,4,6): 4*10 + (99+2+4+6) = 151

# `for x in xs |acc| -> acc:` — a capture-listed accumulator loop whose body ALSO restates
# the accumulator as a bare-ident statement (and does so per match arm, which is how the
# semantic layer's validate_struct_layouts_range threads its table). The capture mutates in
# place, so both the loop's `-> acc` and the per-branch restatements are no-op annotations.
#
# The value is accumulated across iterations AND a branch is taken per element, so a lowering
# that dropped the body, or ran it once, gives a different ANSWER rather than failing to
# build. Note the sibling form `|n = 0| -> n + x` genuinely threads a value between
# iterations and must keep DECLINING — stage0 gives it a shadowing loop-local, which stage1
# does not model, so accepting it would be a silent wrong answer.
differential accumulator_for_loop "$(cat <<'ELISAEOF'
def score(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    acc: mutable i64 = 0
    for x in xs |acc| -> acc:
        if x % 2 == 0:
            acc <- acc + x
            acc
        else:
            acc <- acc + 100
            acc
    return acc


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(2)
        xs.push(3)
        xs.push(4)
        return score(xs)
ELISAEOF
)" 106   # 2 + 100 + 4

# `match s: "": …` — an EMPTY-STRING pattern on an sview scrutinee. The pattern decoder
# rejected a zero-length span as undecodable, so every function with such an arm was
# dropped. Checks the empty case hits AND that a non-empty scrutinee falls to the default,
# so a decoder that produced a match-anything pattern would fail too. The nested arm also
# pins that an inner sview match inside another match arm works.
differential empty_string_pattern "$(cat <<'ELISAEOF'
def pick(a: sview, b: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    n: mutable i64 = 0
    match a:
        "x":
            match b:
                "":
                    n <- 1
                _:
                    n <- 2
        _:
            n <- 3
    return n


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return pick("x", "") * 100 + pick("x", "q") * 10 + pick("z", "")
ELISAEOF
)" 123

# `for x in xs |n = 0|:` — an INITIALIZED capture. stage0 gives it a SHADOWING loop-local,
# so the OUTER `n` of the same name is untouched after the loop. This case exists because
# getting it wrong is SILENT: emitting the accumulator decl into the enclosing scope makes
# the loop mutate the caller's variable and the function returns the accumulated value
# instead of the original. Measured before the fix: 4 where stage0 gives 100.
#
# The second half pins the OPPOSITE direction — an UNINITIALIZED capture (`|acc|`) names an
# existing outer local and MUST mutate it in place, so over-scoping would break it too. A
# lowering that scoped both, or neither, fails one half of this case.
differential loop_accumulator_scoping "$(cat <<'ELISAEOF'
def shadowed(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    n: mutable i64 = 100
    for x in xs |n = 0|:
        n <- n + x
    return n


def in_place(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    acc: mutable i64 = 0
    for x in xs |acc| -> acc:
        acc <- acc + x
        acc
    return acc


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(4)
        xs.push(5)
        return shadowed(xs) + in_place(xs)
ELISAEOF
)" 109   # shadowed keeps 100, in_place accumulates 9
