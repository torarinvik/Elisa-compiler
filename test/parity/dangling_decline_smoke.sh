#!/usr/bin/env bash
# A PROGRAM whose object cannot possibly link must not compile "successfully".
#
# The backend tolerates a function whose body it cannot emit: the body is stripped and the
# name is recorded in `!elisa.declined` (ELISA_DBG_DECLINE prints it as DROPPED). That
# tolerance is what lets stage1 compile itself — the self-host build drops 45 functions and
# links fine, because every one of them is either dead code or an extern the libc/runtime
# object provides.
#
# What was NOT tolerable is that the driver exited 0 even when the stripped declaration was
# still CALLED. The compiler knew (it wrote the decline into the module's own metadata) and
# said nothing; the first symptom was `Undefined symbol: _total` from the host linker, with
# no indication that the compiler had given up on `total`. See emit_module_core.
#
# The check is narrow, and each case below pins one of the narrowings — a broader rule was
# measured and refuses to compile this compiler.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 60 "$@"; else "$@"; fi; }
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ] || { echo "dangling_decline_smoke SKIP: no stage1 binary"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

pass=0; total=0
decline_case() {
    local name="$1" src="$2" want="$3"
    total=$((total + 1))
    printf '%b' "$src" > "$WORK/$name.elisa"
    RUN "$STAGE1" -o "$WORK/$name.o" "$WORK/$name.elisa" >/dev/null 2>&1
    local got=$?
    if [ "$got" -ne "$want" ]; then
        echo "  FAIL $name: rc=$got want=$want"; return
    fi
    pass=$((pass + 1))
}

# The declining construct is a `deque[i64]` LOCAL: stage1's backend has no layout for it,
# so `total`'s body declines while `total`'s own signature stays emittable.
#
# It used to be a `dict[i64, i64]`, and stage1 has since GAINED dict support — the fixture
# stopped declining, so all four cases exercised an ordinary successful compile and the
# first one failed on an rc the compiler was right to return. A gate whose premise has
# quietly evaporated is worse than no gate, so the premise is now ASSERTED below rather
# than assumed: if `deque` gains support too, this says so in one line instead of looking
# like a regression.
DECLINING_BODY='    table: mutable deque[i64] = []\n'

# PRECONDITION: the construct must actually decline. ELISA_DBG_DECLINE prints DROPPED per
# stripped function.
printf 'def total() -> i64:\n%b    return 3\n\ndef main() -> i64:\n    return 7\n' "$DECLINING_BODY" > "$WORK/precondition.elisa"
if ! ELISA_DBG_DECLINE=1 RUN "$STAGE1" -o "$WORK/precondition.o" "$WORK/precondition.elisa" 2>&1 | grep -q 'DROPPED total'; then
    echo "dangling_decline_smoke FAILED: the fixture no longer declines — stage1 gained support for"
    echo "  the construct this gate leans on. Pick another (probe candidates with ELISA_DBG_DECLINE=1)."
    exit 1
fi

# `main` still calls the declining `total`, so the emitted object references a symbol
# nothing defines: rc 2, not a silent 0.
decline_case referenced_decline 'def total() -> i64:\n    table: mutable deque[i64] = []\n    return 3\n\ndef main() -> i64:\n    return total() + 4\n' 2

# The SAME declining function, never called. Its stripped declaration has no users, the
# linker never looks for it, and the program is fine. This is the narrowing the self-host
# build depends on: refusing every drop would refuse to compile the compiler.
decline_case unreferenced_decline 'def total() -> i64:\n    table: mutable deque[i64] = []\n    return 3\n\ndef main() -> i64:\n    return 7\n' 0

# A LIBRARY — no `main`. Its whole purpose is to be linked against something else, and
# `native_runtime_support.elisa` legitimately leaves symbols for the runtime object to
# satisfy. Same referenced decline as the first case; still compiles.
decline_case library_decline 'def total() -> i64:\n    table: mutable deque[i64] = []\n    return 3\n\ndef entry() -> i64:\n    return total() + 4\n' 0

# An ordinary program declines nothing and is unaffected.
decline_case clean_program 'def add(a: i64, b: i64) -> i64:\n    return a + b\n\ndef main() -> i64:\n    return add(40, 2)\n' 0

if [ "$pass" -ne "$total" ]; then echo "dangling_decline_smoke FAILED: passed=$pass total=$total"; exit 1; fi
echo "dangling_decline_smoke OK: $pass/$total (a called-but-declined body fails the compile)"
