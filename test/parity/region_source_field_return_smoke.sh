#!/usr/bin/env bash
# A copied scalar-container descriptor follows its field's arena, while a
# borrow of the field or reference-bearing contents must keep their lifetime.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" <<'ELISA'
global region source
struct SourceBuffer:
    bytes: darray[u8] @source
    refs: darray[u8&] @source
struct Borrowed[@r]:
    bytes: darray[u8] @r

def good[@r](buffer: SourceBuffer& @r) -> darray[u8] @source:
    return buffer.bytes

def bad_borrow[@r](buffer: SourceBuffer& @r) -> u8& @source:
    return &buffer.bytes[0]

def bad_elements[@r](buffer: SourceBuffer& @r) -> darray[u8&] @source:
    return buffer.refs

def bad_region[@r](buffer: Borrowed[r]& @r) -> darray[u8] @source:
    return buffer.bytes

def shadow[@source, @r](buffer: SourceBuffer& @r) -> darray[u8] @source:
    return buffer.bytes
ELISA
)"
grep -Fxq 'P 0' <<< "$report"
if grep -q '  L9 ' <<< "$report"; then
    printf 'source-backed scalar field rejected:\n%s\n' "$report" >&2
    exit 1
fi
for line in 12 15 18 21; do
    if ! grep -q "  L$line .*region" <<< "$report"; then
        printf 'missing lifetime diagnostic on line %s:\n%s\n' "$line" "$report" >&2
        exit 1
    fi
done
printf 'source-backed field return and lifetime controls OK\n'
