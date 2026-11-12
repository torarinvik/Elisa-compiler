#!/usr/bin/env bash
# A chained alias resolves its target's members only in its declaring scope.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

output="$("$RPT" <<'ELISA'
module Outer:
    public:
        module Nested:
            public:
                def good() -> i64:
                    return 1
module Client:
    using Outer as Root
    using Root::Nested as Alias
    def good() -> i64:
        return Alias::good()
    def bad() -> i64:
        return Alias::missing()
def outside() -> i64:
    return Alias::good()
ELISA
)"
[[ "$output" == *$'P 0\nD 2\n'* && "$output" == *'L13 undefined identifier "Alias.missing"'* && "$output" == *'L15 undefined identifier "Alias.good"'* ]] || {
    printf 'module alias member scope failed:\n%s\n' "$output" >&2
    exit 1
}
collision="$("$RPT" <<'ELISA'
module Alias:
    public:
        def good() -> i64: return 1
module Other:
    public:
        def good() -> i64: return 2
module Client:
    using Other as Alias
    def inside() -> i64: return Alias::good()
    module Nested:
        def inside_nested() -> i64: return Alias::good()
def outside() -> i64: return Alias::good()
ELISA
)"
[[ "$collision" == *$'P 0\nD 0'* ]] || {
    printf 'a local alias or root module was hidden by the same spelling:\n%s\n' "$collision" >&2
    exit 1
}

shadow="$("$RPT" <<'ELISA'
error Fault:
    Outer
    Inner
module A:
    public:
        def load() -> i64 error[Fault{Outer}]:
            return 1
module B:
    public:
        def load() -> i64 error[Fault{Inner}]:
            return 1
using A as X
module Client:
    using B as X
    def run() -> i64 error[Fault{Outer}]:
        return try X::load()
ELISA
)"
[[ "$shadow" == *$'P 0\nD 1\n'* && "$shadow" == *'cannot propagate Fault from a function returning Fault'* ]] || {
    printf 'nearest lexical alias did not select its error subset:\n%s\n' "$shadow" >&2
    exit 1
}

conflict="$("$RPT" <<'ELISA'
module A:
    def f() -> i64: return 1
module B:
    def f() -> i64: return 2
using A as X
using B as X
module C:
    using B as X
    def f() -> i64: return X::f()
ELISA
)"
[[ "$conflict" == *$'P 0\nD 1\n'* && "$conflict" == *'conflicting alias: "X"'* ]] || {
    printf 'only same-scope aliases should conflict:\n%s\n' "$conflict" >&2
    exit 1
}
unknown="$("$RPT" <<'ELISA'
module A:
    def f() -> i64: return 1
module B:
    def f() -> i64: return 2
static if UNKNOWN:
    using B as X
using A as X
ELISA
)"
if grep -q 'conflicting alias:' <<< "$unknown"; then
    printf 'an unresolved alias cannot establish a definite conflict:\n%s\n' "$unknown" >&2
    exit 1
fi

echo 'module alias member scope smoke OK'
