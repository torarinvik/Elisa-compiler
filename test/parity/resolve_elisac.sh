# shellcheck shell=bash
# Resolve a CURRENT elisac binary for the parity / bench harnesses.
# Sourced (not executed) — sets $ELISACORE_BIN in the caller's shell.
#
# Default behavior: use the Stage0 binary when its provenance receipt matches the
# current source, and rebuild from $ELISA_CORE/compiler only when it does not. A
# matching receipt means the binary was built from exactly this source with the
# canonical recipe, so rebuilding would only churn bytes and invalidate any Stage1
# seed recorded against it.
#
# Escape hatch: set ELISACORE_BIN to an explicit path to skip the build and use
# that binary as-is (e.g. to test against a specific/older compiler). Set
# ELISAC_OUT to change where the fresh build is written (default is the local
# compiler/bin/elisac inside ELISA_CORE, matching the worktree-local `make build`).
#
# Requires $ELISA_CORE to be set before sourcing.
: "${ELISA_CORE:?resolve_elisac.sh: ELISA_CORE must be set before sourcing}"

if [[ -n "${ELISACORE_BIN:-}" ]]; then
	command -v "$ELISACORE_BIN" >/dev/null 2>&1 || [[ -x "$ELISACORE_BIN" ]] || {
		echo "error: ELISACORE_BIN is not executable: $ELISACORE_BIN" >&2
		exit 2
	}
	echo "using pinned elisac: $ELISACORE_BIN (skipping build)" >&2
else
	command -v go >/dev/null 2>&1 || { echo "error: missing 'go' (needed to build the latest elisac)" >&2; exit 2; }
	ELISACORE_BIN="${ELISAC_OUT:-$ELISA_CORE/compiler/bin/elisac}"
	REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
	mkdir -p "$(dirname "$ELISACORE_BIN")"
	if env -i HOME="$HOME" PATH="$PATH" TMPDIR="${TMPDIR:-/tmp}" LANG=en_US.UTF-8 python3 "$REPO_ROOT/scripts/stage0_provenance.py" check --root "$ELISA_CORE/compiler" --binary "$ELISACORE_BIN" >/dev/null 2>&1; then
		echo "Stage0 provenance is current: $ELISACORE_BIN" >&2
	else
		echo "building latest elisac from $ELISA_CORE/compiler -> $ELISACORE_BIN" >&2
		env -i HOME="$HOME" PATH="$PATH" TMPDIR="${TMPDIR:-/tmp}" LANG=en_US.UTF-8 python3 "$REPO_ROOT/scripts/stage0_provenance.py" build --root "$ELISA_CORE/compiler" --binary "$ELISACORE_BIN" || exit 2
	fi
	export ELISA_STAGE0_SOURCE_ROOT="$ELISA_CORE/compiler"
fi
