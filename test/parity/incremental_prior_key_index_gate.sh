#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# Each control uses the same explicitly selected, fresh candidate product.
for control in incremental_name_uniqueness_control incremental_prior_key_index_control incremental_codec_integrity_control incremental_ga_reuse_control incremental_ga_cache_control incremental_shadow_gate_control; do
    bash "$ROOT/test/parity/$control.sh"
done
