#!/usr/bin/env bash
# A `const module` takes `public:` / `private:` sections like any other module block, and
# both compilers must agree on what each one exposes.
#
# The rule being pinned (stage0's `canAccessPrivateName`): a private member is reachable
# from its owning namespace and its DESCENDANTS, never its ancestors. So an UNMARKED
# member of a const module that sits in a `private:` section is private to the const
# module itself and even the parent module cannot read it — which is what makes the
# `public:` section the only way to publish a grouped constant.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
# shellcheck source=/dev/null
source "$ROOT/test/parity/resolve_elisac.sh"
STAGE0="${ELISACORE_BIN:?resolve_elisac.sh did not set ELISACORE_BIN}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$STAGE1_ROOT/bin/elisac-stage1}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for tool in "$STAGE0" "$STAGE1_BIN"; do
    if [[ ! -x "$tool" ]]; then
        echo "const module visibility: missing compiler: $tool" >&2
        exit 2
    fi
done

failed=0
case_index=0

# run_case LABEL legal|illegal|stage0-only-illegal  < source
#
# `stage0-only-illegal` pins a KNOWN divergence rather than hiding it: stage0 refuses and
# stage1 still accepts, because stage1's private-member check only inspects an `Expr.Scope`
# whose base is an `Expr.Ident`. A NESTED module's access is `Scope(Scope(Ident("Geo"),
# "Scalar"), "hidden")`, so it is never examined -- a pre-existing permissive gap that has
# nothing to do with const modules (`module Geo: module Scalar: private: def hidden()` is
# accepted by stage1 too). Closing it also needs a DOT-spelled owner path for the message,
# since stage1 carries module paths with `::` and the diagnostic renders the owner verbatim.
# When it closes, flip these two cases to plain `illegal`.
run_case() {
    local label="$1" verdict="$2"
    case_index=$((case_index + 1))
    local src="$TMP_DIR/case$case_index.elisa"
    cat > "$src"

    set +e
    "$STAGE0" -emit obj -O0 -o "$TMP_DIR/case$case_index.s0.o" "$src" >"$TMP_DIR/case$case_index.s0.out" 2>&1
    local s0_rc=$?
    "$STAGE1_BIN" -emit obj -O0 -o "$TMP_DIR/case$case_index.s1.o" "$src" >"$TMP_DIR/case$case_index.s1.out" 2>&1
    local s1_rc=$?
    set -e

    # stage0 reports rc=0 with a ZERO-BYTE object for some inputs, so acceptance is
    # rc=0 AND a non-empty object — never rc alone.
    local s0_size=0 s1_size=0
    [[ -f "$TMP_DIR/case$case_index.s0.o" ]] && s0_size=$(wc -c < "$TMP_DIR/case$case_index.s0.o" | tr -d ' ')
    [[ -f "$TMP_DIR/case$case_index.s1.o" ]] && s1_size=$(wc -c < "$TMP_DIR/case$case_index.s1.o" | tr -d ' ')
    local s0_ok=0 s1_ok=0
    [[ "$s0_rc" -eq 0 && "$s0_size" -gt 0 ]] && s0_ok=1
    [[ "$s1_rc" -eq 0 && "$s1_size" -gt 0 ]] && s1_ok=1

    local want_s0=0 want_s1=0
    case "$verdict" in
        legal)               want_s0=1; want_s1=1 ;;
        illegal)             want_s0=0; want_s1=0 ;;
        stage0-only-illegal) want_s0=0; want_s1=1 ;;
        *) echo "const module visibility: $label: unknown verdict $verdict" >&2; exit 2 ;;
    esac
    if [[ "$s0_ok" -ne "$want_s0" ]]; then
        echo "const module visibility: $label: stage0 verdict wrong (accepted=$s0_ok want=$want_s0)" >&2
        sed -n '1,4p' "$TMP_DIR/case$case_index.s0.out" >&2
        failed=$((failed + 1))
    fi
    if [[ "$s1_ok" -ne "$want_s1" ]]; then
        # A stage1 verdict that moved on a pinned divergence is NEWS either way: it either
        # closed the gap (tighten this case) or widened it.
        echo "const module visibility: $label: stage1 verdict wrong (accepted=$s1_ok want=$want_s1)" >&2
        sed -n '1,4p' "$TMP_DIR/case$case_index.s1.out" >&2
        failed=$((failed + 1))
    fi
}

run_case "public section publishes to the parent" legal <<'SRC'
module Geo:
    private:
        const module Scalar:
            public:
                ZERO: i64 = 0
                ONE: i64 = 1
            private:
                HIDDEN: i64 = 9

    public:
        def zero() -> i64:
            return Scalar::ZERO

def main() -> i64:
    return Geo::zero()
SRC

run_case "private section stays hidden outside" stage0-only-illegal <<'SRC'
module Geo:
    const module Scalar:
        public:
            ZERO: i64 = 0
        private:
            HIDDEN: i64 = 9

def main() -> i64:
    return Geo::Scalar::HIDDEN
SRC

run_case "unmarked member of a private const module is not visible to the parent" stage0-only-illegal <<'SRC'
module Geo:
    private:
        const module Scalar:
            ZERO: i64 = 0

    public:
        def zero() -> i64:
            return Scalar::ZERO

def main() -> i64:
    return Geo::zero()
SRC

run_case "flat section label covers the rest of the const module body" legal <<'SRC'
module Geo:
    private:
        const module Scalar:
            public:
            ZERO: i64 = 0
            ONE: i64 = 1

    public:
        def one() -> i64:
            return Scalar::ONE

def main() -> i64:
    return Geo::one() - 1
SRC

# Executed: the published constant must reach the parent with the RIGHT value in both
# compilers, not merely compile. A wrong-value bug here is invisible to an accept check.
EXEC_SRC="$TMP_DIR/exec.elisa"
cat > "$EXEC_SRC" <<'SRC'
module Geo:
    private:
        const module Scalar:
            public:
                SEVEN: i64 = 7
                TWO: i64 = 2

    public:
        def answer() -> i64:
            return Scalar::SEVEN * Scalar::TWO

def main() -> i64:
    return Geo::answer()
SRC

if command -v clang >/dev/null 2>&1; then
    "$STAGE0" -emit obj -O0 -o "$TMP_DIR/exec.s0.o" "$EXEC_SRC"
    clang -o "$TMP_DIR/exec.s0" "$TMP_DIR/exec.s0.o"
    ELISA_STAGE1_ROOT="$STAGE1_ROOT" ELISA_STAGE1_BIN="$STAGE1_BIN" \
        "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit exe -O0 -o "$TMP_DIR/exec.s1" "$EXEC_SRC"
    set +e
    "$TMP_DIR/exec.s0"; s0_exit=$?
    "$TMP_DIR/exec.s1"; s1_exit=$?
    set -e
    if [[ "$s0_exit" -ne 14 || "$s1_exit" -ne 14 ]]; then
        echo "const module visibility: executed case wrong: stage0=$s0_exit stage1=$s1_exit expected=14" >&2
        failed=$((failed + 1))
    fi
else
    echo "const module visibility: clang not available, skipping the executed case" >&2
fi

if [[ "$failed" -ne 0 ]]; then
    echo "const module visibility smoke FAILED: $failed check(s)" >&2
    exit 1
fi

echo "const module visibility smoke OK: public/private sections agree in BOTH compilers, executed"
echo "  (two refusal cases are stage0-only: stage1's nested-module privacy gap, pinned above)"
