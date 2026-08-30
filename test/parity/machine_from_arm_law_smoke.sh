#!/usr/bin/env bash
# docs/125 §5 R1 (the machine arm law), stage1-OWNED (docs/125 step 13): a `machine from`
# arm body is STRAIGHT-LINE. Resolution is `next`/`done`, so hidden branching
# (`if`/`match`/`while`/`for`) and escapes (`return`/`break`/`continue`) in a body are
# refused BY STAGE1 ITSELF (P >= 1) rather than deferred to stage0. Mutation (the `<-`
# advance) and guarded terminators (`next X if C`) stay legal (P 0). Sibling of the
# machine-over arm law; mirrors stage0's parser/machine_from.go validateMachineFromArmStmt.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "machine-from arm-law smoke FAIL: $1" >&2; exit 1; }

# 1. LEGAL: a straight-line body (`n <- n - 1` mutation) + guarded/plain `next`/`done`
#    terminators parses clean.
out=$(printf 'const enum St of u8:\n    Step\n    Stop\ndef down(x: i64) -> i64:\n    n: mutable i64 = x\n    total: i64 = machine from St.Step decreases n:\n        St.Step:\n            n <- n - 1\n            next St.Stop if n <= 0\n            next St.Step\n        St.Stop:\n            done n\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "legal straight-line body flagged: $out"

# 2. ILLEGAL: a hidden `if` in an arm body (should be a guarded `next`/`done` instead).
out=$(printf 'const enum St of u8:\n    Step\n    Stop\ndef down(x: i64) -> i64:\n    n: mutable i64 = x\n    total: i64 = machine from St.Step decreases n:\n        St.Step:\n            if n > 0:\n                n <- n - 1\n            next St.Stop if n <= 0\n            next St.Step\n        St.Stop:\n            done n\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "hidden if in arm body NOT refused: $out"

# 3. ILLEGAL: a `return` escape (resolution is `done`, not a function return).
out=$(printf 'const enum St of u8:\n    Step\n    Stop\ndef down(x: i64) -> i64:\n    n: mutable i64 = x\n    total: i64 = machine from St.Step decreases n:\n        St.Step:\n            return 0\n        St.Stop:\n            done n\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "return escape in arm body NOT refused: $out"

# 4. ILLEGAL: a `while` loop hidden in an arm body.
out=$(printf 'const enum St of u8:\n    Step\n    Stop\ndef down(x: i64) -> i64:\n    n: mutable i64 = x\n    total: i64 = machine from St.Step decreases n:\n        St.Step:\n            while n > 0:\n                n <- n - 1\n            next St.Stop\n        St.Stop:\n            done n\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" && fail "hidden while in arm body NOT refused: $out"

echo "machine-from arm-law smoke OK: straight-line legal; hidden if/while + return escape refused by stage1"
