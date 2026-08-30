#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

type_bad=$(printf 'struct Vec:\n    x: i32\nexport type Vec as VecFFI\n' | "$RPT")
printf '%s\n' "$type_bad" | grep -q 'must name a concrete C-ABI-compatible struct'

global_bad=$(printf 'const MAGIC = 1337\nexport global MAGIC as ctx_magic\n' | "$RPT")
printf '%s\n' "$global_bad" | grep -q 'must target a global'

array_bad=$(printf 'def pass_array(value: i32[4]) -> i32[4]:\n    return value\nexport fn pass_array_c(value: i32[4]) -> i32[4] = pass_array\n' | "$RPT")
printf '%s\n' "$array_bad" | grep -q 'is not C-ABI-compatible'

valid=$(printf 'struct Vec[T] layout(c):\n    x: mutable T\nexport type Vec[i32] as Vec2i\nglobal seed: i32 = 7\nexport global seed as ctx_seed\n' | "$RPT")
printf '%s\n' "$valid" | grep -q '^D 0$'

echo "export boundary smoke OK" >&2
