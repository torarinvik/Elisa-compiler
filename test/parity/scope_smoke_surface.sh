# Scope smoke — the SURFACE FORMS: multi-target destructuring, module-qualified enum patterns
# and `is` tests, parallel assignment, tuple yields, default parameters, the `count` quantifier,
# optional matches, and named tuples in parameters and returns.


# `a, b, c =` NEWLINE INDENT `for … |accs…| -> a, b, c:` — multi-target destructuring from an
# accumulator loop. This nests TWO blocks: the indented body's tail statement is the loop's own
# header block, so the outer block's statement list is empty and its value is another Block.
# The tuple check used to see that Block and decline every such form in the semantic layer.
#
# Three accumulators of DIFFERENT types (bool, u32, i64) and each is read back, so a lowering
# that bound them in the wrong order or dropped one changes the ANSWER rather than failing to
# build. The loop also filters, so the accumulation has to actually run per element.
differential multi_target_accumulator_destructuring "$(cat <<'ELISAEOF'
def scan(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    found, count, total =
        for x in xs |found = false, count: u32 = 0, total = 0| -> found, count, total:
            if x > 2:
                found <- true
                count <- count + 1
                total <- total + x
    return (1000 if found else 0) + count.i64() * 100 + total


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(1)
        xs.push(3)
        xs.push(5)
        return scan(xs)
ELISAEOF
)" 184   # 1000 + 2*100 + 8 = 1208, truncated mod 256

# `match e: M::EK.A: …` — a MODULE-QUALIFIED enum variant as a match pattern. Pattern.Variant
# carries the path as one dotted string, and the ordinal lookup compared the WHOLE prefix
# before the last dot ("M::EK") against the registered enum name ("EK"), so it never matched
# and every such arm declined. The semantic layer writes all of its Ast enum patterns this way.
# Distinct arm values per variant, so a lookup that resolved to the wrong ordinal changes the
# ANSWER rather than failing to build.
differential module_qualified_enum_pattern "$(cat <<'ELISAEOF'
module M:
    enum EK:
        A
        B
        C


def to_i(e: M::EK) -> i64:
    can Abort.Panic:
        return match e:
            M::EK.A: 7
            M::EK.B: 9
            _:       11


def main() -> i64:
    can Abort.Panic:
        return to_i(M::EK.B) * 10 + to_i(M::EK.C)
ELISAEOF
)" 101

# `e is M::EK.A` — a MODULE-QUALIFIED enum variant in an `is` test. The three `is` forms
# (payload-enum, const-enum, packed) each matched the variant head only as an Expr.Ident, but a
# qualified head parses as Expr.Scope, so all of them missed and the function declined.
# Checks both the hit and the miss.
differential module_qualified_enum_is "$(cat <<'ELISAEOF'
module M:
    enum EK:
        A
        B


def kind_is_a(e: M::EK) -> i64:
    can Abort.Panic:
        return 5 if e is M::EK.A else 3


def main() -> i64:
    can Abort.Panic:
        return kind_is_a(M::EK.A) * 10 + kind_is_a(M::EK.B)
ELISAEOF
)" 53

# `a, b <- b, a` — POSITIONAL parallel assignment, and the guarded form
# `a, b <- b, a if COND`. Two separate defects: the backend had no lowering for an Array RHS
# at all, and the trailing `if` parses as part of the LAST ELEMENT rather than guarding the
# statement, so it arrived as `[b, If(COND, a, Absent)]` — an else-less conditional value with
# no lowering, where stage0 accepts the statement.
#
# A SWAP is the case that catches evaluation order: every RHS value must be emitted before any
# store, or `first` on the right reads the value it was just overwritten with. A lowering that
# interleaved stores returns 22/44 here instead of 21/34.
differential parallel_assignment_and_guard "$(cat <<'ELISAEOF'
def order(a: i64, b: i64, do_swap: bool) -> i64:
    can Abort.Panic:
        first: mutable i64 = a
        second: mutable i64 = b
        first, second <- second, first if do_swap
        return first * 10 + second


def plain(a: i64, b: i64) -> i64:
    can Abort.Panic:
        first: mutable i64 = a
        second: mutable i64 = b
        first, second <- second, first
        return first * 10 + second


def main() -> i64:
    can Abort.Panic:
        return order(1, 2, true) + order(3, 4, false) + plain(1, 2)
ELISAEOF
)" 76   # 21 + 34 + 21

# `for x in xs |lo, hi| -> lo, hi:` — a loop header with a MULTI-name (tuple) yield in
# STATEMENT position. The yield is a no-op annotation there (captures mutate in place), but the
# guard only accepted a single capture Ident, so the tuple form declined outright — it is how
# the semantic layer's multi-accumulator walkers are written.
#
# Both captures are mutated and both are read back, so dropping either half changes the answer.
differential tuple_yield_loop_header "$(cat <<'ELISAEOF'
def walk(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    lo: mutable i64 = 100
    hi: mutable i64 = 0
    for x in xs |lo, hi| -> lo, hi:
        lo <- x if x < lo else lo
        hi <- x if x > hi else hi
    return lo * 100 + hi


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(3)
        xs.push(7)
        return walk(xs)
ELISAEOF
)" 51   # lo=3, hi=7 -> 307 truncated mod 256

# A MIXED capture header: a bare capture (`out`) plus a TYPED initialized accumulator
# (`position: usize = 0`), yielded as a tuple. The bound-name check keyed on UNTYPED VarDecls
# only, so the typed accumulator was not recognised as a name the block binds and the whole
# loop declined.
#
# Note the header must capture `out`: stage0 rejects mutating an outer binding from inside a
# value block (docs/119 E4), even through a call. The loop breaks early, so a lowering that
# mishandled the accumulator would copy the wrong number of elements.
differential typed_accumulator_capture "$(cat <<'ELISAEOF'
def fill(out: mutable darray[i64]&, xs: darray[i64], limit: usize) -> void can[Memory.Allocate, Abort.Panic]:
    for x in xs |out, position: usize = 0| -> out, position:
        break if position >= limit
        out.push(x)
        position <- position + 1


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(4)
        xs.push(5)
        xs.push(6)
        o: mutable darray[i64] = []
        fill(o, xs, 2)
        return o.count.i64() * 10 + o[1]
ELISAEOF
)" 25

# DEFAULT PARAMETERS omitted at the call site. The parser parsed the default expression and
# DISCARDED it, keeping only a has_default flag, so nothing downstream could fill an omitted
# argument and the call declined on an LLVMCountParams mismatch.
#
# Each call omits a different number of trailing arguments and the three results differ, so a
# lowering that filled the wrong value — or filled positionally out of order — changes the
# ANSWER rather than failing to build.
differential default_parameters "$(cat <<'ELISAEOF'
def scaled(base: i64, factor: i64 = 3, offset: i64 = 5) -> i64:
    return base * factor + offset


def main() -> i64:
    can Abort.Panic:
        return scaled(2) + scaled(2, 4) + scaled(2, 4, 6)
ELISAEOF
)" 38   # 11 + 13 + 14

# `count VAR in XS where COND` — a fold to an integer. The parser DROPPED the query head
# keyword from Expr.Comprehension, so the backend could not tell `count` from `sum`/`min`/`max`
# and declined rather than guess. The head is now recorded in the line-keyed side table.
#
# The count and the container length differ, so a lowering that returned the length (or
# short-circuited like `any` does) gives a different ANSWER.
differential count_quantifier "$(cat <<'ELISAEOF'
def evens(xs: darray[i64]) -> usize can[Memory.Allocate, Abort.Panic]:
    return count x in xs where x % 2 == 0


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(1)
        xs.push(2)
        xs.push(4)
        xs.push(7)
        return evens(xs).i64() * 10 + xs.count.i64()
ELISAEOF
)" 24   # 2 evens of 4 elements

# `x: T = match OPT: v: … / _: …` — an OPTIONAL scrutinee in VALUE position. A binding arm over
# an optional is a CATCH-ALL: stage0 takes it even when the optional is ABSENT, and `_` is dead.
# The slot emitter accepted only integer/penum/packed/cstr/sview scrutinees, so this declined.
#
# Both halves matter. `sel` never reads the payload, so it pins ARM SELECTION on the absent
# path (a present/absent split would score 2 there, not 1). `val` reads the payload only where
# the optional is PRESENT — deliberately, because the payload of an ABSENT optional is UNDEF in
# stage0 (`v: v + 1` yields 0 there while `v: 5` yields 5), so reading it is undefined
# behaviour and NOT a parity-testable path.
differential optional_value_match "$(cat <<'ELISAEOF'
def pick(n: i64) -> i64? can[Abort.Panic]:
    return n * 2 if n > 0 else null


def sel(n: i64) -> i64:
    can Abort.Panic:
        got: i64 = match pick(n):
            v: 1
            _: 2
        return got


def val(n: i64) -> i64:
    can Abort.Panic:
        got: i64 = match pick(n):
            v: v
            _: 9
        return got


def main() -> i64:
    can Abort.Panic:
        return sel(0) * 100 + val(3) * 10 + val(5)
ELISAEOF
)" 170   # sel(0)=1 (binding arm taken when ABSENT), val(3)=6, val(5)=10

# `phrase = EXPR` — an UNTYPED declaration by FIRST ASSIGNMENT, which stage0 accepts. stage1
# parses it as Stmt.Assign and the handler rejected `=` outright, so it declined. Declares the
# local from the value's inferred type.
#
# The initializer is a TERNARY of f-strings: a value-`if` is context-typed and has no standalone
# type, so the then-arm supplies it. Both branches are exercised and their lengths differ, so
# inferring from the wrong arm or dropping a branch changes the ANSWER.
differential untyped_decl_first_assignment "$(cat <<'ELISAEOF'
def msg(flag: bool, name: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    phrase = f" of {name}" if flag else f""
    buffer: mutable darray[u8] = []
    buffer.extend(f"x{phrase}")
    return buffer.count.i64()


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return msg(true, "ab") * 10 + msg(false, "ab")
ELISAEOF
)" 71   # "x of ab" = 7, "x" = 1

# `match s: "a" | "b":` — an ALTERNATION arm on an sview scrutinee in STATEMENT position. The
# per-arm path tested a single literal, so an OR arm fell through to the decline. Expanded into
# one single-literal arm per option, sharing the body.
#
# Every option of every arm is exercised plus a miss, weighted by position, so dropping an
# option or reordering the arms changes the ANSWER.
differential sview_alternation_statement "$(cat <<'ELISAEOF'
def kind(s: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    n: mutable i64 = 0
    match s:
        "a" | "b":
            n <- 1
        "c" | "d" | "e":
            n <- 2
        _:
            n <- 3
    return n


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return kind("a") * 1000 + kind("b") * 100 + kind("d") * 10 + kind("z")
ELISAEOF
)" 99   # 1123 truncated mod 256

# `f(a) if COND else g(b)` — a TERNARY in STATEMENT position whose arms are side-effecting
# CALLS, not values. Emitting it as a value declines (the arms are void), so it is lowered as
# an if/else running each arm as a statement. The branches append different lengths, so taking
# the wrong one — or running both — changes the ANSWER.
differential ternary_statement_calls "$(cat <<'ELISAEOF'
def build(flag: bool) -> i64 can[Memory.Allocate, Abort.Panic]:
    buffer: mutable darray[u8] = []
    buffer.extend("abcd") if flag else buffer.extend("xy")
    return buffer.count.i64()


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return build(true) * 10 + build(false)
ELISAEOF
)" 42

# TWO named-tuple parameters on ONE LINE. Tuple-type labels are keyed by LINE, so the lookup
# returned both label sets concatenated (6 labels for a 3-element tuple), the count check
# failed, the parameter type resolved Unmodeled and the whole SIGNATURE was dropped — with no
# DECLINE trace, since it is a signature failure rather than a body failure. Splitting the
# params across lines was previously the only way such a function compiled.
differential named_tuple_params_one_line "$(cat <<'ELISAEOF'
def place_of(n: i64) -> (kind: i64, base: sview, field: sview):
    can Abort.Panic:
        return (n, "b", "f") if n > 0 else (0, "", "")


def same(a: (kind: i64, base: sview, field: sview), b: (kind: i64, base: sview, field: sview)) -> bool:
    can Abort.Panic:
        return a.kind == b.kind


def use(n: i64) -> i64 can[Abort.Panic]:
    p: (kind: i64, base: sview, field: sview) = place_of(n)
    q: (kind: i64, base: sview, field: sview) = place_of(3)
    return 5 if same(p, q) else 2


def main() -> i64:
    can Abort.Panic:
        return use(3) * 10 + use(0)
ELISAEOF
)" 52

# A named-tuple PARAMETER and a named-tuple RETURN on the SAME LINE, with DIFFERENT labels
# and different arities. The label side-table is keyed by line, so this signature yields 5
# labels on one line; neither 3 nor 2 divides 5, so the identical-repeated-groups heuristic
# could not disambiguate and BOTH tuple types resolved Unmodeled — dropping the signature
# with no DECLINE trace. Each tuple now registers under its own label WINDOW (source order)
# and the annotation lookup finds the unique window that names a registered tuple.
differential named_tuple_param_and_return_one_line "$(cat <<'ELISAEOF'
def place_of(n: i64) -> (kind: i64, base: sview, field: sview) can[Abort.Panic]:
    return (n, "b", "f") if n > 0 else (0, "", "")


def assign_delta(value: i64, place: (kind: i64, base: sview, field: sview)) -> (ok: bool, delta: i64) can[Abort.Panic]:
    return (true, value + place.kind) if place.kind > 0 else (false, 0)


def use(n: i64) -> i64 can[Abort.Panic]:
    r: (ok: bool, delta: i64) = assign_delta(n, place_of(n))
    return r.delta if r.ok else 7


def main() -> i64:
    can Abort.Panic:
        return use(4) * 10 + use(0)
ELISAEOF
)" 87

# A NESTED named tuple. The parser pushes each label BEFORE parsing the element it names, so
# `(ok: bool, place: (kind: i64, base: sview), op: i64)` writes ok, place, kind, base, op —
# the inner labels sit INSIDE the outer ones. Reading a flat run of 3 labels gets
# [ok, place, kind], so the outer type resolved Unmodeled and the signature was dropped with
# no DECLINE trace. Label positions now skip each element's nested span.
differential nested_named_tuple_type "$(cat <<'ELISAEOF'
def place_of(n: i64) -> (kind: i64, base: sview):
    return (n, "b") if n > 0 else (0, "")


def match_goal(n: i64) -> (ok: bool, place: (kind: i64, base: sview), op: i64):
    return (n > 0, place_of(n), n)


def use(n: i64) -> i64 can[Abort.Panic]:
    goal: (ok: bool, place: (kind: i64, base: sview), op: i64) = match_goal(n)
    return goal.op + goal.place.kind if goal.ok else 3


def main() -> i64:
    can Abort.Panic:
        return use(4) * 10 + use(0)
ELISAEOF
)" 83

# `a, b, c = match X:` — ONE dispatch, SEVERAL outputs, each arm yielding a tuple. The
# destructuring-assign path handled `Assign(Array(targets), =, Block(...))` (a loop with a tuple
# yield) but not a MATCH on the right, so resolve_enums.elisa's check_unreachable_arms declined
# and was dropped. emit_match_into_slot now carries N parallel slots; each arm's tuple element i
# is stored into slot i. Element types come from the FIRST arm, with stage0's i64 default for a
# bare integer literal (which has no intrinsic type of its own).
differential destructure_match_scalar "$(cat <<'ELISAEOF'
def classify(n: i64) -> i64 can[Abort.Panic]:
    flag, key, weight = match n:
        0: true, 1, 7
        1: false, 2, 8
        _: false, 3, 9
    return key * 10 + weight + (100 if flag else 0)


def main() -> i64:
    can Abort.Panic:
        return classify(0) + classify(2)
ELISAEOF
)" 156

# Same form over an SVIEW scrutinee — a different arm-test path (string compare, not an integer
# switch) sharing the same N-slot arm-body emitter.
differential destructure_match_sview "$(cat <<'ELISAEOF'
def pick(name: sview) -> i64 can[Abort.Panic]:
    ok, kind, weight = match name:
        "add": true, 1, 4
        "sub": true, 2, 5
        _: false, 3, 6
    return kind * 10 + weight + (100 if ok else 0)


def main() -> i64:
    can Abort.Panic:
        return pick("sub") + pick("zz")
ELISAEOF
)" 161
