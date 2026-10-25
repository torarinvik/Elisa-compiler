#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/test/proofs/check_view_return_generic_owner_identity.py"
python3 "$ROOT/test/parity/compiler_atoms_smoke.py" \
  semantic pymodule_struct_typedef try_fallback_source authority_coverage \
  authority_annotation_index iterator_alias_resolution \
  holder_view_wrappers holder_comprehension_alias try_fallible_entry \
  catch_marker_identity \
  catch_totality_offset_identity \
  errorset_wrapper_return_visibility \
  cast_constant_truncated
