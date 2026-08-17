#!/usr/bin/env bash
# `project easm-lint` against stage0.
#
# stage1 reproduces the report for a target with NO EASM inputs — which is every project that
# does not use EASM, and is the whole of stage0's output for them. A target that DOES carry
# `.easm` inputs is refused by name.
#
# The refusal is not about the grammar. A routine-subset PARSER was written, matched stage0
# exactly on a simple module, and was then removed: stage0's easm-lint VERIFIES. A two-export
# fixture produced eight `Issues:` entries from an entry-fact whitelist, label and control
# contract validation, parameter/input binding, and REGISTER DATAFLOW over the instruction
# stream. A parser without those checks prints a module with no issues — "this EASM is fine"
# about code stage0 rejects with eight errors.
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

# A target that DOES carry EASM inputs. stage0 parses and reports modules; stage1 must refuse
# by name and exit non-zero, NOT print a module-less report.
total=$((total + 1))
project carries "" "asm/spin.easm"
cat > "$WORK/carries/asm/spin.easm" <<'EASM'
module spin
target any
EASM
out="$( cd "$WORK/carries" && RUN "$BIN" project easm-lint 2>&1 )"
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "cannot verify them"; then
    pass=$((pass + 1))
else
    echo "  FAIL carries_easm_refused: rc=$rc out='$(printf '%s' "$out" | head -1)'"
fi

# stage0 must still handle that project — if it did not, the refusal above would be agreeing
# with a broken oracle rather than declining a real capability.
total=$((total + 1))
if ( cd "$WORK/carries" && RUN "$ELISACORE_BIN" project easm-lint 2>&1 | grep -q "^Module spin" ); then
    pass=$((pass + 1))
else
    echo "  FAIL carries_easm_oracle: stage0 did not report a module for the fixture; the refusal case proves nothing"
fi

if [ "$pass" -ne "$total" ]; then
    echo "project_easm_lint_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
echo "project_easm_lint_smoke OK: $pass/$total (no-EASM parity; EASM inputs refused by name)"
