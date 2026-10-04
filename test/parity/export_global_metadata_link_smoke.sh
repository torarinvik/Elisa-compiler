#!/usr/bin/env bash
# LSP declaration metadata must not be mistaken for an `export global` alias. The
# resulting object is linked against the compiler runtime, which carries the same
# declaration metadata and exposed duplicate LLVM aliases before the backend fix.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
bash "$ROOT/scripts/build_runtime_object.sh" >/dev/null

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-export-global-metadata.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/probe.elisa" <<'SRC'
global lsp_alias_probe: i64 = 40
global exported_probe: i64 = 7
export global exported_probe as ctx_exported_probe

def main() -> i64:
    return lsp_alias_probe + 2
SRC

"$STAGE1" -emit obj -O0 -o "$WORK/probe.o" "$WORK/probe.elisa" >/dev/null
nm -g "$WORK/probe.o" | awk '$NF == "_ctx_exported_probe" || $NF == "ctx_exported_probe" { found = 1 } END { exit !found }' || {
    echo "export-global metadata link FAIL: explicit public alias was not emitted" >&2
    exit 1
}
"${ELISA_CLANG:-clang}" -o "$WORK/probe" "$WORK/probe.o" "$RUNTIME_OBJ"

set +e
"$WORK/probe"
status=$?
set -e
if [[ "$status" != 42 ]]; then
    echo "export-global metadata link FAIL: probe exited $status, expected 42" >&2
    exit 1
fi

echo "export-global metadata link OK: ordinary metadata is not aliased and explicit public aliases remain exported"
