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

indexed_report="$("$RPT" <<'ELISA'
global region source
struct SourceRows:
    rows: darray[sview @source]
struct BorrowedRows[@r]:
    rows: darray[sview @r]

def good_index[@r](table: SourceRows& @r) -> sview @source:
    for index in 0..<1:
        pass
    return table.rows[0]
def bad_index[@r](table: BorrowedRows[r]& @r) -> sview @source:
    return table.rows[0]
def bad_local[@r](table: BorrowedRows[r]& @r) -> sview @source:
    item: sview @source = table.rows[0]
    return item

def generic_good[@r](table: BorrowedRows[source]& @r) -> sview @source:
    return table.rows[0]
def shadowed_index[@source, @r](table: SourceRows& @r) -> sview @source:
    return table.rows[0]
ELISA
)"
grep -Fxq 'P 0' <<< "$indexed_report"
if grep -q '  L10 ' <<< "$indexed_report"; then
    printf 'source-backed indexed view rejected:\n%s\n' "$indexed_report" >&2
    exit 1
fi
if grep -q '  L18 ' <<< "$indexed_report"; then
    printf 'global region argument rejected:\n%s\n' "$indexed_report" >&2
    exit 1
fi
for line in 12 14 20; do
    if ! grep -q "  L$line .*region" <<< "$indexed_report"; then
        printf 'missing indexed-view lifetime diagnostic on line %s:\n%s\n' "$line" "$indexed_report" >&2
        exit 1
    fi
done
can_report="$("$RPT" <<'ELISA'
global region source
struct SourceRows:
    rows: darray[sview @source]
def guarded[@r](table: SourceRows& @r) -> sview @source:
    can Abort.Panic:
        for index in 0..<1:
            pass
        return table.rows[0]
def captured[@r](table: SourceRows& @r, bytes: darray[u8]&) -> sview @source:
    can Abort.Panic:
        hash: mutable u64 = 0
        for byte in bytes |hash|:
            hash <- hash + byte.u64()
        return table.rows[0]
ELISA
)"
grep -Fxq 'P 0' <<< "$can_report"
if ! grep -Fxq 'D 0' <<< "$can_report"; then
    printf 'source-backed indexed view in effect block rejected:\n%s\n' "$can_report" >&2
    exit 1
fi
shadow_report="$("$RPT" <<'ELISA'
global region source
struct SourceRows:
    rows: darray[sview @source]
struct ShortRows[@r]:
    rows: darray[sview @r]
def shadow_in_loop[@r](table: SourceRows& @r, others: darray[ShortRows[r]]&) -> sview @source:
    for table in others:
        return table.rows[0]
    return ""
ELISA
)"
grep -Fxq 'P 0' <<< "$shadow_report"
if ! grep -q '  L8 .*region' <<< "$shadow_report"; then
    printf 'missing lifetime diagnostic for a shadowed loop binding:\n%s\n' "$shadow_report" >&2
    exit 1
fi
assignment_report="$("$RPT" <<'ELISA'
global region source
struct SourceRows:
    rows: darray[sview @source]
struct BorrowedRows[@r]:
    rows: darray[sview @r]
def good[@r](table: SourceRows& @r) -> sview @source:
    item: mutable sview @source = ""
    item <- table.rows[0]
    return item
def bad[@r](table: BorrowedRows[r]& @r) -> sview @source:
    item: mutable sview @source = ""
    item <- table.rows[0]
    return item
ELISA
)"
grep -Fxq 'P 0' <<< "$assignment_report"
if grep -qE '  L(8|9) ' <<< "$assignment_report"; then
    printf 'source-backed reassignment rejected:\n%s\n' "$assignment_report" >&2
    exit 1
fi
if ! grep -q '  L12 .*region' <<< "$assignment_report"; then
    printf 'missing lifetime diagnostic for indexed reassignment:\n%s\n' "$assignment_report" >&2
    exit 1
fi
global_report="$("$RPT" <<'ELISA'
global region source
struct BorrowedRows[@r]:
    rows: darray[sview @r]
global mutable saved: sview = ""
def store_bad[@r](table: BorrowedRows[r]& @r) -> void:
    can Global.Write:
        saved <- table.rows[0]
def local_shadow[@r](table: BorrowedRows[r]& @r) -> void:
    saved: mutable sview @r = ""
    saved <- table.rows[0]
ELISA
)"
grep -Fxq 'P 0' <<< "$global_report"
if ! grep -q '  L7 value in region "r" is stored into "saved"' <<< "$global_report"; then
    printf 'missing lifetime diagnostic for a global store:\n%s\n' "$global_report" >&2
    exit 1
fi
if grep -q '  L10 .*stored into "saved", which outlives' <<< "$global_report"; then
    printf 'local shadow incorrectly treated as a global store:\n%s\n' "$global_report" >&2
    exit 1
fi
printf 'source-backed field return and lifetime controls OK\n'
