"""Bind reference initializer typestate widening to its production classifier."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check production and proof bindings without Elisa-Proof replay")
ARGS = parser.parse_args()
from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/reference_initializer_compatibility.elisa"
UNIQUE_POLICY = ROOT / "src/semantic/reference_initializer_typestate_unique.elisa"
INITIALIZERS = ROOT / "src/semantic/resolve_types_initializers.elisa"
SEMANTIC_TYPES = ROOT / "src/semantic/semantic_types.elisa"
POSITIVE = HERE / "reference_initializer_compatibility.elisa"
NEGATIVE = HERE / "reference_initializer_compatibility_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(
        rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(",
        source[match.end():],
    )
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def struct_fields(source: str, name: str) -> dict[str, str]:
    lines = source.splitlines()
    declaration = re.compile(rf"^( *)struct {re.escape(name)}:\s*$")
    for index, line in enumerate(lines):
        match = declaration.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        fields: dict[str, str] = {}
        for field_line in lines[index + 1:]:
            if not field_line.strip() or field_line.lstrip().startswith("#"):
                continue
            field_indent = len(field_line) - len(field_line.lstrip(" "))
            if field_indent <= indent:
                break
            if field_indent != indent + 4:
                continue
            field = re.match(r"^\s*([A-Za-z_]\w*):\s*(.*?)\s*$", field_line)
            if field:
                field_type = re.sub(r"\s*=\s*.*$", "", field.group(2)).strip()
                fields[field.group(1)] = re.sub(r"\s+", "", field_type)
        return fields
    raise SystemExit(f"struct {name} not found")


def enum_variants(source: str, name: str) -> list[str]:
    lines = source.splitlines()
    declaration = re.compile(rf"^( *)const enum {re.escape(name)} of u8:\s*$")
    for index, line in enumerate(lines):
        match = declaration.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        variants: list[str] = []
        for variant_line in lines[index + 1:]:
            if not variant_line.strip() or variant_line.lstrip().startswith("#"):
                continue
            variant_indent = len(variant_line) - len(variant_line.lstrip(" "))
            if variant_indent <= indent:
                break
            if variant_indent == indent + 4:
                variants.append(variant_line.strip())
        return variants
    raise SystemExit(f"const enum {name} not found")


POSITIVE_SHAPES = {
    "production_unique_name_classifier_matches_its_spec": """def production_unique_name_classifier_matches_its_spec(table: Semantic::SymbolTable&, name: sview) -> bool:
    ensure result == true
    return SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, name) == SemanticReferenceInitializerTypestate::unique_named_typestate_struct_spec(table, name)
""",
    "a_single_named_struct_with_a_typestate_marker_is_unique": """def a_single_named_struct_with_a_typestate_marker_is_unique() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Struct}], typestate_struct_names: ["Player"]}
    return SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "duplicate_same_named_structs_are_ambiguous": """def duplicate_same_named_structs_are_ambiguous() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Struct}, Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Struct}], typestate_struct_names: ["Player"]}
    return not SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "unrelated_struct_names_do_not_break_uniqueness": """def unrelated_struct_names_do_not_break_uniqueness() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [Semantic::Symbol{name: "Other", kind: Semantic::SymbolKind::Struct}, Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Struct}], typestate_struct_names: ["Player"]}
    return SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "an_unregistered_struct_name_is_not_a_typestate": """def an_unregistered_struct_name_is_not_a_typestate() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Struct}], typestate_struct_names: []}
    return not SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "a_nonstruct_declaration_does_not_satisfy_the_typestate_gate": """def a_nonstruct_declaration_does_not_satisfy_the_typestate_gate() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Enum}], typestate_struct_names: ["Player"]}
    return not SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "an_empty_symbol_table_has_no_unique_typestate": """def an_empty_symbol_table_has_no_unique_typestate() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [], typestate_struct_names: ["Player"]}
    return not SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "a_same_named_nonstruct_does_not_make_the_struct_ambiguous": """def a_same_named_nonstruct_does_not_make_the_struct_ambiguous() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Struct}, Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Enum}], typestate_struct_names: ["Player"]}
    return SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "production_widening_classifier_matches_its_spec": """def production_widening_classifier_matches_its_spec(expected_is_named: bool, actual_is_container: bool, same_nominal_name: bool, unique_typestate: bool) -> bool:
    ensure result == true
    return SemanticReferenceInitializerCompatibility::typestate_widening_allowed(expected_is_named, actual_is_container, same_nominal_name, unique_typestate) == SemanticReferenceInitializerCompatibility::typestate_widening_spec(expected_is_named, actual_is_container, same_nominal_name, unique_typestate)
""",
    "a_unique_same_named_typestate_can_widen": """def a_unique_same_named_typestate_can_widen() -> bool:
    ensure result == true
    return SemanticReferenceInitializerCompatibility::typestate_widening_allowed(true, true, true, true)
""",
    "widening_requires_a_named_expected_target": """def widening_requires_a_named_expected_target() -> bool:
    ensure result == true
    return not SemanticReferenceInitializerCompatibility::typestate_widening_allowed(false, true, true, true)
""",
    "widening_requires_an_unqualified_container_actual_target": """def widening_requires_an_unqualified_container_actual_target() -> bool:
    ensure result == true
    return not SemanticReferenceInitializerCompatibility::typestate_widening_allowed(true, false, true, true)
""",
    "widening_requires_the_same_nominal_name": """def widening_requires_the_same_nominal_name() -> bool:
    ensure result == true
    return not SemanticReferenceInitializerCompatibility::typestate_widening_allowed(true, true, false, true)
""",
    "widening_requires_unique_typestate_declaration": """def widening_requires_unique_typestate_declaration() -> bool:
    ensure result == true
    return not SemanticReferenceInitializerCompatibility::typestate_widening_allowed(true, true, true, false)
""",
}
NEGATIVE_SHAPES = {
    "duplicate_same_named_structs_are_unique": """def duplicate_same_named_structs_are_unique() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Struct}, Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Struct}], typestate_struct_names: ["Player"]}
    return SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "an_unregistered_struct_can_be_a_typestate": """def an_unregistered_struct_can_be_a_typestate() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Struct}], typestate_struct_names: []}
    return SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "an_enum_declaration_can_satisfy_the_typestate_gate": """def an_enum_declaration_can_satisfy_the_typestate_gate() -> bool:
    ensure result == true
    table: Semantic::SymbolTable = Semantic::SymbolTable{symbols: [Semantic::Symbol{name: "Player", kind: Semantic::SymbolKind::Enum}], typestate_struct_names: ["Player"]}
    return SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table, "Player")
""",
    "a_generic_container_reference_can_widen": """def a_generic_container_reference_can_widen() -> bool:
    ensure result == true
    return SemanticReferenceInitializerCompatibility::typestate_widening_allowed(false, true, true, true)
""",
    "a_different_nominal_name_can_widen": """def a_different_nominal_name_can_widen() -> bool:
    ensure result == true
    return SemanticReferenceInitializerCompatibility::typestate_widening_allowed(true, true, false, true)
""",
    "an_ambiguous_typestate_name_can_widen": """def an_ambiguous_typestate_name_can_widen() -> bool:
    ensure result == true
    return SemanticReferenceInitializerCompatibility::typestate_widening_allowed(true, true, true, false)
""",
}


def with_abort_panic(shape: str) -> str:
    lines = shape.splitlines()
    ensure_line = next(index for index, line in enumerate(lines) if line.startswith("    ensure "))
    return "\n".join(
        lines[:ensure_line + 1]
        + ["    can Abort.Panic:"]
        + [f"    {line}" for line in lines[ensure_line + 1:]]
    ) + "\n"


for name in (
    "production_unique_name_classifier_matches_its_spec",
    "a_single_named_struct_with_a_typestate_marker_is_unique",
    "duplicate_same_named_structs_are_ambiguous",
    "unrelated_struct_names_do_not_break_uniqueness",
    "an_unregistered_struct_name_is_not_a_typestate",
    "a_nonstruct_declaration_does_not_satisfy_the_typestate_gate",
    "an_empty_symbol_table_has_no_unique_typestate",
    "a_same_named_nonstruct_does_not_make_the_struct_ambiguous",
):
    POSITIVE_SHAPES[name] = with_abort_panic(POSITIVE_SHAPES[name])
for name in (
    "duplicate_same_named_structs_are_unique",
    "an_unregistered_struct_can_be_a_typestate",
    "an_enum_declaration_can_satisfy_the_typestate_gate",
):
    NEGATIVE_SHAPES[name] = with_abort_panic(NEGATIVE_SHAPES[name])


for path, shapes in ((POSITIVE, POSITIVE_SHAPES), (NEGATIVE, NEGATIVE_SHAPES)):
    if declarations(path) != set(shapes):
        raise SystemExit(f"reference-initializer theorem inventory changed in {path.name}")
    source = path.read_text()
    for name, expected in shapes.items():
        if compact(function_section(source, name)) != compact(expected):
            raise SystemExit(f"reference-initializer theorem changed its exact claim: {name}")

if 'include "../../src/semantic/reference_initializer_compatibility.elisa"' not in POSITIVE.read_text():
    raise SystemExit("reference-initializer proof no longer imports the production widening policy")
if 'include "../../src/semantic/reference_initializer_typestate_unique.elisa"' not in POSITIVE.read_text():
    raise SystemExit("reference-initializer proof no longer imports the production uniqueness scan")
if 'include "./reference_initializer_compatibility.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("reference-initializer false controls no longer inherit the positive claims")

proof_projection = POSITIVE.read_text()
actual_semantic_types = SEMANTIC_TYPES.read_text()
expected_symbol_fields = {"name": "sview@source", "kind": "SymbolKind"}
for field, expected in expected_symbol_fields.items():
    if struct_fields(actual_semantic_types, "Symbol").get(field) != expected or \
            struct_fields(proof_projection, "Symbol").get(field) != expected:
        raise SystemExit(f"Symbol.{field} proof projection differs from production")
expected_table_fields = {
    "symbols": "mutabledarray[Symbol]",
    "typestate_struct_names": "mutabledarray[sview@source]",
}
for field, expected in expected_table_fields.items():
    if struct_fields(actual_semantic_types, "SymbolTable").get(field) != expected or \
            struct_fields(proof_projection, "SymbolTable").get(field) != expected:
        raise SystemExit(f"SymbolTable.{field} proof projection differs from production")
if enum_variants(actual_semantic_types, "SymbolKind") != enum_variants(proof_projection, "SymbolKind"):
    raise SystemExit("SymbolKind proof projection changed variant order")

unique_text = UNIQUE_POLICY.read_text()
unique_compact = compact(unique_text)
if 'module SemanticReferenceInitializerTypestate:' not in unique_text:
    raise SystemExit("reference-initializer uniqueness module changed identity")
unique_declarations = set(re.findall(r"(?m)^[ \t]*(?:ghost[ \t]+)?def ([A-Za-z_][A-Za-z0-9_]*)\(", unique_text))
if unique_declarations != {
        "matching_struct_count_class_prefix",
        "typestate_name_member_prefix",
        "unique_named_typestate_struct_spec",
        "unique_named_typestate_struct",
}:
    raise SystemExit("reference-initializer uniqueness module gained an unreviewed function")
count_spec = compact(function_section(unique_text, "matching_struct_count_class_prefix"))
for fragment in (
    "requiresend<=table.symbols.count",
    "decreasesend",
    "return0ifend==0",
    "prior_end:usize=end-1",
    "matches_name:bool=table.symbols[prior_end].kind==Semantic::SymbolKind.Structandtable.symbols[prior_end].name==name",
    "2returnifmatching_struct_count_class_prefix(table,name,prior_end)==2",
    "2returnifmatching_struct_count_class_prefix(table,name,prior_end)==1andmatches_name",
    "return1ifmatches_name",
    "returnmatching_struct_count_class_prefix(table,name,prior_end)",
):
    if fragment not in count_spec:
        raise SystemExit(f"saturating struct-count specification lost a case: {fragment}")
member_spec = compact(function_section(unique_text, "typestate_name_member_prefix"))
for fragment in (
    "requires end <= table.typestate_struct_names.count",
    "decreases end",
    "return false if end == 0",
    "prior_end: usize = end - 1",
    "return true if table.typestate_struct_names[prior_end] == name",
    "return typestate_name_member_prefix(table, name, prior_end)",
):
    if compact(fragment) not in member_spec:
        raise SystemExit(f"typestate membership specification lost a case: {fragment}")
unique_spec = compact(function_section(unique_text, "unique_named_typestate_struct_spec"))
if compact("return matching_struct_count_class_prefix(table, name, table.symbols.count) == 1 and typestate_name_member_prefix(table, name, table.typestate_struct_names.count)") not in unique_spec:
    raise SystemExit("unique typestate specification no longer requires one struct and a registry entry")
unique_impl = compact(function_section(unique_text, "unique_named_typestate_struct"))
for fragment in (
    "ensure result == unique_named_typestate_struct_spec(table, name)",
    "can Abort.Panic:",
    "declarations: mutable u8 = 0",
    "symbol_count: usize = table.symbols.count",
    "assert symbol_count == table.symbols.count",
    "assert matching_struct_count_class_prefix(table, name, 0.usize()) == 0",
    "assert declarations == matching_struct_count_class_prefix(table, name, 0.usize())",
    "for symbol_index in 0..<symbol_count |table, name, symbol_count, declarations|:",
    "invariant symbol_count == table.symbols.count",
    "invariant symbol_index <= symbol_count",
    "invariant declarations == matching_struct_count_class_prefix(table, name, symbol_index)",
    "next_declarations: u8 = 2 if declarations == 2 or (declarations == 1 and symbol_matches) else (1 if symbol_matches else declarations)",
    "next_symbol_index: usize = symbol_index + 1",
    "assert next_symbol_index <= symbol_count",
    "assert matching_struct_count_class_prefix(table, name, next_symbol_index) == next_declarations",
    "declarations <- next_declarations",
    "assert declarations == matching_struct_count_class_prefix(table, name, next_symbol_index)",
    "assert declarations == matching_struct_count_class_prefix(table, name, table.symbols.count)",
    "typestate_count: usize = table.typestate_struct_names.count",
    "assert typestate_count == table.typestate_struct_names.count",
    "assert not typestate_name_member_prefix(table, name, 0.usize())",
    "assert registered == typestate_name_member_prefix(table, name, 0.usize())",
    "for typestate_index in 0..<typestate_count |table, name, typestate_count, registered|:",
    "invariant typestate_count == table.typestate_struct_names.count",
    "invariant typestate_index <= typestate_count",
    "invariant registered == typestate_name_member_prefix(table, name, typestate_index)",
    "next_typestate_index: usize = typestate_index + 1",
    "assert next_typestate_index <= typestate_count",
    "assert typestate_name_member_prefix(table, name, next_typestate_index) == (registered or table.typestate_struct_names[typestate_index] == name)",
    "assert registered == typestate_name_member_prefix(table, name, next_typestate_index)",
    "assert registered == typestate_name_member_prefix(table, name, table.typestate_struct_names.count)",
    "assert declarations == matching_struct_count_class_prefix(table, name, table.symbols.count)",
    "assert registered == typestate_name_member_prefix(table, name, table.typestate_struct_names.count)",
    "return declarations == 1 and registered",
):
    if compact(fragment) not in unique_impl:
        raise SystemExit(f"production uniqueness scan lost its proved loop invariant or result: {fragment}")

policy_text = POLICY.read_text()
policy_compact = compact(policy_text)
if compact("ghost def typestate_widening_spec(expected_is_named: bool, actual_is_container: bool, same_nominal_name: bool, unique_typestate: bool) -> bool: return expected_is_named and actual_is_container and same_nominal_name and unique_typestate") not in policy_compact:
    raise SystemExit("typestate widening specification lost a required compatibility premise")
if compact("def typestate_widening_allowed(expected_is_named: bool, actual_is_container: bool, same_nominal_name: bool, unique_typestate: bool) -> bool: ensure result == typestate_widening_spec(expected_is_named, actual_is_container, same_nominal_name, unique_typestate) false return if not expected_is_named false return if not actual_is_container false return if not same_nominal_name return unique_typestate") not in policy_compact:
    raise SystemExit("production typestate-widening classifier no longer refines its specification")

initializer_text = INITIALIZERS.read_text()
initializer_compact = compact(initializer_text)
if initializer_text.count('include "./reference_initializer_compatibility.elisa"') != 1:
    raise SystemExit("reference initializer checking must import the compatibility policy exactly once")
if initializer_text.count('include "./reference_initializer_typestate_unique.elisa"') != 1:
    raise SystemExit("reference initializer checking must import the proved typestate uniqueness scan exactly once")
match_source = compact(function_section(initializer_text, "reference_initializer_matches"))
required_match_fragments = (
    "expected_target:u32=interned_elem(declared_id,0,table)",
    "actual_target:u32=reference_initializer_target_id(value,names,types,table)",
    "truereturnifexpected_target==0oractual_target==0",
    "truereturnifexpected_target==actual_target",
    "SemanticReferenceInitializerCompatibility::typestate_widening_allowed(",
    "interned_kind(expected_target,table)==SemTypeKind.Named",
    "interned_kind(actual_target,table)==SemTypeKind.Container",
    "interned_name(expected_target,table)==interned_name(actual_target,table)",
    "SemanticReferenceInitializerTypestate::unique_named_typestate_struct(table,interned_name(expected_target,table))",
)
if any(fragment not in match_source for fragment in required_match_fragments):
    raise SystemExit("reference initializer no longer uses exact identity plus the proved typestate widening")
match_order = (
    match_source.find("truereturnifexpected_target==0oractual_target==0"),
    match_source.find("truereturnifexpected_target==actual_target"),
    match_source.find("SemanticReferenceInitializerCompatibility::typestate_widening_allowed("),
)
if any(position < 0 for position in match_order) or match_order != tuple(sorted(match_order)):
    raise SystemExit("unknown and exact reference targets must bypass the narrow typestate widening rule")
diagnostic_source = compact(function_section(initializer_text, "check_reference_initializer"))
if "returnifreference_initializer_matches(value,declared_id,names,types,table)" not in diagnostic_source or \
        "returnifexpected_target==0oractual_target==0" not in diagnostic_source:
    raise SystemExit("reference initializer mismatch reporting no longer preserves unknown-type conservatism")
diagnostic_order = (
    diagnostic_source.find("returnifreference_initializer_matches(value,declared_id,names,types,table)"),
    diagnostic_source.find("returnifexpected_target==0oractual_target==0"),
    diagnostic_source.find("table.diagnostics<-table.diagnostics.push("),
)
if any(position < 0 for position in diagnostic_order) or diagnostic_order != tuple(sorted(diagnostic_order)):
    raise SystemExit("unknown reference targets must remain silent before mismatch diagnostics are emitted")

closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(POSITIVE_SHAPES),
        "false_controls": len(NEGATIVE_SHAPES),
        "proof_closure_files": len(closure),
    }, sort_keys=True))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("reference initializer proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
compiler_executable = Path(product["compiler"]["executable"]["path"]).resolve(strict=True)
manifest_checksum = MANIFEST.with_name(MANIFEST.name + ".sha256")
inputs = list(dict.fromkeys([
    BIN, MANIFEST, manifest_checksum, PROVER / "ELISA_COMPILER_REV", compiler_executable,
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POLICY, UNIQUE_POLICY, INITIALIZERS, SEMANTIC_TYPES, POSITIVE, NEGATIVE, *closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


positive_code, positive = replay(POSITIVE)
assert positive_code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == set(POSITIVE_SHAPES)
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
negative_code, negative = replay(NEGATIVE)
assert negative_code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == set(NEGATIVE_SHAPES)
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "reference-initializer typestate widening policy",
    "positive_theorems": sorted(POSITIVE_SHAPES),
    "false_controls_rejected": sorted(NEGATIVE_SHAPES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
}, sort_keys=True))
