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

view_report="$("$RPT" <<'ELISA'
global region source
struct SourceBuffer:
    bytes: darray[u8] @source
struct Borrowed[@r]:
    bytes: darray[u8] @r

def view_bytes(bytes: darray[u8], start: usize, count: usize) -> sview:
    return ""
def choose_view(first: darray[u8], second: darray[u8]) -> sview:
    return ""

def good_view[@r](buffer: SourceBuffer& @r) -> sview @source:
    return view_bytes(buffer.bytes, 0, buffer.bytes.count)
def bad_view[@r](buffer: SourceBuffer& @r, other: Borrowed[r]& @r) -> sview @source:
    return choose_view(buffer.bytes, other.bytes)
ELISA
)"
grep -Fxq 'P 0' <<< "$view_report"
if grep -q '  L13 ' <<< "$view_report"; then
    printf 'source-backed view rejected:\n%s\n' "$view_report" >&2
    exit 1
fi
if ! grep -q '  L15 .*region' <<< "$view_report"; then
    printf 'missing lifetime diagnostic for independent view argument:\n%s\n' "$view_report" >&2
    exit 1
fi
printf 'source-backed field return and lifetime controls OK\n'
