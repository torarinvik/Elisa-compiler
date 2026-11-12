#!/usr/bin/env bash
# Nested module qualifiers through aliases must respect scope and missing modules.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
output="$("$RPT" <<'ELISA'
module Outer:
    public:
        module Inner:
            public:
                module Deep:
                    public:
                        def ok() -> i64: return 1
using Outer as Root
using Root::Inner as Alias
def good() -> i64: return Alias::Deep::ok()
def missing() -> i64: return Alias::Unknown::ok()
module Client:
    using Root::Inner as Local
    def good() -> i64: return Local::Deep::ok()
def outside() -> i64: return Local::Deep::ok()
ELISA
)"
[[ "$output" == *$'P 0\nD 2\n'* && "$output" == *'L11 undefined identifier "Alias.Unknown"'* && "$output" == *'L15 undefined identifier "Local.Deep"'* ]] || {
    printf 'nested alias qualifier smoke failed:\n%s\n' "$output" >&2
    exit 1
}
echo 'nested alias qualifier smoke OK'
