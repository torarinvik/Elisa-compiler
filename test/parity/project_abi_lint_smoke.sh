#!/usr/bin/env bash
# `project abi-lint` against stage0, one fixture per RULE.
#
# The lint is twelve regexes in stage0 and twelve hand-rolled matchers in stage1 (Elisa has
# no regex library). A matcher that is subtly too narrow makes the tool print "ABI lint:
# clean" for a project it did not check — a false clean, which is worse than no lint. So each
# rule gets a fixture that should FIRE it and, where the rule has a guard (a memory clobber, a
# scratch register, an ELISA_ABI_LINT_ALLOW), a companion fixture that should SUPPRESS it.
# Both directions matter: a matcher that never matches passes a fire-only suite trivially if
# the expected output is taken from stage1 rather than stage0. It is not — every expectation
# here is whatever stage0 printed.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 120 "$@"; else "$@"; fi; }
set -u
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"

[ -x "$BIN" ] || { echo "project_abi_lint_smoke SKIP: no stage1 binary at $BIN"; exit 0; }
[ -x "$ELISACORE_BIN" ] || { echo "project_abi_lint_smoke SKIP: no elisac at $ELISACORE_BIN"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

pass=0; total=0

# project <name> [triple] — a scaffold whose single target carries native/guest.c
project() {
    local name="$1" triple="${2:-}"
    mkdir -p "$WORK/$name/native" "$WORK/$name/src"
    printf 'def main() -> i64:\n    return 0\n' > "$WORK/$name/src/main.elisa"
    local triple_line=""
    [ -n "$triple" ] && triple_line="      \"target-triple\": \"$triple\","
    cat > "$WORK/$name/project.json" <<JSON
{
  "version": "0.1.0",
  "include-dirs": [
    "src"
  ],
  "targets": {
    "app": {
      "entry": "src/main.elisa",
      "emit": "llvm",
$triple_line
      "foreign": [
        "native/guest.c"
      ]
    }
  }
}
JSON
}

# check <name> [extra-args...] — stage0 and stage1 must agree on stdout AND exit code, in
# BOTH the text and the --json form. The JSON is not a rendering detail of the same data:
# `omitempty` drops fields, `line` disappears on issues that carry none, and a clean project
# prints `"issues": null` rather than an empty array — all of which are separately wrong-able.
check() {
    local name="$1"; shift
    local form
    for form in text json; do
        total=$((total + 1))
        local o0 o1 extra=""
        [ "$form" = "json" ] && extra="--json"
        o0="$( cd "$WORK/$name" && RUN "$ELISACORE_BIN" project abi-lint "$@" $extra 2>&1; echo "rc=$?" )"
        o1="$( cd "$WORK/$name" && RUN "$BIN" project abi-lint "$@" $extra 2>&1; echo "rc=$?" )"
        if [ "$o0" = "$o1" ]; then
            pass=$((pass + 1))
        else
            echo "  FAIL $name ($form)"
            diff <(printf '%s\n' "$o0") <(printf '%s\n' "$o1") | sed 's/^/      /' | head -8
        fi
    done
}

# --- no native sources at all: the clean path, and the one that must NOT emit
#     target-triple-defaulted (stage0 emits it only when foreign sources exist).
total=$((total + 1))
mkdir -p "$WORK/bare"
( cd "$WORK/bare" && "$ELISACORE_BIN" init demo >/dev/null 2>&1 )
b0="$( cd "$WORK/bare/demo" && RUN "$ELISACORE_BIN" project abi-lint 2>&1; echo "rc=$?" )"
b1="$( cd "$WORK/bare/demo" && RUN "$BIN" project abi-lint 2>&1; echo "rc=$?" )"
if [ "$b0" = "$b1" ]; then pass=$((pass + 1)); else
    echo "  FAIL no_native_sources"; diff <(printf '%s\n' "$b0") <(printf '%s\n' "$b1") | sed 's/^/      /' | head -6
fi

# --- a C file with no asm at all: scanned, no issues but the info one.
project quiet
printf 'int add(int a, int b) { return a + b; }\n' > "$WORK/quiet/native/guest.c"
check quiet

# --- positional operands + arg register, and the stack/memory-clobber rule.
project positional
cat > "$WORK/positional/native/guest.c" <<'C'
void helper(void *ctx) {
    __asm__ volatile ("movq %0, %%rdi\n" "pushq %%rbp\n" : : "r"(ctx));
}
C
check positional

# --- the same block WITH a memory clobber: the clobber rule must go quiet, the
#     positional one must not.
project clobber
cat > "$WORK/clobber/native/guest.c" <<'C'
void helper(void *ctx) {
    __asm__ volatile ("movq %0, %%rdi\n" "pushq %%rbp\n" : : "r"(ctx) : "memory");
}
C
check clobber

# --- guest-entry with `call *`: the error rule, including the noreturn-dependent tail.
project guest_call
cat > "$WORK/guest_call/native/guest.c" <<'C'
/* ELISA_ABI_CONTRACT guest_entry */
void RunMainEntry(void *ctx) {
    __asm__ volatile (
        "movq %0, %%rdi\n"
        "pushq %%rbp\n"
        "call *%1\n"
        : : "r"(ctx), "r"(ctx)
    );
}
C
check guest_call

# --- the same, marked noreturn: the message loses its trailing clause.
project guest_call_noreturn
cat > "$WORK/guest_call_noreturn/native/guest.c" <<'C'
/* ELISA_ABI_CONTRACT guest_entry */
__attribute__((noreturn)) void RunMainEntry(void *ctx) {
    __asm__ volatile (
        "movq %0, %%rdi\n"
        "pushq %%rbp\n"
        "call *%1\n"
        : : "r"(ctx), "r"(ctx)
    );
}
C
check guest_call_noreturn

# --- guest-entry with `jmp *` and no noreturn: the jump rule.
project guest_jump
cat > "$WORK/guest_jump/native/guest.c" <<'C'
/* ELISA_ABI_CONTRACT guest_entry */
void guest_exec(void *ctx) {
    __asm__ volatile (
        "movq %0, %%rdi\n"
        "pushq %%rbp\n"
        "jmp *%1\n"
        : : "r"(ctx), "r"(ctx)
    );
}
C
check guest_jump

# --- scratch parking present: the scratch rule goes quiet, the others stay.
project scratch
cat > "$WORK/scratch/native/guest.c" <<'C'
/* ELISA_ABI_CONTRACT guest_entry */
void RunMainEntry(void *ctx) {
    __asm__ volatile (
        "movq %0, %%r10\n"
        "movq %%r10, %%rdi\n"
        "pushq %%rbp\n"
        : : "r"(ctx) : "memory"
    );
}
C
check scratch

# --- ELISA_ABI_LINT_ALLOW suppression, one code and the blanket form.
project allow_one
cat > "$WORK/allow_one/native/guest.c" <<'C'
void helper(void *ctx) {
    /* ELISA_ABI_LINT_ALLOW(inline-asm-positional-abi-operands) */
    __asm__ volatile ("movq %0, %%rdi\n" "pushq %%rbp\n" : : "r"(ctx));
}
C
check allow_one

project allow_all
cat > "$WORK/allow_all/native/guest.c" <<'C'
void helper(void *ctx) {
    /* ELISA_ABI_LINT_ALLOW(all) */
    __asm__ volatile ("movq %0, %%rdi\n" "pushq %%rbp\n" : : "r"(ctx));
}
C
check allow_all

# --- `andq ... %%rsp` on one line is stack mutation; the same instruction and register on
#     DIFFERENT lines is not (the regex alternative is line-scoped via [^\n]*).
project stack_same_line
cat > "$WORK/stack_same_line/native/guest.c" <<'C'
void helper(void *ctx) {
    __asm__ volatile ("andq $-16, %%rsp\n" : : "r"(ctx));
}
C
check stack_same_line

# --- recursion through a quoted include, and the contract declared in the header.
project recursive
mkdir -p "$WORK/recursive/native/inc"
cat > "$WORK/recursive/native/inc/entry.h" <<'C'
/* ELISA_ABI_CONTRACT guest_entry */
static void jump_main_entry(void *ctx) {
    __asm__ volatile ("movq %0, %%rdi\n" "pushq %%rbp\n" "jmp *%0\n" : : "r"(ctx));
}
C
printf '#include "inc/entry.h"\nvoid use(void *c) { jump_main_entry(c); }\n' > "$WORK/recursive/native/guest.c"
check recursive

# --- a foreign source that does not exist: stage0 reports it rather than aborting.
project missing_source
rm -f "$WORK/missing_source/native/guest.c"
check missing_source

# --- an explicit x86_64 triple silences target-triple-defaulted.
project with_triple x86_64-unknown-linux-gnu
cat > "$WORK/with_triple/native/guest.c" <<'C'
int add(int a, int b) { return a + b; }
C
check with_triple

# --- --strict-contracts: a guest-entry-looking file with NO contract, and a contract with a
#     non-x86_64 triple.
project strict_missing
cat > "$WORK/strict_missing/native/guest.c" <<'C'
void RunMainEntry(void *ctx) { (void)ctx; }
C
check strict_missing --strict-contracts

project strict_triple aarch64-apple-darwin
cat > "$WORK/strict_triple/native/guest.c" <<'C'
/* ELISA_ABI_CONTRACT guest_entry */
void RunMainEntry(void *ctx) { (void)ctx; }
C
check strict_triple --strict-contracts

if [ "$pass" -ne "$total" ]; then
    echo "project_abi_lint_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
echo "project_abi_lint_smoke OK: $pass/$total (abi-lint matches stage0 per rule)"
