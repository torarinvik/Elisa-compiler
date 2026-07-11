#!/usr/bin/env bash
# docs/123 §5 (the machine arm law), stage1-OWNED (docs/125 step 13): a `machine over` arm
# body is STRAIGHT-LINE. All discrimination lives in the arm HEADER, so hidden branching/
# looping (`if`/`match`/`while`/`for`) and `continue` are REFUSED BY STAGE1 (P >= 1). A
# straight-line body plus a `-> State` transition stays legal (P 0). `return`/`break` are arm
# EXITS and remain legal. Mirrors stage0's parser/machine.go validateMachineArmStmt.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "machine-over arm-law smoke FAIL: $1" >&2; exit 1; }

# 1. LEGAL: straight-line body (`total <- total + 1`) + `-> State` transition.
out=$(printf 'def scan(lexer: mutable Lexer&) -> i64:\n    total: i64 = 0\n    machine over lexer.current_char() while not lexer.is_end():\n        state Run\n        start Run\n        Run, .Digit:\n            total <- total + 1\n            -> Run\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "legal straight-line arm flagged: $out"

# 2. ILLEGAL: a hidden `if` in an arm body (the guard belongs in the arm header).
out=$(printf 'def scan(lexer: mutable Lexer&) -> i64:\n    total: i64 = 0\n    machine over lexer.current_char() while not lexer.is_end():\n        state Run\n        start Run\n        Run, .Digit:\n            if total > 0:\n                total <- total + 1\n            -> Run\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "hidden if in arm body NOT refused: $out"

# 3. ILLEGAL: `continue` (every arm ends in `-> State`, `return`, or `break`).
out=$(printf 'def scan(lexer: mutable Lexer&) -> i64:\n    total: i64 = 0\n    machine over lexer.current_char() while not lexer.is_end():\n        state Run\n        start Run\n        Run, .Digit:\n            continue\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "continue in arm body NOT refused: $out"

echo "machine-over arm-law smoke OK: straight-line legal; hidden if + continue refused by stage1"
