"""Admit source-linked proofs of frontend-IR pattern tags and field IDs."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
ENCODING = ROOT / "src/driver/frontend_ir_pattern_encoding.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
PATTERNS = ROOT / "src/driver/frontend_ir_patterns.elisa"
TYPE_TABLE = ROOT / "src/driver/frontend_ir_type_table_statements.elisa"
POSITIVE = HERE / "frontend_ir_pattern_encoding.elisa"
NEGATIVE = HERE / "frontend_ir_pattern_encoding_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def code_only(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def function_body(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(0).split("def", 1)[0]
    tail = source[match.end():]
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", tail)
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def schema_entry(source: str, type_name: str) -> tuple[int, dict[str, int]]:
    match = re.search(
        rf"(?ms)^[ \t]*# {re.escape(type_name)} \(type ([0-9]+)\)\s*\n"
        r"(.*?)(?=^[ \t]*# [A-Za-z_][A-Za-z0-9_]* \(type [0-9]+\)|\Z)",
        source,
    )
    if not match:
        raise SystemExit(f"frontend IR schema entry {type_name} is missing")
    type_id = int(match.group(1))
    body = match.group(2)
    if f"ir_uvarint_out(buffer, {type_id})" not in body or \
            f'ir_str_out(buffer, "{type_name}")' not in body:
        raise SystemExit(f"{type_name} type table entry disagrees with its declared tag")
    fields = {name: int(field_id) for field_id, name in re.findall(
        r'ir_field_desc_out\(buffer,\s*([0-9]+),\s*"([A-Za-z_][A-Za-z0-9_]*)"\)', body
    )}
    return type_id, fields


type_table = TYPE_TABLE.read_text()
encoding = ENCODING.read_text()
patterns_source = PATTERNS.read_text()
writer_source = WRITER.read_text()

tag_bindings = {
    "WILDCARD_PATTERN_NODE_TYPE_ID": "MatchWildcardPattern",
    "BINDING_PATTERN_NODE_TYPE_ID": "MatchBindPattern",
    "LITERAL_PATTERN_NODE_TYPE_ID": "MatchLiteralPattern",
    "STRING_LITERAL_PATTERN_NODE_TYPE_ID": "MatchStringLiteralPattern",
    "VARIANT_PATTERN_NODE_TYPE_ID": "MatchVariantPattern",
    "STRUCT_PATTERN_NODE_TYPE_ID": "MatchStructPattern",
    "TUPLE_PATTERN_NODE_TYPE_ID": "MatchTuplePattern",
    "BOOL_LITERAL_NODE_TYPE_ID": "BoolLit",
    "CHAR_LITERAL_NODE_TYPE_ID": "CharLit",
    "INT_LITERAL_NODE_TYPE_ID": "IntLit",
    "PATTERN_ARG_NODE_TYPE_ID": "MatchPatternArg",
    "MATCH_ARM_NODE_TYPE_ID": "MatchArm",
}
field_bindings = {
    "BINDING_PATTERN_NAME_FIELD_ID": ("MatchBindPattern", "Name"),
    "LITERAL_PATTERN_VALUE_FIELD_ID": ("MatchLiteralPattern", "Value"),
    "STRING_LITERAL_PATTERN_VALUE_FIELD_ID": ("MatchStringLiteralPattern", "Value"),
    "VARIANT_PATTERN_ARGS_FIELD_ID": ("MatchVariantPattern", "Args"),
    "VARIANT_PATTERN_ENUM_NAME_FIELD_ID": ("MatchVariantPattern", "EnumName"),
    "VARIANT_PATTERN_VARIANT_FIELD_ID": ("MatchVariantPattern", "Variant"),
    "STRUCT_PATTERN_ARGS_FIELD_ID": ("MatchStructPattern", "Args"),
    "STRUCT_PATTERN_BRACE_FIELD_ID": ("MatchStructPattern", "Brace"),
    "STRUCT_PATTERN_TYPE_NAME_FIELD_ID": ("MatchStructPattern", "TypeName"),
    "TUPLE_PATTERN_ELEMENTS_FIELD_ID": ("MatchTuplePattern", "Elems"),
    "BOOL_LITERAL_VALUE_FIELD_ID": ("BoolLit", "Value"),
    "CHAR_LITERAL_VALUE_FIELD_ID": ("CharLit", "Value"),
    "INT_LITERAL_VALUE_FIELD_ID": ("IntLit", "Value"),
    "PATTERN_ARG_NAME_FIELD_ID": ("MatchPatternArg", "Name"),
    "PATTERN_ARG_PATTERN_FIELD_ID": ("MatchPatternArg", "Pattern"),
    "MATCH_ARM_BODY_FIELD_ID": ("MatchArm", "Body"),
    "MATCH_ARM_GUARD_FIELD_ID": ("MatchArm", "Guard"),
    "MATCH_ARM_PATTERN_FIELD_ID": ("MatchArm", "Pattern"),
}
constants = {
    name: int(value) for name, value in re.findall(
        r"(?m)^\s*const ([A-Z][A-Z0-9_]*):\s*(?:u64|i64)\s*=\s*([0-9]+)\s*$", encoding
    )
}
schema_types: dict[str, tuple[int, dict[str, int]]] = {}
for type_name in set(tag_bindings.values()) | {record for record, _field in field_bindings.values()}:
    schema_types[type_name] = schema_entry(type_table, type_name)
for constant, type_name in tag_bindings.items():
    if constants.get(constant) != schema_types[type_name][0]:
        raise SystemExit(f"{constant} no longer matches {type_name}'s stage0 node type ID")
for constant, (type_name, field_name) in field_bindings.items():
    if constants.get(constant) != schema_types[type_name][1].get(field_name):
        raise SystemExit(f"{constant} no longer matches {type_name}.{field_name}'s stage0 field ID")

byte_values = {
    "QUALIFIED_PATTERN_PATH_SEPARATOR_BYTE": 46,
    "STRING_PATTERN_QUOTE_BYTE": 34,
    "CHAR_PATTERN_QUOTE_BYTE": 39,
    "ASCII_DIGIT_ZERO_BYTE": 48,
    "ASCII_DIGIT_NINE_BYTE": 57,
}
for constant, value in byte_values.items():
    if constants.get(constant) != value:
        raise SystemExit(f"{constant} changed from its ASCII byte value")

if 'include "./frontend_ir_pattern_encoding.elisa"' not in writer_source or \
        'include "./frontend_ir_patterns.elisa"' not in writer_source:
    raise SystemExit("frontend IR writer no longer imports the encoding constants and pattern emitter")
if writer_source.index('include "./frontend_ir_pattern_encoding.elisa"') > \
        writer_source.index('include "./frontend_ir_patterns.elisa"'):
    raise SystemExit("frontend IR pattern emitter is included before its encoding constants")
if 'include "../../src/driver/frontend_ir_pattern_encoding.elisa"' not in POSITIVE.read_text() or \
        'include "../../src/driver/frontend_ir_pattern_encoding.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("positive and negative proofs must import the production encoding constants")

pattern_function = code_only(function_body(patterns_source, "ir_pattern_node"))
branch_matches = list(re.finditer(
    r"(?m)^[ \t]*Ast::Pattern\.(Wildcard|Binding|Literal|Variant|Struct|Tuple)(?:\([^\n]*\))?:[ \t]*$",
    pattern_function,
))
branches: dict[str, str] = {}
for index, branch in enumerate(branch_matches):
    end = branch_matches[index + 1].start() if index + 1 < len(branch_matches) else len(pattern_function)
    branches[branch.group(1)] = compact(pattern_function[branch.start():end])
expected_pattern_branch_calls = {
    "Wildcard": (
        "return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::WILDCARD_PATTERN_NODE_TYPE_ID,fields,live)",
    ),
    "Binding": (
        "ir_put_str(&fields,&live,FrontendIrPatternEncoding::BINDING_PATTERN_NAME_FIELD_ID,name)",
        "return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::BINDING_PATTERN_NODE_TYPE_ID,fields,live)",
    ),
    "Literal": (
        "text[0]==FrontendIrPatternEncoding::STRING_PATTERN_QUOTE_BYTE",
        "ir_put_str(&fields,&live,FrontendIrPatternEncoding::STRING_LITERAL_PATTERN_VALUE_FIELD_ID,text)",
        "return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::STRING_LITERAL_PATTERN_NODE_TYPE_ID,fields,live)",
        "ir_put_node(&fields,&live,FrontendIrPatternEncoding::LITERAL_PATTERN_VALUE_FIELD_ID,value_id)",
        "return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::LITERAL_PATTERN_NODE_TYPE_ID,fields,live)",
    ),
    "Variant": (
        "ir_put_raw(&fields,&live,FrontendIrPatternEncoding::VARIANT_PATTERN_ARGS_FIELD_ID,args_payload)",
        "ir_put_str(&fields,&live,FrontendIrPatternEncoding::VARIANT_PATTERN_ENUM_NAME_FIELD_ID,bytes_view_range(enum_name,0,enum_name.count))",
        "ir_put_str(&fields,&live,FrontendIrPatternEncoding::VARIANT_PATTERN_VARIANT_FIELD_ID,bytes_view_range(variant_name,0,variant_name.count))",
        "return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::VARIANT_PATTERN_NODE_TYPE_ID,fields,live)",
    ),
    "Struct": (
        "ir_put_raw(&fields,&live,FrontendIrPatternEncoding::STRUCT_PATTERN_ARGS_FIELD_ID,args_payload)",
        "ir_put_bool(&fields,&live,FrontendIrPatternEncoding::STRUCT_PATTERN_BRACE_FIELD_ID,true)",
        "ir_put_str(&fields,&live,FrontendIrPatternEncoding::STRUCT_PATTERN_TYPE_NAME_FIELD_ID,path)",
        "return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::STRUCT_PATTERN_NODE_TYPE_ID,fields,live)",
    ),
    "Tuple": (
        "ir_put_node_list(&fields,&live,FrontendIrPatternEncoding::TUPLE_PATTERN_ELEMENTS_FIELD_ID,element_ids)",
        "return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::TUPLE_PATTERN_NODE_TYPE_ID,fields,live)",
    ),
}
for branch, calls in expected_pattern_branch_calls.items():
    body = branches.get(branch, "")
    if not body or any(compact(call) not in body for call in calls):
        raise SystemExit(f"ir_pattern_node {branch} branch no longer emits its mapped schema fields and tag")

literal_function = code_only(function_body(patterns_source, "ir_literal_value_node"))
argument_function = code_only(function_body(patterns_source, "ir_pattern_args_out"))
arm_function = code_only(function_body(patterns_source, "ir_arms_out"))
literal_code = compact(literal_function)
literal_calls = (
    '"true":ir_put_bool(&fields,&live,FrontendIrPatternEncoding::BOOL_LITERAL_VALUE_FIELD_ID,true)return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::BOOL_LITERAL_NODE_TYPE_ID,fields,live)',
    '"false":ir_put_bool(&fields,&live,FrontendIrPatternEncoding::BOOL_LITERAL_VALUE_FIELD_ID,false)return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::BOOL_LITERAL_NODE_TYPE_ID,fields,live)',
    'text[0]==FrontendIrPatternEncoding::CHAR_PATTERN_QUOTE_BYTE:ir_put_str(&fields,&live,FrontendIrPatternEncoding::CHAR_LITERAL_VALUE_FIELD_ID,text)return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::CHAR_LITERAL_NODE_TYPE_ID,fields,live)',
    'text[index]<FrontendIrPatternEncoding::ASCII_DIGIT_ZERO_BYTE',
    'text[index]>FrontendIrPatternEncoding::ASCII_DIGIT_NINE_BYTE',
    'ir_put_str(&fields,&live,FrontendIrPatternEncoding::INT_LITERAL_VALUE_FIELD_ID,text)return ir_emit_node(bodies,nodes,FrontendIrPatternEncoding::INT_LITERAL_NODE_TYPE_ID,fields,live)',
)
if any(compact(call) not in literal_code for call in literal_calls):
    raise SystemExit("literal writer no longer uses its exact named node and field IDs")
argument_code = compact(argument_function)
if any(compact(call) not in argument_code for call in (
    "ir_put_str(&fields,&live,FrontendIrPatternEncoding::PATTERN_ARG_NAME_FIELD_ID,bytes_view_range(label,0,label.count))",
    "ir_put_node(&fields,&live,FrontendIrPatternEncoding::PATTERN_ARG_PATTERN_FIELD_ID,inner_id)",
    "ir_uvarint_out(payload,FrontendIrPatternEncoding::PATTERN_ARG_NODE_TYPE_ID)",
)):
    raise SystemExit("pattern argument writer no longer uses its exact named schema IDs")
arm_code = compact(arm_function)
if any(compact(call) not in arm_code for call in (
    "ir_put_node_list(&fields,&live,FrontendIrPatternEncoding::MATCH_ARM_BODY_FIELD_ID,body_ids)",
    "ir_put_node(&fields,&live,FrontendIrPatternEncoding::MATCH_ARM_GUARD_FIELD_ID,guard_id)",
    "ir_put_node(&fields,&live,FrontendIrPatternEncoding::MATCH_ARM_PATTERN_FIELD_ID,pattern_id)",
    "ir_uvarint_out(payload,FrontendIrPatternEncoding::MATCH_ARM_NODE_TYPE_ID)",
)):
    raise SystemExit("match arm writer no longer uses its exact named schema IDs")

for function in (pattern_function, literal_function, argument_function, arm_function):
    if re.search(r"ir_emit_node\(bodies,\s*nodes,\s*[0-9]+", function) or \
            re.search(r"ir_put_[A-Za-z_]+\(&fields,\s*&live,\s*[0-9]+", function) or \
            re.search(r"ir_uvarint_out\(payload,\s*[0-9]+", function):
        raise SystemExit("pattern wire tags or field IDs reverted to numeric literals")
if re.search(r"(?m)^\s*def sview_(?:len|at)\(", code_only(patterns_source)):
    raise SystemExit("pattern source uses a removed sview length/index helper")

positive_names = {
    "pattern_node_type_ids_match_schema",
    "pattern_field_ids_match_schema",
    "pattern_layout_field_ids_are_pairwise_distinct",
    "pattern_text_discriminators_match_ascii",
}
negative_names = {
    "binding_pattern_must_use_wildcard_node_type",
    "variant_name_field_must_be_the_args_field",
}
for name in positive_names:
    if not re.search(rf"(?m)^def {name}\(", POSITIVE.read_text()):
        raise SystemExit(f"positive proof lost {name}")
for name in negative_names:
    if not re.search(rf"(?m)^def {name}\(", NEGATIVE.read_text()):
        raise SystemExit(f"negative proof lost {name}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("frontend IR pattern encoding proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, WRITER, PATTERNS, TYPE_TABLE])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    ENCODING, WRITER, PATTERNS, TYPE_TABLE, *source_closure,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "pattern encoding proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "frontend IR pattern node IDs, field IDs, and byte discriminators",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
