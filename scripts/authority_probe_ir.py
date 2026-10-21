#!/usr/bin/env python3
"""Limit clang -O1 to authority walkers in a Core-generated probe's LLVM IR.

Development probe only. Normal attribute-group-0 functions outside this hot set
receive optnone/noinline; existing special attributes and all LLVM bodies remain
intact. Compile the output with LLVM clang -O1, using the usual command timeout.
"""
import argparse
import re
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
parser.add_argument("--packed-reads", action="store_true", help="also optimize the two packed AST record-read helpers")
parser.add_argument("--context-lookups", action="store_true", help="also optimize packed-context hash and string-index helpers")
parser.add_argument("--lookup-tables", action="store_true", help="also optimize dictionary probes, string equality, and semantic name hashing")
args = parser.parse_args()
source, destination = args.source, args.destination
if source.resolve() == destination.resolve():
    raise SystemExit("Input and output must be different files")
maximum = -1
base_attributes = None
with source.open() as stream:
    for line in stream:
        match = re.match(r"attributes #(\d+) =", line)
        if match:
            maximum = max(maximum, int(match[1]))
        base = re.fullmatch(r"attributes #0 = \{(.*)\}\s*", line)
        if base:
            base_attributes = base[1].strip()
if maximum < 0 or base_attributes is None:
    raise SystemExit("No LLVM attribute group 0 found")
attribute_names = re.sub(r'"(?:\\.|[^"\\])*"', '""', base_attributes)
if re.search(r"\b(alwaysinline|optnone)\b", attribute_names):
    raise SystemExit("Attribute group 0 must permit normal optimization")
cold_attributes = base_attributes + " optnone"
if not re.search(r"\bnoinline\b", attribute_names):
    cold_attributes += " noinline"
group = maximum + 1
hot = cold = authority_hot = 0
with source.open() as stream, destination.open("w") as output:
    for line in stream:
        if line.startswith("define ") and line.rstrip().endswith("#0 {"):
            is_authority = any(prefix in line for prefix in (
                "@Semantic.ga_", '@"Semantic_ga_', "@SemanticGlobalAuthority",
            ))
            is_context_lookup = any(name in line for name in (
                "@ctx_hash_cstr(", "@ctx_hash_sview(", "@ctx_hash_u64(",
                "@ctx_unhash_u64(", "@ctx_unhash_xor_31(", "@ctx_unhash_xor_27(",
                "@ctx_unhash_xor_30(", "@ctx_unhash_mul_1(", "@ctx_unhash_mul_2(",
                "@ctx_string_view_index(", "@string_view_index(",
            ))
            is_lookup_table = any(name in line for name in (
                '@"arena_dict_find_index$generic_v1$', "@arena_dict_find_index(",
                "@ctx_string_views_eq(", "@Semantic.name_hash(",
            ))
            if is_authority or (args.context_lookups and is_context_lookup) or (args.lookup_tables and is_lookup_table) or (args.packed_reads and any(name in line for name in (
                "@ctx_aos_store_record(", "@ctx_aos_store_sized_record(",
            ))):
                hot += 1
                authority_hot += int(is_authority)
            else:
                line = line.replace("#0 {", f"#{group} {{")
                cold += 1
        output.write(line)
    output.write(f"\nattributes #{group} = {{ {cold_attributes} }}\n")
if not authority_hot:
    destination.unlink()
    raise SystemExit("No authority functions found; refusing a misleading probe")
print(f"authority IR: {hot} hot functions, {cold} unoptimized functions")
