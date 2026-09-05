#!/usr/bin/env bash
# Namespace/value disambiguation and qualified module access.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "namespace smoke FAIL: $1" >&2; exit 1; }

bad=$(printf '%s\n' \
  'module M:' \
  '    def value() -> i64:' \
  '        return 1' \
  '' \
  'def f() -> i64:' \
  '    return M' | "$RPT")
echo "$bad" | grep -q "is a namespace; write M::member" || fail "namespace used as value was not rejected: $bad"

good=$(printf '%s\n' \
  'module M:' \
  '    def value() -> i64:' \
  '        return 1' \
  '' \
  'def f() -> i64:' \
  '    return M::value()' | "$RPT")
echo "$good" | grep -q '^P 0$' || fail "qualified module call did not parse: $good"
echo "$good" | grep -q '^D 0$' || fail "qualified module call produced diagnostics: $good"

echo "namespace smoke OK: namespace-as-value rejected, :: access accepted"
