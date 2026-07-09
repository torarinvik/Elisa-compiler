#!/usr/bin/env bash
# docs/125 §5 — `PATTERN with NAME = LITERAL[, ...]` arm-alternative discriminators parse
# (P 0) and desugar to a resolvable arm (D 0): the arm fans out into one sibling per `|`
# alternative, each carrying its discriminating constants prepended to a copy of the shared
# body — so a body that READS the constant resolves it (no undefined-name diagnostic). The
# `with`-less arm shape is left byte-for-byte on the existing path.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "with smoke FAIL: $1" >&2; exit 1; }

# 1. Two alternatives on ONE line, body reads the per-alternative constant.
out=$(printf 'const enum Sign of u8:\n    Pos\n    Neg\ndef classify(s: Sign) -> i64:\n    return match s:\n        Sign.Pos with negated = 0 | Sign.Neg with negated = 1:\n            return negated\n        _:\n            return 2\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "single-line with had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "single-line with had diagnostics (constant unresolved?): $out"

# 2. Alternatives split across lines (continuation `|`), each with MULTIPLE constants.
out=$(printf 'const enum K of u8:\n    A\n    B\ndef f(k: K) -> i64:\n    return match k:\n        K.A with lo = 1, hi = 2\n        | K.B with lo = 3, hi = 4:\n            return lo + hi\n        _:\n            return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "multi-line multi-decl with had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "multi-line multi-decl with had diagnostics: $out"

# 3. A `with`-less arm (plain or-pattern) is unchanged — no fan-out, still resolves clean.
out=$(printf 'const enum K of u8:\n    A\n    B\ndef f(k: K) -> i64:\n    return match k:\n        K.A | K.B:\n            return 1\n        _:\n            return 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "with-less arm regressed (parse): $out"
echo "$out" | grep -q "^D 0$" || fail "with-less arm regressed (diagnostics): $out"

echo "with smoke OK: single-line + multi-line/multi-decl alternatives bind their constants; with-less arm unchanged"
