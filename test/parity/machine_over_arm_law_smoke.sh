#!/usr/bin/env bash
# docs/123 §5 (the machine arm law), stage1-OWNED (docs/125 step 13): a `machine over` arm
# body is STRAIGHT-LINE. All discrimination lives in the arm HEADER, so hidden branching/
# looping (`if`/`match`/`while`/`for`) and `continue` are REFUSED BY STAGE1 (P >= 1). A
# straight-line body plus a `-> State` transition stays legal (P 0). `return`/`break` are arm
# EXITS and remain legal. Mirrors stage0's parser/machine.go validateMachineArmStmt.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "machine-over arm-law smoke FAIL: $1" >&2; exit 1; }

# 1. LEGAL: straight-line body mutating the driven resource + `-> State` transition.
#    An unrelated outer binding is deliberately not used here: the foreign-mutation law
#    rejects it, and the stage0 oracle now enforces that rule as well.
out=$(printf 'def scan(cursor: mutable i64) -> i64:\n    machine over cursor while cursor < 1:\n        state Run\n        start Run\n        Run, _:\n            cursor <- cursor + 1\n            -> Run\n    return cursor\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "legal straight-line arm flagged: $out"

# 1b. LEGAL: compound assignment is also a straight-line mutation and must use the same
# driven-resource validation as `<-`, rather than being silently skipped by stage1.
out=$(printf 'def scan(lexer: mutable Lexer&) -> i64:\n    total: i64 = 0\n    machine over lexer.current_char() while not lexer.is_end():\n        state Run\n        start Run\n        Run, .Digit:\n            total += 1\n            -> Run\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "legal compound assignment arm flagged: $out"

# 1c. LEGAL: a multi-subscript assignment target is still rooted in the driven value. Stage1
# stores this as `Expr.IndexN`; its machine lvalue-root helper must not reject it while stage0
# represents the same source as an IndexExpr with Index2.
out=$(printf 'def scan(table: mutable Table&) -> i64:\n    machine over table[0, 0]:\n        state Run\n        start Run\n        Run, _:\n            table[0, 0] <- 1\n            -> Run\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "legal multi-index assignment arm flagged: $out"

# 1d. LEGAL: a qualified value expression still contributes its base binding to the driven
# resource set. `Scope` is a distinct AST node from `Field`; the stage1 root walker must recurse
# through it so a mutation of `resource` is not misclassified as foreign state.
out=$(printf 'def scan(resource: mutable Resource&) -> i64:\n    machine over resource::current():\n        state Run\n        start Run\n        Run, _:\n            resource[0] <- 1\n            -> Run\n    return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "qualified driven-resource root was not retained: $out"

# 2. ILLEGAL: a hidden `if` in an arm body (the guard belongs in the arm header).
out=$(printf 'def scan(lexer: mutable Lexer&) -> i64:\n    total: i64 = 0\n    machine over lexer.current_char() while not lexer.is_end():\n        state Run\n        start Run\n        Run, .Digit:\n            if total > 0:\n                total <- total + 1\n            -> Run\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "hidden if in arm body NOT refused: $out"

# 3. ILLEGAL: `continue` (every arm ends in `-> State`, `return`, or `break`).
out=$(printf 'def scan(lexer: mutable Lexer&) -> i64:\n    total: i64 = 0\n    machine over lexer.current_char() while not lexer.is_end():\n        state Run\n        start Run\n        Run, .Digit:\n            continue\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "continue in arm body NOT refused: $out"

echo "machine-over arm-law smoke OK: straight-line legal; hidden if + continue refused by stage1"
