#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

invalid=$(printf 'const NEG_TO_U32: u32 = (-1.0).u32()\nconst NEG_U8_NEAR_ONE: u8 = (-0.999999999999999944488848768742172978818416595458984375).u8()\nconst BIG_TO_I8: i8 = 200.0.i8()\nconst NEG_BIG_TO_I8: i8 = (-129.0).i8()\nconst BIG_TO_I64: i64 = 9223372036854775808.0.i64()\nconst I64_POS_ROUNDING_MIDPOINT: i64 = 9223372036854775296.0.i64()\nconst NEG_BIG_TO_I64: i64 = (-9223372036854777856.0).i64()\nconst BIG_TO_U64: u64 = 18446744073709550592.0.u64()\nconst EXPONENT_TO_I8: i8 = 1e100.i8()\nconst EXPONENT_OVER_I8: i8 = 1.28e2.i8()\nconst DOUBLE_NEG_POSITIVE_OVERFLOW: i8 = (-(-128.0)).i8()\nconst ROUNDING_NEAR_I8_MAX: i8 = 127.999999999999999.i8()\nconst ROUNDING_NEAR_I8_MIN: i8 = (-128.99999999999999).i8()\n' | "$RPT")
for name in NEG_TO_U32 NEG_U8_NEAR_ONE BIG_TO_I8 NEG_BIG_TO_I8 BIG_TO_I64 I64_POS_ROUNDING_MIDPOINT NEG_BIG_TO_I64 BIG_TO_U64 EXPONENT_TO_I8 EXPONENT_OVER_I8 DOUBLE_NEG_POSITIVE_OVERFLOW ROUNDING_NEAR_I8_MAX ROUNDING_NEAR_I8_MIN; do
    grep -q "const \"$name\" initializer must be a compile-time" <<< "$invalid"
done

valid=$(printf 'const SMALL_I8: i8 = 127.0.i8()\nconst SMALL_I8_FRACTION: i8 = 127.9.i8()\nconst NEG_SMALL_I8_FRACTION: i8 = (-128.9).i8()\nconst SMALL_U8_FRACTION: u8 = 255.9.u8()\nconst DOUBLE_NEG_SMALL_I8: i8 = (-(-127.0)).i8()\nconst NEG_MIN_I8: i8 = (-128.0).i8()\nconst NEG_MIN_I64: i64 = (-9223372036854775808.0).i64()\nconst NEG_ROUNDS_TO_MIN_I64: i64 = (-9223372036854775809.0).i64()\nconst SAFE_PREVIOUS_I64: i64 = 9223372036854774784.0.i64()\nconst NEG_FRACTION_U32: u32 = (-0.9).u32()\nconst NEG_ZERO_U32: u32 = (-0.0).u32()\nconst U64_ABOVE_I64: u64 = 9223372036854775808.0.u64()\nconst EXP_SMALL_I8: i8 = 1e2.i8()\nconst EXP_TINY_I8: i8 = 1e-20.i8()\nconst EXP_AT_LIMIT_I8: i8 = 1.27e2.i8()\nconst SMALL_U32: u32 = 42.0.u32()\n' | "$RPT")
grep -q '^D 0$' <<< "$valid"

wasm32_invalid=$(printf 'const WASM32_INT_BOUNDARY: int = 2147483648.0.int()\nconst WASM32_USIZE_BOUNDARY: usize = 4294967296.0.usize()\nconst WASM32_INT_NEG_MIDPOINT: int = (-2147483648.9999997615814208984375).int()\nconst WASM32_ISIZE_NEG_MIDPOINT: isize = (-2147483648.9999997615814208984375).isize()\n' | ELISA_STAGE1_WASM=1 "$RPT")
for name in WASM32_INT_BOUNDARY WASM32_USIZE_BOUNDARY WASM32_INT_NEG_MIDPOINT WASM32_ISIZE_NEG_MIDPOINT; do
    grep -q "const \"$name\" initializer must be a compile-time" <<< "$wasm32_invalid"
done

wasm32_valid=$(printf 'const WASM32_INT_MIN: int = (-2147483648.0).int()\nconst WASM32_USIZE_MAX: usize = 4294967295.0.usize()\n' | ELISA_STAGE1_WASM=1 "$RPT")
grep -q '^D 0$' <<< "$wasm32_valid"

wasm64_valid=$(printf 'const WASM64_INT_CONTROL: int = 2147483648.0.int()\nconst WASM64_USIZE_CONTROL: usize = 4294967296.0.usize()\nconst WASM64_INT_NEG_MIDPOINT: int = (-2147483648.9999997615814208984375).int()\n' | env -u ELISA_STAGE1_WASM "$RPT")
grep -q '^D 0$' <<< "$wasm64_valid"

echo "const float cast smoke OK" >&2
