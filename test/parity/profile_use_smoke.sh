#!/usr/bin/env bash
# Profile-use smoke: the self-hosted CLI accepts the compiler-facing profile format and
# forwards its complete hot-function records into LLVM function attributes.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
BUILD="${ELISA_PROFILE_USE_BUILD:-$ROOT/build/profile-use-smoke}"
mkdir -p "$BUILD"

if ! "$STAGE1_BIN" -emit llvm -O0 -o "$BUILD/profile.ll" \
    -fprofile-use "$ROOT/test/repro/profile_use_smoke.elisapgo" \
    "$ROOT/test/repro/profile_use_smoke.elisa" >/dev/null 2>"$BUILD/profile.err"; then
    echo "profile_use_smoke FAILED: stage1 rejected a valid profile" >&2
    sed -n '1,40p' "$BUILD/profile.err" >&2
    exit 1
fi

if ! grep -Eq '^attributes #[0-9]+ = \{ hot noinline nounwind \}' "$BUILD/profile.ll"; then
    echo "profile_use_smoke FAILED: hot profile was not applied" >&2
    exit 1
fi
if ! grep -Eq '^attributes #[0-9]+ = \{ cold nounwind \}' "$BUILD/profile.ll"; then
    echo "profile_use_smoke FAILED: explicit cold annotation was not preserved" >&2
    exit 1
fi

if "$STAGE1_BIN" -emit llvm -O0 -o "$BUILD/invalid.ll" \
    -fprofile-use "$ROOT/test/repro/profile_use_smoke.elisa" \
    "$ROOT/test/repro/profile_use_smoke.elisa" >/dev/null 2>"$BUILD/invalid.err"; then
    echo "profile_use_smoke FAILED: malformed profile was accepted" >&2
    exit 1
fi

echo "profile_use_smoke OK"
