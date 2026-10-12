"""Admit proofs of frontend-IR declaration tags against the writer and registry."""
import hashlib
from itertools import combinations
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
TAGS = ROOT / "src/driver/frontend_ir_decl_tags.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
DECL_WRITER = ROOT / "src/driver/frontend_ir_decl.elisa"
POSITIVE = HERE / "frontend_ir_decl_tags.elisa"
NEGATIVE = HERE / "frontend_ir_decl_tags_rejected.elisa"
PROOF_REPLAY_TIMEOUT_SECONDS = 60

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def line_indent_at(text: str, position: int) -> int:
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    return len(line) - len(line.lstrip(" \t"))


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


tags = {
    "FuncDecl": ("FUNC_DECL_NODE_TAG", 71),
    "StructDecl": ("STRUCT_DECL_NODE_TAG", 254),
    "EnumDecl": ("ENUM_DECL_NODE_TAG", 47),
    "ConstEnumDecl": ("CONST_ENUM_DECL_NODE_TAG", 32),
    "TypeAliasDecl": ("TYPE_ALIAS_DECL_NODE_TAG", 266),
    "ImportDecl": ("IMPORT_DECL_NODE_TAG", 136),
    "NamespaceDecl": ("NAMESPACE_DECL_NODE_TAG", 195),
    "GlobalDecl": ("GLOBAL_DECL_NODE_TAG", 77),
    "ConstDecl": ("CONST_DECL_NODE_TAG", 31),
}
field_ids = {
    "FuncDecl": [
        ("FUNC_DECL_BODY_FIELD_ID", 3, "Body"),
        ("FUNC_DECL_NAME_FIELD_ID", 20, "Name"),
        ("FUNC_DECL_PARAMS_FIELD_ID", 23, "Params"),
        ("FUNC_DECL_POSITION_FIELD_ID", 26, "Position"),
        ("FUNC_DECL_RETURN_TYPE_FIELD_ID", 31, "ReturnType"),
    ],
    "StructDecl": [
        ("STRUCT_DECL_AFFINITY_FIELD_ID", 1, "Affine"),
        ("STRUCT_DECL_FIELDS_FIELD_ID", 5, "Fields"),
        ("STRUCT_DECL_INVARIANTS_FIELD_ID", 8, "Invariants"),
        ("STRUCT_DECL_NAME_FIELD_ID", 10, "Name"),
        ("STRUCT_DECL_POSITION_FIELD_ID", 12, "Position"),
    ],
    "EnumDecl": [
        ("ENUM_DECL_NAME_FIELD_ID", 7, "Name"),
        ("ENUM_DECL_POSITION_FIELD_ID", 10, "Position"),
        ("ENUM_DECL_VARIANTS_FIELD_ID", 11, "Variants"),
    ],
    "ConstEnumDecl": [
        ("CONST_ENUM_DECL_MEMBERS_FIELD_ID", 1, "Members"),
        ("CONST_ENUM_DECL_NAME_FIELD_ID", 2, "Name"),
        ("CONST_ENUM_DECL_POSITION_FIELD_ID", 3, "Position"),
        ("CONST_ENUM_DECL_STORAGE_FIELD_ID", 4, "Storage"),
    ],
    "TypeAliasDecl": [
        ("TYPE_ALIAS_DECL_NAME_FIELD_ID", 1, "Name"),
        ("TYPE_ALIAS_DECL_POSITION_FIELD_ID", 2, "Position"),
        ("TYPE_ALIAS_DECL_TARGET_FIELD_ID", 3, "Target"),
    ],
    "ImportDecl": [
        ("IMPORT_DECL_MODULE_FIELD_ID", 1, "Module"),
        ("IMPORT_DECL_POSITION_FIELD_ID", 3, "Position"),
    ],
    "NamespaceDecl": [
        ("NAMESPACE_DECL_DECLS_FIELD_ID", 2, "Decls"),
        ("NAMESPACE_DECL_MODULE_FIELD_ID", 4, "Module"),
        ("NAMESPACE_DECL_NAME_FIELD_ID", 5, "Name"),
        ("NAMESPACE_DECL_POSITION_FIELD_ID", 6, "Position"),
    ],
    "GlobalDecl": [
        ("GLOBAL_DECL_MUTABLE_FIELD_ID", 1, "Mutable"),
        ("GLOBAL_DECL_NAME_FIELD_ID", 2, "Name"),
        ("GLOBAL_DECL_POSITION_FIELD_ID", 3, "Position"),
        ("GLOBAL_DECL_TYPE_FIELD_ID", 4, "Type"),
        ("GLOBAL_DECL_VALUE_FIELD_ID", 5, "Value"),
    ],
    "ConstDecl": [
        ("CONST_DECL_NAME_FIELD_ID", 1, "Name"),
        ("CONST_DECL_POSITION_FIELD_ID", 2, "Position"),
        ("CONST_DECL_TYPE_FIELD_ID", 3, "Type"),
        ("CONST_DECL_VALUE_FIELD_ID", 4, "Value"),
    ],
}
tag_source = TAGS.read_text()
for kind, (constant, value) in tags.items():
    declaration = f"const {constant}: u32 = {value}"
    if compact(declaration) not in compact(tag_source):
        raise SystemExit(f"{constant} no longer matches its schema ID")
for kind, field_records in field_ids.items():
    for constant, value, _field_name in field_records:
        declaration = f"const {constant}: u32 = {value}"
        if compact(declaration) not in compact(tag_source):
            raise SystemExit(f"{constant} no longer matches its schema field ID")

tag_function = compact(function_section(tag_source, "node_tag"))
expected_tag_match = compact("return match kind: " + " ".join(
    f"NodeKind.{kind}: {constant}"
    for kind, (constant, _value) in tags.items()
))
if expected_tag_match not in tag_function:
    raise SystemExit("node_tag no longer exhaustively matches every declaration kind to its named tag")
expected_tag_contracts = compact(" ".join(
    f"ensure kind != NodeKind.{kind} or result == {constant}"
    for kind, (constant, _value) in tags.items()
))
if expected_tag_contracts not in tag_function:
    raise SystemExit("node_tag no longer states each tag mapping without negated-equality implications")

if 'include "./frontend_ir_decl_tags.elisa"' not in WRITER.read_text():
    raise SystemExit("frontend IR writer no longer imports the declaration tag policy")
if 'include "./frontend_ir_decl.elisa"' not in WRITER.read_text():
    raise SystemExit("frontend IR writer no longer imports the declaration encoder")
decl_body = function_section(DECL_WRITER.read_text(), "ir_decl_node")
branches = list(re.finditer(r"(?m)^[ \t]*Ast::Decl\.([A-Za-z_][A-Za-z0-9_]*)\(", decl_body))
branch_bodies = {}
for index, match in enumerate(branches):
    end = branches[index + 1].start() if index + 1 < len(branches) else len(decl_body)
    branch_bodies[match.group(1)] = decl_body[match.start():end]

branch_mapping = {
    "Func": ["FuncDecl"],
    "Struct": ["StructDecl"],
    "Enum": ["ConstEnumDecl", "EnumDecl"],
    "Alias": ["TypeAliasDecl"],
    "Import": ["ImportDecl"],
    "Module": ["NamespaceDecl"],
    "Const": ["GlobalDecl", "ConstDecl"],
}
branch_field_calls = {
    "Func": [("node_list", "FUNC_DECL_BODY_FIELD_ID"), ("str", "FUNC_DECL_NAME_FIELD_ID"),
             ("raw", "FUNC_DECL_PARAMS_FIELD_ID"), ("pos", "FUNC_DECL_POSITION_FIELD_ID"),
             ("node", "FUNC_DECL_RETURN_TYPE_FIELD_ID")],
    "Struct": [("bool", "STRUCT_DECL_AFFINITY_FIELD_ID"), ("raw", "STRUCT_DECL_FIELDS_FIELD_ID"),
               ("node_list", "STRUCT_DECL_INVARIANTS_FIELD_ID"), ("str", "STRUCT_DECL_NAME_FIELD_ID"),
               ("pos", "STRUCT_DECL_POSITION_FIELD_ID")],
    "Enum": [("raw", "CONST_ENUM_DECL_MEMBERS_FIELD_ID"), ("str", "CONST_ENUM_DECL_NAME_FIELD_ID"),
             ("pos", "CONST_ENUM_DECL_POSITION_FIELD_ID"), ("node", "CONST_ENUM_DECL_STORAGE_FIELD_ID"),
             ("str", "ENUM_DECL_NAME_FIELD_ID"), ("pos", "ENUM_DECL_POSITION_FIELD_ID"),
             ("raw", "ENUM_DECL_VARIANTS_FIELD_ID")],
    "Alias": [("str", "TYPE_ALIAS_DECL_NAME_FIELD_ID"), ("pos", "TYPE_ALIAS_DECL_POSITION_FIELD_ID"),
              ("node", "TYPE_ALIAS_DECL_TARGET_FIELD_ID")],
    "Import": [("str", "IMPORT_DECL_MODULE_FIELD_ID"), ("pos", "IMPORT_DECL_POSITION_FIELD_ID")],
    "Module": [("node_list", "NAMESPACE_DECL_DECLS_FIELD_ID"), ("bool", "NAMESPACE_DECL_MODULE_FIELD_ID"),
               ("str", "NAMESPACE_DECL_NAME_FIELD_ID"), ("pos", "NAMESPACE_DECL_POSITION_FIELD_ID")],
    "Const": [("bool", "GLOBAL_DECL_MUTABLE_FIELD_ID"), ("str", "GLOBAL_DECL_NAME_FIELD_ID"),
              ("pos", "GLOBAL_DECL_POSITION_FIELD_ID"), ("node", "GLOBAL_DECL_TYPE_FIELD_ID"),
              ("node", "GLOBAL_DECL_VALUE_FIELD_ID"), ("str", "CONST_DECL_NAME_FIELD_ID"),
              ("pos", "CONST_DECL_POSITION_FIELD_ID"), ("node", "CONST_DECL_TYPE_FIELD_ID"),
              ("node", "CONST_DECL_VALUE_FIELD_ID")],
}
for branch, kinds in branch_mapping.items():
    body = compact(branch_bodies.get(branch, ""))
    if not body:
        raise SystemExit(f"declaration writer lost the {branch} branch")
    previous = -1
    for kind in kinds:
        use = f"FrontendIrDeclarationNodeTags::node_tag(FrontendIrDeclarationNodeTags::NodeKind.{kind})"
        position = body.find(compact(use))
        if position < 0 or position <= previous:
            raise SystemExit(f"{branch} declaration no longer emits the expected {kind} tag in order")
        previous = position
    field_calls = re.findall(
        r"ir_put_(raw|bool|str|pos|node|node_list)\(&fields,&live,([^,]+),",
        body,
    )
    expected_calls = [
        (operation, f"FrontendIrDeclarationNodeTags::{constant}")
        for operation, constant in branch_field_calls[branch]
    ]
    if field_calls != expected_calls:
        raise SystemExit(f"{branch} declaration fields no longer use the expected named schema IDs")

enum_body = branch_bodies["Enum"]
const_body = branch_bodies["Const"]
enum_condition = enum_body.index("if is_const:")
const_enum_tag = enum_body.index("NodeKind.ConstEnumDecl")
enum_tag = enum_body.index("NodeKind.EnumDecl")
enum_payload = enum_body.index("variants_payload:")
if not (enum_condition < const_enum_tag < enum_payload < enum_tag and
        line_indent_at(enum_body, const_enum_tag) > line_indent_at(enum_body, enum_condition) and
        line_indent_at(enum_body, enum_tag) == line_indent_at(enum_body, enum_condition)):
    raise SystemExit("enum and const-enum tags are no longer selected by is_const")
mutable_condition = const_body.index("if is_mutable:")
global_tag = const_body.index("NodeKind.GlobalDecl")
const_tag = const_body.index("NodeKind.ConstDecl")
if not (mutable_condition < global_tag < const_tag and
        line_indent_at(const_body, global_tag) > line_indent_at(const_body, mutable_condition) and
        line_indent_at(const_body, const_tag) == line_indent_at(const_body, mutable_condition)):
    raise SystemExit("global and const declaration tags are no longer selected by is_mutable")

type_tables = [ROOT / f"src/driver/frontend_ir_type_table{suffix}.elisa" for suffix in ("", "_2", "_3")]
type_table_source = "\n".join(path.read_text() for path in type_tables)
type_table_text = compact(type_table_source)
schema_names = {
    "FuncDecl": "FuncDecl",
    "StructDecl": "StructDecl",
    "EnumDecl": "EnumDecl",
    "ConstEnumDecl": "ConstEnumDecl",
    "TypeAliasDecl": "TypeAliasDecl",
    "ImportDecl": "ImportDecl",
    "NamespaceDecl": "NamespaceDecl",
    "GlobalDecl": "GlobalDecl",
    "ConstDecl": "ConstDecl",
}
for kind, (constant, value) in tags.items():
    schema_entry = f"ir_uvarint_out(buffer, {value}) ir_str_out(buffer, \"{schema_names[kind]}\")"
    if compact(schema_entry) not in type_table_text:
        raise SystemExit(f"generated frontend IR type table no longer pairs {kind} with ID {value}")


def schema_field_ids(schema_name: str, schema_id: int) -> dict[str, int]:
    lines = type_table_source.splitlines()
    header = f"# {schema_name} (type {schema_id})"
    matches = [index for index, line in enumerate(lines) if line.strip() == header]
    if len(matches) != 1:
        raise SystemExit(f"expected one generated type-table entry for {schema_name}")
    start = matches[0]
    end = next((index for index in range(start + 1, len(lines))
                if re.fullmatch(r"\s*# [A-Za-z_][A-Za-z0-9_]* \(type [0-9]+\)", lines[index])), len(lines))
    descriptors = re.findall(
        r'ir_field_desc_out\(buffer,\s*([0-9]+),\s*"([A-Za-z_][A-Za-z0-9_]*)"\)',
        "\n".join(lines[start + 1:end]),
    )
    result = {name: int(field_id) for field_id, name in descriptors}
    if len(result) != len(descriptors):
        raise SystemExit(f"generated {schema_name} type-table entry has duplicate field names")
    return result


for kind, records in field_ids.items():
    actual_fields = schema_field_ids(schema_names[kind], tags[kind][1])
    for constant, value, field_name in records:
        if actual_fields.get(field_name) != value:
            raise SystemExit(f"generated {kind} schema no longer maps {field_name} to field ID {value}")

field_function = compact(function_section(tag_source, "field_ids_are_pairwise_distinct"))
expected_field_match = compact("ensure result == true return match kind: " + " ".join(
    f"NodeKind.{kind}: (" + " and ".join(
        f"({left[0]} != {right[0]})"
        for left, right in combinations(records, 2)
    ) + ")"
    for kind, records in field_ids.items()
))
if expected_field_match not in field_function:
    raise SystemExit("field_ids_are_pairwise_distinct no longer checks every field pair per declaration kind")

positive_names = {
    "every_declaration_kind_uses_its_schema_id",
    "distinct_declaration_kinds_have_distinct_node_tags",
    "every_declaration_kind_uses_pairwise_distinct_field_ids",
    "declaration_node_tags_are_pairwise_distinct",
}
negative_names = {
    "function_tag_is_the_struct_tag",
    "constant_declaration_uses_global_tag",
    "function_body_and_name_share_field_id",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/driver/frontend_ir_decl_tags.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer includes the production declaration tag policy")

positive_shapes = {
    "every_declaration_kind_uses_its_schema_id": "return match kind: FrontendIrDeclarationNodeTags::NodeKind.FuncDecl: FrontendIrDeclarationNodeTags::node_tag(kind) == FrontendIrDeclarationNodeTags::FUNC_DECL_NODE_TAG FrontendIrDeclarationNodeTags::NodeKind.StructDecl: FrontendIrDeclarationNodeTags::node_tag(kind) == FrontendIrDeclarationNodeTags::STRUCT_DECL_NODE_TAG FrontendIrDeclarationNodeTags::NodeKind.EnumDecl: FrontendIrDeclarationNodeTags::node_tag(kind) == FrontendIrDeclarationNodeTags::ENUM_DECL_NODE_TAG FrontendIrDeclarationNodeTags::NodeKind.ConstEnumDecl: FrontendIrDeclarationNodeTags::node_tag(kind) == FrontendIrDeclarationNodeTags::CONST_ENUM_DECL_NODE_TAG FrontendIrDeclarationNodeTags::NodeKind.TypeAliasDecl: FrontendIrDeclarationNodeTags::node_tag(kind) == FrontendIrDeclarationNodeTags::TYPE_ALIAS_DECL_NODE_TAG FrontendIrDeclarationNodeTags::NodeKind.ImportDecl: FrontendIrDeclarationNodeTags::node_tag(kind) == FrontendIrDeclarationNodeTags::IMPORT_DECL_NODE_TAG FrontendIrDeclarationNodeTags::NodeKind.NamespaceDecl: FrontendIrDeclarationNodeTags::node_tag(kind) == FrontendIrDeclarationNodeTags::NAMESPACE_DECL_NODE_TAG FrontendIrDeclarationNodeTags::NodeKind.GlobalDecl: FrontendIrDeclarationNodeTags::node_tag(kind) == FrontendIrDeclarationNodeTags::GLOBAL_DECL_NODE_TAG FrontendIrDeclarationNodeTags::NodeKind.ConstDecl: FrontendIrDeclarationNodeTags::node_tag(kind) == FrontendIrDeclarationNodeTags::CONST_DECL_NODE_TAG",
    "distinct_declaration_kinds_have_distinct_node_tags": "requires left != right ensure result == true return FrontendIrDeclarationNodeTags::node_tag(left) != FrontendIrDeclarationNodeTags::node_tag(right)",
    "every_declaration_kind_uses_pairwise_distinct_field_ids": "return FrontendIrDeclarationNodeTags::field_ids_are_pairwise_distinct(kind)",
}
negative_shapes = {
    "function_tag_is_the_struct_tag": "return FrontendIrDeclarationNodeTags::node_tag(FrontendIrDeclarationNodeTags::NodeKind.FuncDecl) == FrontendIrDeclarationNodeTags::STRUCT_DECL_NODE_TAG",
    "constant_declaration_uses_global_tag": "return FrontendIrDeclarationNodeTags::node_tag(FrontendIrDeclarationNodeTags::NodeKind.ConstDecl) == FrontendIrDeclarationNodeTags::GLOBAL_DECL_NODE_TAG",
    "function_body_and_name_share_field_id": "return FrontendIrDeclarationNodeTags::FUNC_DECL_BODY_FIELD_ID == FrontendIrDeclarationNodeTags::FUNC_DECL_NAME_FIELD_ID",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer states the expected node-tag claim")

pairwise_body = compact(function_section(POSITIVE.read_text(), "declaration_node_tags_are_pairwise_distinct"))
tag_names = [constant for constant, _value in tags.values()]
expected_pairwise = compact("return (" + " and ".join(
    f"FrontendIrDeclarationNodeTags::{left} != FrontendIrDeclarationNodeTags::{right}"
    for left, right in combinations(tag_names, 2)
) + ")")
if expected_pairwise not in pairwise_body:
    raise SystemExit("declaration_node_tags_are_pairwise_distinct no longer compares every pair")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("frontend IR declaration tag proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_include_closure([POSITIVE, NEGATIVE, WRITER]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_REPLAY_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names) + 2
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "frontend IR node-tag proof report changed across repeated runs"
assert positive_names | {"node_tag", "field_ids_are_pairwise_distinct"} <= {
    row["name"] for row in positive["declaration_details"] if row.get("verified")
}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert negative["summary"]["declarations"] == len(negative_names) + 2
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(row["status"] == "disproved" and row["counterexample_found"]
           for row in negative["findings"])
assert {"node_tag", "field_ids_are_pairwise_distinct"} <= {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert product == require_current_product(BIN, PROVER)
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "frontend IR node-tag proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed declaration node-tag mapping shared by the frontend IR writer and generated schema table",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
