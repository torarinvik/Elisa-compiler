#!/usr/bin/env bash
# The grammar/lexer DSL was removed from Elisa. Stage1 must reject every former
# declaration head once and recover past any indented body.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
REPO_ROOT="$REPO_ROOT" ELISACORE_BIN="$ELISACORE_BIN" bash "$REPO_ROOT/test/parity/build_parse_report.sh"

check_removed() {
  local head="$1"
  local source="$2"
  local output
  output="$(printf '%s' "$source" | "$REPO_ROOT/build/parse_report")"
  [[ "$output" == *"D 1"* && "$output" == *"unexpected token '$head'"* ]] || {
    echo "removed DSL declaration was not rejected cleanly: $head" >&2
    printf '%s\n' "$output" >&2
    exit 1
  }
}

check_removed grammar $'grammar G:\n    pass\n'
check_removed grammarenv $'grammarenv E:\n    pass\n'
check_removed lexer $'lexer L:\n    pass\n'
check_removed tokenset $'tokenset T = []\n'
check_removed charset $'charset C = \'a\'\n'
check_removed keywordmap $'keywordmap K: cstr -> i64:\n    _ => 0\n'
check_removed extend $'extend grammar G:\n    pass\n'

echo "grammar/lexer DSL removal smoke OK"
