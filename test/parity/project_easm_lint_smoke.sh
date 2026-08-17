#!/usr/bin/env bash
# `project easm-lint` against stage0.
#
# stage1 reproduces the report for a target with NO EASM inputs — which is every project that
# does not use EASM, and is the whole of stage0's output for them. A target that DOES carry
# `.easm` inputs is refused by name.
#
# stage1 now VERIFIES the void / no-parameter subset — the intrinsic shims real projects carry
# (`pause; ret`, `trap`) — reproducing stage0's module lines, its issues and its exit code.
#
# The boundary is parameters and a non-void return. Those force `inputs:`/`outputs:`, and
# declaring either reaches register dataflow (`input-register-unused`,
# `return-register-not-written`) which this port does not model. An exhaustive sweep of the
# void/no-param space reaches exactly THIRTEEN issue codes, all decidable from declarations
# plus the operand-free instruction list, and all thirteen are implemented. Anything outside
# that — parameters, non-void, `facts:`/`labels:`, operands, an unmodelled mnemonic — is
# refused by name, because reporting "no issues" for a routine whose checks were skipped is a
# false clean.
#
# Both halves are asserted. The refusal is not a skip: if the verifier is ever ported, the last
# check fails and says so, rather than the refusal quietly outliving the gap.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 120 "$@"; else "$@"; fi; }
set -u
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"

[ -x "$BIN" ] || { echo "project_easm_lint_smoke SKIP: no stage1 binary at $BIN"; exit 0; }
[ -x "$ELISACORE_BIN" ] || { echo "project_easm_lint_smoke SKIP: no elisac at $ELISACORE_BIN"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

pass=0; total=0

# project <name> [triple] [easm-entry]
project() {
    local name="$1" triple="${2:-}" easm="${3:-}"
    mkdir -p "$WORK/$name/src" "$WORK/$name/asm"
    printf 'def main() -> i64:\n    return 0\n' > "$WORK/$name/src/main.elisa"
    local triple_line="" easm_line=""
    [ -n "$triple" ] && triple_line="      \"target-triple\": \"$triple\","
    [ -n "$easm" ] && easm_line="      \"easm\": [\"$easm\"],"
    cat > "$WORK/$name/project.json" <<JSON
{
  "version": "0.1.0",
  "include-dirs": ["src"],
  "targets": {
    "app": {
$triple_line
$easm_line
      "entry": "src/main.elisa",
      "emit": "llvm"
    }
  }
}
JSON
}

check() {
    local name="$1"
    local form
    for form in text json; do
        total=$((total + 1))
        local o0 o1 extra=""
        [ "$form" = "json" ] && extra="--json"
        o0="$( cd "$WORK/$name" && RUN "$ELISACORE_BIN" project easm-lint $extra 2>&1; echo "rc=$?" )"
        o1="$( cd "$WORK/$name" && RUN "$BIN" project easm-lint $extra 2>&1; echo "rc=$?" )"
        if [ "$o0" = "$o1" ]; then
            pass=$((pass + 1))
        else
            echo "  FAIL $name ($form)"
            diff <(printf '%s\n' "$o0") <(printf '%s\n' "$o1") | sed 's/^/      /' | head -8
        fi
    done
}

# No EASM inputs, with and without an explicit triple — `targetTriple` is omitempty in the
# JSON, so the two differ by more than one line of text.
project none
check none
project with_triple x86_64-unknown-linux-gnu
check with_triple

# A MODELLED routine — void, no parameters, operand-free body — must be verified and reported
# byte-identically, issues included.
total=$((total + 1))
project modelled "" "asm/spin.easm"
cat > "$WORK/modelled/asm/spin.easm" <<'EASM'
module spin
target any
export def easm_spin_pause() -> void abi c:
    clobbers: memory
    stack: unchanged
    control: returns
    requires: x86_64.sse.pause
    body:
        pause
        ret
EASM
m0="$( cd "$WORK/modelled" && RUN "$ELISACORE_BIN" project easm-lint 2>&1; echo "rc=$?" )"
m1="$( cd "$WORK/modelled" && RUN "$BIN" project easm-lint 2>&1; echo "rc=$?" )"
if [ "$m0" = "$m1" ]; then pass=$((pass + 1)); else
    echo "  FAIL modelled_routine"; diff <(printf '%s\n' "$m0") <(printf '%s\n' "$m1") | sed 's/^/      /' | head -6
fi

# The same routine with an ISSUE — no capability declared — must report it, and exit 1.
total=$((total + 1))
project modelled_issue "" "asm/spin.easm"
cat > "$WORK/modelled_issue/asm/spin.easm" <<'EASM'
module spin
target any
export def easm_spin_pause() -> void abi c:
    stack: unchanged
    control: returns
    body:
        pause
        ret
EASM
i0="$( cd "$WORK/modelled_issue" && RUN "$ELISACORE_BIN" project easm-lint 2>&1; echo "rc=$?" )"
i1="$( cd "$WORK/modelled_issue" && RUN "$BIN" project easm-lint 2>&1; echo "rc=$?" )"
if [ "$i0" = "$i1" ] && printf '%s' "$i1" | grep -q "missing-capability"; then pass=$((pass + 1)); else
    echo "  FAIL modelled_issue"; diff <(printf '%s\n' "$i0") <(printf '%s\n' "$i1") | sed 's/^/      /' | head -6
fi

# A routine OUTSIDE the subset must still be refused by name. Parameters are the boundary:
# declaring inputs/outputs is what reaches register dataflow, which this port does not model.
total=$((total + 1))
project unmodelled "" "asm/spin.easm"
cat > "$WORK/unmodelled/asm/spin.easm" <<'EASM'
module spin
target any
export def takes(a: uintptr) -> void abi c:
    stack: unchanged
    control: returns
    inputs: a = rdi
    body:
        ret
EASM
out="$( cd "$WORK/unmodelled" && RUN "$BIN" project easm-lint 2>&1 )"
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "cannot verify them"; then
    pass=$((pass + 1))
else
    echo "  FAIL unmodelled_refused: rc=$rc out='$(printf '%s' "$out" | head -1)'"
fi

# stage0 must handle that same fixture, or the refusal proves nothing.
total=$((total + 1))
if ( cd "$WORK/unmodelled" && RUN "$ELISACORE_BIN" project easm-lint 2>&1 | grep -q "^Module spin" ); then
    pass=$((pass + 1))
else
    echo "  FAIL unmodelled_oracle: stage0 did not report a module for the fixture"
fi

if [ "$pass" -ne "$total" ]; then
    echo "project_easm_lint_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
echo "project_easm_lint_smoke OK: $pass/$total (void/no-param routines verified; the rest refused)"
