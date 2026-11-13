#!/usr/bin/env bash
# The runtime mode permits implicit field-reference returns, while explicit
# region ties still cannot be erased.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

check_report() {
    local expected="$1" out
    out="$("$RPT")"
    grep -q '^P 0$' <<< "$out"
    if [[ "$expected" == accept ]]; then
        grep -q '^D 0$' <<< "$out" || { printf 'unexpected runtime-region diagnostic:\n%s\n' "$out" >&2; return 1; }
    else
        grep -Fq 'value tied to region parameter' <<< "$out" || { printf 'missing region diagnostic:\n%s\n' "$out" >&2; return 1; }
    fi
}

check_report accept <<'ELISA'
# std
struct S:
    xs: mutable darray[u32]
def get(s: mutable S&) -> mutable darray[u32]&:
    return &s.xs
ELISA
check_report reject <<'ELISA'
struct S:
    xs: mutable darray[u32]
def get(s: mutable S&) -> mutable darray[u32]&:
    return &s.xs
ELISA
check_report reject <<'ELISA'
# std
struct S:
    xs: mutable darray[u32]
def get[@r](s: mutable S& @r) -> mutable darray[u32]&:
    return &s.xs
ELISA
check_report accept <<'ELISA'
# std
struct S:
    xs: mutable darray[u32]
def get[@r](s: mutable S& @r) -> mutable darray[u32]& @r:
    return &s.xs
ELISA
echo 'runtime region field return OK'
