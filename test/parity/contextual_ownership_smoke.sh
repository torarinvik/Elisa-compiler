#!/usr/bin/env bash
# Contextual ownership/concurrency forms must lower through their operand while the
# same spellings remain ordinary identifiers outside those exact forms.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "contextual-ownership smoke FAIL: $1" >&2; exit 1; }
clean() {
    local out
    out="$(printf '%s' "$1" | "$RPT")"
    echo "$out" | grep -q '^P 0$' || fail "parse error: $out"
    echo "$out" | grep -q '^D 0$' || fail "semantic diagnostic: $out"
}

clean $'struct Box:\n    value: int\n\ndef f() -> Box:\n    return new Box(value: 1)\n'
clean $'def f(x: int) -> int:\n    return freeze(move x)\n'
clean $'def f(x: int) -> int:\n    return await x\n'
clean $'def f(group: int) -> void:\n    wait all group\n'
clean $'def f(new: int, freeze: int, await: int, wait: int, all: int) -> int:\n    return new + freeze + await + wait + all\n'

echo "contextual-ownership smoke OK: new/freeze/await/wait-all lower through operands; identifier spellings remain usable"
