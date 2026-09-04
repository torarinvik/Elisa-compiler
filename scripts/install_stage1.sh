#!/usr/bin/env bash
# Install the self-hosted compiler as `elisac-stage1` on PATH (~/.elisac).
#
# BY DEFAULT THIS TAKES A SNAPSHOT, it does not point at this worktree. The
# product is not a drop-in binary -- scripts/elisac_stage1.sh owns include
# expansion, the runtime object and the LLVM tool lookup -- so the snapshot is a
# copy of the whole compiler root the driver expects: bin/, build/runtime/,
# scripts/, src/ and elisacore_std/.
#
# WHY A COPY. A wrapper bound to a live worktree makes every consumer share a
# development tree. Editing the compiler then changes other people's builds
# underneath them, and a source file newer than the product trips the staleness
# guard, so an unrelated project fails to build for a reason its own tree cannot
# explain. Both happened. A snapshot moves only when someone runs this script.
#
# `--link` restores the old behaviour (a wrapper bound to THIS worktree) for
# working on the compiler itself, where picking up every `--seed` is the point.
#
# The Go compiler installs beside it as `elisac-stage0` (Elisa-core
# compiler/githooks/install-elisac.sh); the two names say which compiler a
# command line is using.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${ELISAC_PREFIX:-${HOME}/.elisac}"
MODE="snapshot"
[[ "${1:-}" == "--link" ]] && MODE="link"

mkdir -p "$PREFIX"
REVISION="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"

if [[ "$MODE" == "link" ]]; then
    cat > "$PREFIX/elisac-stage1" <<WRAPPER
#!/usr/bin/env bash
# elisac-stage1: the self-hosted Elisa compiler, forwarded to its driver.
# LIVE LINK to a development worktree -- it changes when that worktree does.
# Installed by ${ROOT}/scripts/install_stage1.sh --link
exec bash "${ROOT}/scripts/elisac_stage1.sh" "\$@"
WRAPPER
    chmod +x "$PREFIX/elisac-stage1"
    echo "installed elisac-stage1 -> LIVE ${ROOT} (${REVISION})"
    exit 0
fi

[[ -x "$ROOT/bin/elisac-stage1" ]] || { echo "no product at $ROOT/bin/elisac-stage1 -- run scripts/elisac_stage1.sh --seed first" >&2; exit 2; }
[[ -f "$ROOT/build/runtime/elisacore_runtime.o" ]] || { echo "no runtime object at $ROOT/build/runtime/elisacore_runtime.o" >&2; exit 2; }

STAGING="$PREFIX/.stage1.incoming.$$"
rm -rf "$STAGING"
mkdir -p "$STAGING/bin" "$STAGING/build/runtime"
# Sources first, product LAST: the driver's staleness guard compares source
# mtimes against the binary, and a copy that lands the other way round would
# install a snapshot that refuses to run.
cp -R "$ROOT/src" "$STAGING/src"
cp -R "$ROOT/elisacore_std" "$STAGING/elisacore_std"
cp -R "$ROOT/scripts" "$STAGING/scripts"
cp "$ROOT/build/runtime/elisacore_runtime.o" "$STAGING/build/runtime/elisacore_runtime.o"
cp "$ROOT/bin/elisac-stage1" "$STAGING/bin/elisac-stage1"
touch "$STAGING/bin/elisac-stage1"
cat > "$STAGING/SNAPSHOT" <<META
revision: ${REVISION}
taken:    $(date -u +%Y-%m-%dT%H:%M:%SZ)
from:     ${ROOT}
META

# Swap it in. A consumer running during the swap keeps the directory it already
# opened; the next invocation gets the new one.
if [[ -d "$PREFIX/stage1" ]]; then
    rm -rf "$PREFIX/.stage1.previous"
    mv "$PREFIX/stage1" "$PREFIX/.stage1.previous"
fi
mv "$STAGING" "$PREFIX/stage1"
rm -rf "$PREFIX/.stage1.previous"

cat > "$PREFIX/elisac-stage1" <<WRAPPER
#!/usr/bin/env bash
# elisac-stage1: the self-hosted Elisa compiler.
# A SNAPSHOT taken from ${ROOT} at ${REVISION}; see ${PREFIX}/stage1/SNAPSHOT.
# It does not change when that worktree does -- re-run install_stage1.sh to move it.
exec bash "${PREFIX}/stage1/scripts/elisac_stage1.sh" "\$@"
WRAPPER
chmod +x "$PREFIX/elisac-stage1"

# A stable path for downstream link lines: an object emitted by this compiler
# references the Elisa runtime, and every consumer otherwise has to go hunting
# for it inside a worktree.
cp "$PREFIX/stage1/build/runtime/elisacore_runtime.o" "$PREFIX/elisacore_runtime.o"

echo "installed elisac-stage1 -> SNAPSHOT ${PREFIX}/stage1 (${REVISION})"
echo "runtime object          -> ${PREFIX}/elisacore_runtime.o"
