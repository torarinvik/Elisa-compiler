#!/usr/bin/env bash
# Install the self-hosted compiler as `elisac-stage1` on PATH (~/.elisac).
#
# The product is not a drop-in binary: scripts/elisac_stage1.sh owns the stdin
# request protocol, the runtime object and the LLVM tool lookup. So what gets
# installed is a forwarding wrapper bound to THIS worktree -- after any
# `--seed` the installed compiler is automatically the new product, and
# `elisac-stage1 --seed` rebuilds it. The Go compiler installs beside it as
# `elisac-stage0` (Elisa-core compiler/githooks/install-elisac.sh); the two
# names say which compiler a command line is using.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${HOME}/.elisac"
cat > "${HOME}/.elisac/elisac-stage1" <<WRAPPER
#!/usr/bin/env bash
# elisac-stage1: the self-hosted Elisa compiler, forwarded to its driver.
# Installed by ${ROOT}/scripts/install_stage1.sh
exec bash "${ROOT}/scripts/elisac_stage1.sh" "\$@"
WRAPPER
chmod +x "${HOME}/.elisac/elisac-stage1"
echo "installed elisac-stage1 -> ${ROOT} ($(git -C "$ROOT" rev-parse --short HEAD))"
