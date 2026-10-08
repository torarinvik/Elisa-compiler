#!/usr/bin/env bash
# Global authority is mandatory for mutable storage by default. The old gate
# compared opt-in advisory inference and asserted silence without -Wglobals;
# its replacement exercises actual direct/call rejection and selective grants.
set -euo pipefail
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/mutable_global_authority_smoke.sh" "$@"
