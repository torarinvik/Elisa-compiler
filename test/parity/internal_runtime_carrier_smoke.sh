#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

output=$(printf 'extern take_view(view: StringView) -> void\nextern take_raw[T](values: DynArray[T]) -> void\nextern take_window(view: DynArrayView) -> void\n' | "$RPT")
grep -q 'internal runtime carrier type "StringView".*use "sview\[\.\.\.\]"' <<< "$output"
grep -q 'internal runtime carrier type "DynArray".*use "darray\[T, shape\]"' <<< "$output"
grep -q 'internal runtime carrier type "DynArrayView".*use "view\[T\]"' <<< "$output"

canonical=$(printf 'extern take_view(view: sview) -> void\nextern take_raw[T](values: darray[T]) -> void\nextern take_window[T](view: view[T]) -> void\n' | "$RPT")
grep -q '^D 0$' <<< "$canonical"

echo "internal runtime carrier smoke OK" >&2
