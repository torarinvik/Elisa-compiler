#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LLVM_MC="${LLVM_MC:-$(command -v llvm-mc || true)}"
if [[ -z "$LLVM_MC" && -x /opt/homebrew/opt/llvm/bin/llvm-mc ]]; then
    LLVM_MC=/opt/homebrew/opt/llvm/bin/llvm-mc
fi
if [[ -z "$LLVM_MC" ]]; then
    echo "easm_template_assembler_smoke SKIP: llvm-mc not found"
    exit 0
fi
json="$("$ROOT/scripts/easm_assemble_template.py" "$ROOT/test/fixtures/easm/template_thunk.easm" --llvm-mc "$LLVM_MC" --triple x86_64-apple-darwin)"
case "$json" in
    *'"bytes":[102,65,140,226,65,82,102,65,186,0,0,65,142,226,73,187,0,0,0,0,0,0,0,0,65,255,211,65,90,65,142,226,195]'*) ;;
    *) echo "easm_template_assembler_smoke FAILED: unexpected image"; echo "$json"; exit 1 ;;
esac
case "$json" in
    *'"hole":"target","offset":16,"width":8'*'"hole":"host_fs","offset":9,"width":2'*) ;;
    *) echo "easm_template_assembler_smoke FAILED: unexpected patch points"; echo "$json"; exit 1 ;;
esac
echo "easm_template_assembler_smoke OK"
