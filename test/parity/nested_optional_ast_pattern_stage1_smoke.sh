#!/usr/bin/env bash
# The nested optional AST-pattern path must branch on presence and never feed the
# tagged optional aggregate directly to the packed-store handle conversion.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/fixtures/backend/nested_optional_ast_match.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-nested-optional-pattern.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
if [[ -x "$LLVM_CONFIG" ]]; then
    LLVM_BIN_DIR="$("$LLVM_CONFIG" --bindir)"
    if [[ -x "$LLVM_BIN_DIR/opt" ]]; then
        "$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$SOURCE" >"$WORK/llvm.log" 2>&1 || {
            echo "FAIL Stage1 could not emit LLVM for the nested optional AST-pattern regression" >&2
            cat "$WORK/llvm.log" >&2
            exit 1
        }
        if grep -Eq 'zext[[:space:]]+\{[[:space:]]*i1,[[:space:]]*i32[[:space:]]*\}.*to i64' "$WORK/stage1.ll"; then
            echo "FAIL Stage1 cast a tagged optional aggregate to an integer handle" >&2
            exit 1
        fi
        "$LLVM_BIN_DIR/opt" -passes=verify -disable-output "$WORK/stage1.ll"
    else
        echo "nested optional AST-pattern: LLVM opt unavailable; skipping direct IR verifier"
    fi
else
    echo "nested optional AST-pattern: llvm-config unavailable; skipping direct IR verifier"
fi
"$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$SOURCE" >"$WORK/stage1.log" 2>&1 || {
    echo "FAIL Stage1 rejected the nested optional AST-pattern regression" >&2
    cat "$WORK/stage1.log" >&2
    exit 1
}
"$WORK/stage1" || {
    status=$?
    echo "FAIL nested optional AST-pattern execution returned $status, expected 0" >&2
    exit 1
}

echo "nested optional AST-pattern Stage1 verifier regression OK"
