# shellcheck shell=bash
# Resolve a CURRENT elisac binary for the parity / bench harnesses.
# Sourced (not executed) — sets $ELISACORE_BIN in the caller's shell.
#
# Default behavior: build the compiler from $ELISA_CORE/compiler so we ALWAYS
# run the latest source rather than a possibly-stale prebuilt binary (the old
# $ELISA_CORE/bin/elisacore default was a frequent stale-binary trap). The Go
# build is incremental (~2s when nothing changed), so this is cheap to do every
# run.
#
# Escape hatch: set ELISACORE_BIN to an explicit path to skip the build and use
# that binary as-is (e.g. to test against a specific/older compiler). Set
# ELISAC_OUT to change where the fresh build is written (default ~/.elisac/elisac,
# matching `make build`).
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
	ELISACORE_BIN="${ELISAC_OUT:-$HOME/.elisac/elisac}"
	echo "building latest elisac from $ELISA_CORE/compiler -> $ELISACORE_BIN" >&2
	( cd "$ELISA_CORE/compiler" && go build -o "$ELISACORE_BIN" ./src )
fi
