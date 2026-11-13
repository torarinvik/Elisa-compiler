#!/usr/bin/env bash
# Unordered synthetic annotations must be sorted stably before range lookup.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
work="$(mktemp -d "${TMPDIR:-/tmp}/elisa-ast-using-order.XXXXXX")"
trap 'rm -rf "$work"' EXIT
"$STAGE1" -emit obj -O0 -permissive -o "$work/probe.o" "$ROOT/test/parity/ast_using_order_probe.elisa"
link_flags=()
case "$(uname -s)" in
  Darwin) link_flags=(-Wl,-undefined,dynamic_lookup -Wl,-stack_size,0x20000000) ;;
  Linux) link_flags=(-no-pie) ;;
esac
clang -O2 "${link_flags[@]}" "$work/probe.o" "$RUNTIME" "$ROOT/test/parity/profile_hooks.c" -o "$work/probe"
"$work/probe"
echo 'AST import annotations are stably ordered by source offset'
