#!/usr/bin/env bash
# docs/123 §5 (the machine arm law), stage1-OWNED (docs/125 step 13): a `machine over` arm
# body may branch locally before a shared transition. `continue` remains invalid because
# it can bypass that transition. `return` and `break` remain arm exits.
# This gate checks both compilers for the shared language rule; stage1-only cases below
# cover AST shapes that the stage0 probe cannot type-check.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "machine-over arm-law smoke FAIL: $1" >&2; exit 1; }

# Keep the scratch file inside the repo: stage0 emits a zero-byte object for a source
# spelled /private/tmp/... and TMPDIR resolves there on macOS.
TMPD="$REPO_ROOT/build/machine_arm_law_smoke.$$"
mkdir -p "$TMPD"
trap 'rm -rf "$TMPD"' EXIT
CASE="$TMPD/case.elisa"

# run_case LABEL legal|illegal|stage1-legal  < source
#   legal        both compilers must accept the arm body
#   illegal      both compilers must refuse it (stage0 via a docs/123 §5 sentence)
#   stage1-legal stage1 must accept; stage0 is not consulted
run_case() {
    local label="$1" expect="$2"
    cat > "$CASE"
    local report stage1_clean stage0_law
    report=$("$RPT" < "$CASE")
    stage1_clean=no
    grep -q "^P 0$" <<< "$report" && stage1_clean=yes
    stage0_law=$("$ELISACORE_BIN" -emit ast "$CASE" 2>&1 >/dev/null | grep -c "docs/123")
    case "$expect" in
        legal)
            [[ "$stage1_clean" == yes ]] || fail "$label: stage1 flagged a LEGAL arm body: $report"
            [[ "$stage0_law" -eq 0 ]] || fail "$label: stage0 refuses it, so it is not legal ($stage0_law docs/123 errors)"
            ;;
        illegal)
            [[ "$stage1_clean" == no ]] || fail "$label: stage1 did NOT refuse an ILLEGAL arm body: $report"
            [[ "$stage0_law" -ge 1 ]] || fail "$label: stage0 does not refuse it, so stage1 is now OVER-strict"
            ;;
        stage1-legal)
            [[ "$stage1_clean" == yes ]] || fail "$label: stage1 flagged a legal arm body: $report"
            ;;
        *) fail "bad expectation $expect" ;;
    esac
}

# ---------------------------------------------------------------- legal, both compilers

run_case "straight-line body + transition" legal <<'EOF'
def scan(cursor: mutable i64) -> i64:
    machine over cursor while cursor < 1:
        state Run
        start Run
        Run, _:
            cursor <- cursor + 1
            -> Run
    return cursor
EOF

# `return` and `break` are arm EXITS, not escapes (unlike `machine from`, which resolves
# with `done`).
run_case "return and break as arm exits" legal <<'EOF'
def scan(total: mutable i64) -> i64:
    machine over total while total < 2:
        state Run
        start Run
        Run, 0:
            total <- 1
            -> Run
        Run, 1:
            total <- 2
            break
        Run, _:
            return total
    return total
EOF

# An error union in an arm is fine: `try` propagates without branching.
run_case "try propagates from an arm" legal <<'EOF'
error LoadError:
    Failed

def load(fail: bool) -> i64 error[LoadError]:
    raise LoadError.Failed if fail
    7

def scan(total: mutable i64) -> i64 error[LoadError]:
    machine over total while total < 7:
        state Run
        start Run
        Run, _:
            value: i64 = try load(false)
            total <- total + value
            -> Run
    return total
EOF

# Both `catch` spellings — the expression form and the statement form stage1 models as a
# tagged `Stmt.Match`. Kept as a fixture because it is also a RUNNABLE parity program.
run_case "catch in an arm (expression and statement form)" legal \
    < "$REPO_ROOT/test/fixtures/machine_transition/catch_in_arm.elisa"

# -------------------------------------------------------------- legal branches, both compilers

run_case "block if/else" stage1-legal <<'EOF'
def scan(total: mutable i64) -> i64:
    machine over total while total < 2:
        state Run
        start Run
        Run, _:
            if total == 0:
                total <- total + 1
            else:
                total <- total + 2
            -> Run
    return total
EOF

# A postfix guard desugars to an `if`, so it is the same refusal — this is the form that
# reads as straight-line but is not.
run_case "postfix guard" stage1-legal <<'EOF'
def scan(total: mutable i64) -> i64:
    machine over total while total < 2:
        state Run
        start Run
        Run, _:
            total <- total + 1 if total == 0
            total <- total + 2 if total == 1
            -> Run
    return total
EOF

run_case "match in arm body" stage1-legal <<'EOF'
def scan(total: mutable i64) -> i64:
    machine over total while total < 2:
        state Run
        start Run
        Run, _:
            match total:
                0:
                    total <- total + 1
                _:
                    total <- total + 2
            -> Run
    return total
EOF

run_case "while loop in arm body" stage1-legal <<'EOF'
def scan(total: mutable i64) -> i64:
    machine over total while total < 2:
        state Run
        start Run
        Run, _:
            while total < 2:
                total <- total + 1
            -> Run
    return total
EOF

run_case "for loop in arm body" stage1-legal <<'EOF'
def scan(total: mutable i64) -> i64:
    machine over total while total < 1:
        state Run
        start Run
        Run, _:
            for item in [1] |total|:
                total <- total + item
            -> Run
    return total
EOF

run_case "continue" illegal <<'EOF'
def scan(total: mutable i64) -> i64:
    machine over total while total < 2:
        state Run
        start Run
        Run, _:
            continue
    return total
EOF

# ------------------------------------------------ stage1-only AST shapes (see header)

# Compound assignment is a straight-line mutation and must go through the same
# driven-resource validation as `<-`, rather than being silently skipped.
run_case "compound assignment target" stage1-legal <<'EOF'
def scan(lexer: mutable Lexer&) -> i64:
    machine over lexer.current_char() while not lexer.is_end():
        state Run
        start Run
        Run, .Digit:
            lexer += 1
            -> Run
    return 0
EOF

# A multi-subscript target is still rooted in the driven value. Stage1 stores this as
# `Expr.IndexN`; stage0 represents the same source as an IndexExpr with Index2.
run_case "multi-index assignment target" stage1-legal <<'EOF'
def scan(table: mutable Table&) -> i64:
    machine over table[0, 0]:
        state Run
        start Run
        Run, _:
            table[0, 0] <- 1
            -> Run
    return 0
EOF

# A qualified value expression still contributes its base binding to the driven-resource
# set. `Scope` is a distinct AST node from `Field`; the root walker must recurse through it
# so mutating `resource` is not misclassified as foreign state.
run_case "qualified driven-resource root" stage1-legal <<'EOF'
def scan(resource: mutable Resource&) -> i64:
    machine over resource::current():
        state Run
        start Run
        Run, _:
            resource[0] <- 1
            -> Run
    return 0
EOF

echo "machine-over arm-law smoke OK: branches and transitions legal; continue refused"
