#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

wildcard=$(printf 'error FileError:\n    NotFound\nextern read_value() -> int error[FileError.*]\n' | "$RPT")
grep -Fq 'error[Set.*] is no longer supported; use error[Set] instead' <<< "$wildcard"

pipe=$(printf 'error IoError:\n    NotFound\nextern read_file(path: u8&) -> int | IoError\n' | "$RPT")
grep -Fq 'legacy fallible return syntax `T | ErrorSet` is no longer supported' <<< "$pipe"

valid=$(printf 'def bits(x: int, y: int) -> int:\n    return x | y\n' | "$RPT")
grep -q '^D 0$' <<< "$valid"

echo "legacy error syntax smoke OK" >&2
