#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

invalid=$(printf 'const NEG_TO_U32: u32 = (-1.0).u32()\nconst BIG_TO_I8: i8 = 200.0.i8()\nconst BIG_TO_I64: i64 = 9223372036854775808.0.i64()\nconst BIG_TO_U64: u64 = 9223372036854775808.0.u64()\n' | "$RPT")
for name in NEG_TO_U32 BIG_TO_I8 BIG_TO_I64 BIG_TO_U64; do
    printf '%s\n' "$invalid" | grep -q "const \"$name\" initializer must be a compile-time"
done

valid=$(printf 'const SMALL_I8: i8 = 127.0.i8()\nconst SMALL_U32: u32 = 42.0.u32()\n' | "$RPT")
printf '%s\n' "$valid" | grep -q '^D 0$'

echo "const float cast smoke OK" >&2
