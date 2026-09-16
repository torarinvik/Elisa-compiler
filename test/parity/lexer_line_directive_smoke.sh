#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/lexer_line_directive_probe.elisa" <<EOF
include "$REPO_ROOT/test/fixtures/lexer/frontend_lexer.elisa"

@test
def lexer_line_directive_filename_probe() -> void:
    can Memory.Allocate, Abort.Panic:
        assert frontend_case_line_directive_retargets_filename()
EOF

"$ELISACORE_BIN" -emit test "$WORK/lexer_line_directive_probe.elisa" >/dev/null
echo "lexer line-directive smoke OK"
