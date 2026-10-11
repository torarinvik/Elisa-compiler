#!/usr/bin/env bash
set -euo pipefail
# Keep the existing control in the full parity gate discovery.
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/incremental_name_uniqueness_control.sh" "$@"
