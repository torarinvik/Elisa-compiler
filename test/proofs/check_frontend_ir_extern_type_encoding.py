"""Admit source-linked proofs for retained extern type node encodings."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "frontend_ir_extern_type_encoding.elisa"
NEGATIVE = HERE / "frontend_ir_extern_type_encoding_rejected.elisa"
ENCODING = ROOT / "src/driver/frontend_ir_extern_type_encoding.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
EXTERN_WRITER = ROOT / "src/driver/frontend_ir_extern.elisa"
NAMED_TYPE_TABLE = ROOT / "src/driver/frontend_ir_type_table.elisa"
REF_TYPE_TABLE = ROOT / "src/driver/frontend_ir_type_table_2.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    without_comments = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    return re.sub(r"\s+", "", without_comments)


def function_chunk(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\s*\(", text)
    if not match:
        raise SystemExit(f"missing function {name}")
    following = re.search(r"(?m)^[ \t]*def ", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def schema_block(text: str, name: str, node_id: int) -> str:
    marker = re.search(rf"(?m)^\s*# {re.escape(name)} \(type {node_id}\)\s*$", text)
    if marker is None:
        raise SystemExit(f"stage0 type table lost {name} type ID {node_id}")
    following = re.search(r"(?m)^\s*# [A-Za-z][A-Za-z0-9]* \(type [0-9]+\)\s*$", text[marker.end():])
    end = marker.end() + following.start() if following else len(text)
    return text[marker.start():end]


expected = {
    "Named": {
        "node_id": 194,
        "field_count": 2,
        "tag_name": "NAMED_TYPE_NODE_TYPE_ID",
        "expected_tag": "EXPECTED_NAMED_TYPE_NODE_TYPE_ID",
        "primary_field": 1,
        "primary_name": "NAMED_TYPE_NAME_FIELD_ID",
        "expected_primary": "EXPECTED_NAMED_TYPE_NAME_FIELD_ID",
        "position_field": 2,
        "position_name": "NAMED_TYPE_POSITION_FIELD_ID",
        "expected_position": "EXPECTED_NAMED_TYPE_POSITION_FIELD_ID",
        "wire_name": "Name",
        "primary_wire_type": 3,
    },
    "ProvenanceRef": {
        "node_id": 220,
        "field_count": 6,
        "tag_name": "REF_TYPE_NODE_TYPE_ID",
        "expected_tag": "EXPECTED_REF_TYPE_NODE_TYPE_ID",
        "primary_field": 1,
        "primary_name": "REF_TYPE_ELEM_FIELD_ID",
        "expected_primary": "EXPECTED_REF_TYPE_ELEM_FIELD_ID",
        "position_field": 3,
        "position_name": "REF_TYPE_POSITION_FIELD_ID",
        "expected_position": "EXPECTED_REF_TYPE_POSITION_FIELD_ID",
        "wire_name": "Elem",
        "primary_wire_type": 4,
    },
}

encoding_text = ENCODING.read_text()
writer_text = WRITER.read_text()
extern_text = EXTERN_WRITER.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

for shape, spec in expected.items():
    for name_key, value_key, type_name in (
        ("tag_name", "node_id", "u32"),
        ("primary_name", "primary_field", "u32"),
        ("position_name", "position_field", "u32"),
    ):
        production_name = spec[name_key]
        proof_name = spec[{
            "tag_name": "expected_tag",
            "primary_name": "expected_primary",
            "position_name": "expected_position",
        }[name_key]]
        value = spec[value_key]
        production = re.search(rf"(?m)^\s*const {production_name}: {type_name} = ([0-9]+)\s*$", encoding_text)
        proof = re.search(rf"(?m)^const {proof_name}: {type_name} = ([0-9]+)\s*$", positive_text)
        if production is None or int(production.group(1)) != value:
            raise SystemExit(f"production constant {production_name} no longer matches the stage0 schema")
        if proof is None or int(proof.group(1)) != value:
            raise SystemExit(f"independent proof constant {proof_name} changed")

    type_name = "NamedType" if shape == "Named" else "RefType"
    table = NAMED_TYPE_TABLE.read_text() if shape == "Named" else REF_TYPE_TABLE.read_text()
    block = compact(schema_block(table, type_name, spec["node_id"]))
    node_marker = compact(f'ir_uvarint_out(buffer, {spec["node_id"]})\nir_str_out(buffer, "{type_name}")')
    field_count_marker = compact(f'ir_uvarint_out(buffer, {spec["field_count"]})')
    primary_schema = compact(
        f'ir_field_desc_out(buffer, {spec["primary_field"]}, "{spec["wire_name"]}")\nbuffer.push({spec["primary_wire_type"]})'
    )
    position_schema = compact(
        f'ir_field_desc_out(buffer, {spec["position_field"]}, "Position")\nbuffer.push(7)'
    )
    if node_marker not in block or field_count_marker not in block or primary_schema not in block or position_schema not in block:
        raise SystemExit(f"stage0 {type_name} tag or field schema changed")

for name, field in (("node_type_id", "node_type_id"),
                    ("primary_field_id", "primary_field_id"),
                    ("position_field_id", "position_field_id")):
    body = compact(function_chunk(encoding_text, name))
    for shape, spec in expected.items():
        enum_name = "Named" if shape == "Named" else "ProvenanceRef"
        constant_name = spec[{
            "node_type_id": "tag_name",
            "primary_field_id": "primary_name",
            "position_field_id": "position_name",
        }[field]]
        if compact(f"ExternTypeShape.{enum_name}:{constant_name}") not in body:
            raise SystemExit(f"source {name} mapping changed for {shape}")

if writer_text.count('include "./frontend_ir_extern_type_encoding.elisa"') != 1:
    raise SystemExit("frontend IR writer must include the extern type encoding module exactly once")
if 'include "./frontend_ir_extern.elisa"' not in writer_text:
    raise SystemExit("frontend IR writer no longer imports the extern writer")

extern_type = compact(function_chunk(extern_text, "ir_extern_type_node"))
required_writer_fragments = (
    'iftype_name=="":ir_refuse(refusal,"externtypewithoutaname")return0',
    "ir_put_str(&bare_fields,&bare_live,FrontendIrExternTypeEncoding::NAMED_TYPE_NAME_FIELD_ID,type_name)",
    "ir_put_pos(&bare_fields,&bare_live,FrontendIrExternTypeEncoding::NAMED_TYPE_POSITION_FIELD_ID,type_pos,filename)",
    "ir_emit_node(bodies,nodes,FrontendIrExternTypeEncoding::NAMED_TYPE_NODE_TYPE_ID,bare_fields,bare_live)",
    "returnbare_idifnotprovenance_bearing",
    "ir_put_node(&ref_fields,&ref_live,FrontendIrExternTypeEncoding::REF_TYPE_ELEM_FIELD_ID,bare_id)",
    "ir_put_pos(&ref_fields,&ref_live,FrontendIrExternTypeEncoding::REF_TYPE_POSITION_FIELD_ID,type_pos,filename)",
    "ir_emit_node(bodies,nodes,FrontendIrExternTypeEncoding::REF_TYPE_NODE_TYPE_ID,ref_fields,ref_live)",
)
writer_positions = [extern_type.find(fragment) for fragment in required_writer_fragments]
if any(position < 0 for position in writer_positions) or writer_positions != sorted(writer_positions):
    raise SystemExit("extern type writer no longer uses the proved schema constants or empty-name refusal")
if re.search(r"ir_put_(?:str|node|pos)\([^)]*,[0-9]+,", extern_type) or re.search(r"ir_emit_node\([^)]*,[0-9]+,", extern_type):
    raise SystemExit("extern type writer reintroduced a numeric field or node ID")

expected_positive = {
    "source_extern_node_type_id_is_exact",
    "source_extern_primary_field_id_is_exact",
    "source_extern_position_field_id_is_exact",
    "extern_type_node_tags_are_distinct",
    "extern_type_position_fields_are_distinct",
    "shared_primary_field_slot_is_type_local",
}
expected_negative = {
    "reference_type_cannot_use_named_type_tag",
    "shared_primary_field_slot_does_not_force_shared_node_tag",
    "named_type_cannot_use_reference_position_field",
}


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


if declarations(positive_text) != expected_positive or declarations(negative_text) != expected_negative:
    raise SystemExit("extern type encoding proof theorem inventory changed")
if 'include "../../src/driver/frontend_ir_extern_type_encoding.elisa"' not in positive_text or 'include "../../src/driver/frontend_ir_extern_type_encoding.elisa"' not in negative_text:
    raise SystemExit("extern type proofs must include the production encoding module")
if any(f"FrontendIrExternTypeEncoding::{name}(shape)" not in positive_text for name in ("node_type_id", "primary_field_id", "position_field_id")):
    raise SystemExit("universal proofs must call all production extern type mappings")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("extern type encoding proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, ENCODING, WRITER, EXTERN_WRITER, NAMED_TYPE_TABLE, REF_TYPE_TABLE,
    HERE / "proof_product_gate.py", Path(__file__), POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, WRITER, EXTERN_WRITER]),
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=90)
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
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in expected_negative
}

assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "NamedType and provenance RefType tag/field mappings used by extern reconstruction",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
