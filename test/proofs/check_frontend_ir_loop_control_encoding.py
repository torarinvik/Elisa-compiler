"""Admit source-linked proofs for BreakStmt and ContinueStmt encodings."""
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
POSITIVE = HERE / "frontend_ir_loop_control_encoding.elisa"
NEGATIVE = HERE / "frontend_ir_loop_control_encoding_rejected.elisa"
ENCODING = ROOT / "src/driver/frontend_ir_loop_control_encoding.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
STMT_WRITER = ROOT / "src/driver/frontend_ir_stmt.elisa"
TYPE_TABLE = ROOT / "src/driver/frontend_ir_type_table_2.elisa"

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


def statement_arm(body: str, variant: str) -> str:
    lines = body.splitlines()
    starts = [i for i, line in enumerate(lines) if line.lstrip().startswith(f"Ast::Stmt.{variant}(")]
    if len(starts) != 1:
        raise SystemExit(f"expected one Ast::Stmt.{variant} arm")
    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        current_indent = len(line) - len(line.lstrip())
        if current_indent == indent and (line.lstrip().startswith("Ast::Stmt.") or line.lstrip() == "_:"):
            end = index
            break
    return "\n".join(lines[start:end])


def schema_block(text: str, name: str, node_id: int) -> str:
    marker = re.search(rf"(?m)^\s*# {re.escape(name)} \(type {node_id}\)\s*$", text)
    if marker is None:
        raise SystemExit(f"stage0 type table lost {name} type ID {node_id}")
    following = re.search(r"(?m)^\s*# [A-Za-z][A-Za-z0-9]* \(type [0-9]+\)\s*$", text[marker.end():])
    end = marker.end() + following.start() if following else len(text)
    return text[marker.start():end]


expected = {
    "Break": {
        "node": 19,
        "node_name": "BREAK_STMT_NODE_TYPE_ID",
        "expected_node": "EXPECTED_BREAK_STMT_NODE_TYPE_ID",
        "position_field": 1,
        "kind_name": "BreakStmt",
        "position_name": "break_pos",
        "label_name": "label",
        "refusal": "labelled break",
    },
    "Continue": {
        "node": 34,
        "node_name": "CONTINUE_STMT_NODE_TYPE_ID",
        "expected_node": "EXPECTED_CONTINUE_STMT_NODE_TYPE_ID",
        "position_field": 1,
        "kind_name": "ContinueStmt",
        "position_name": "continue_pos",
        "label_name": "label",
        "refusal": "labelled continue",
    },
}
POSITION_FIELD_NAME = "LOOP_CONTROL_POSITION_FIELD_ID"
EXPECTED_POSITION_FIELD_NAME = "EXPECTED_LOOP_CONTROL_POSITION_FIELD_ID"

encoding_text = ENCODING.read_text()
writer_text = WRITER.read_text()
stmt_text = STMT_WRITER.read_text()
table_text = TYPE_TABLE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

enum_match = re.search(
    r"(?ms)^[ \t]*const enum LoopControlKind of u8:\s*\n(.*?)(?=^[ \t]*const )",
    encoding_text,
)
if enum_match is None:
    raise SystemExit("LoopControlKind enum is missing or has no following constant section")
enum_variants = [line.strip() for line in enum_match.group(1).splitlines() if line.strip()]
if enum_variants != ["Break", "Continue"]:
    raise SystemExit("LoopControlKind constructor inventory changed without proof coverage")

for variant, spec in expected.items():
    production = re.search(rf"(?m)^\s*const {spec['node_name']}: u32 = ([0-9]+)\s*$", encoding_text)
    proof = re.search(rf"(?m)^const {spec['expected_node']}: u32 = ([0-9]+)\s*$", positive_text)
    if production is None or int(production.group(1)) != spec["node"]:
        raise SystemExit(f"production node constant for {variant} no longer matches stage0")
    if proof is None or int(proof.group(1)) != spec["node"]:
        raise SystemExit(f"independent proof node constant for {variant} changed")

    block = compact(schema_block(table_text, spec["kind_name"], spec["node"]))
    node_marker = compact(f'ir_uvarint_out(buffer, {spec["node"]})\nir_str_out(buffer, "{spec["kind_name"]}")')
    field_count = compact("ir_uvarint_out(buffer, 1)")
    position_schema = compact('ir_field_desc_out(buffer, 1, "Position")\nbuffer.push(7)')
    if node_marker not in block or field_count not in block or position_schema not in block:
        raise SystemExit(f"stage0 {spec['kind_name']} schema changed")

position_production = re.search(rf"(?m)^\s*const {POSITION_FIELD_NAME}: u32 = ([0-9]+)\s*$", encoding_text)
position_proof = re.search(rf"(?m)^const {EXPECTED_POSITION_FIELD_NAME}: u32 = ([0-9]+)\s*$", positive_text)
if position_production is None or int(position_production.group(1)) != 1:
    raise SystemExit("production loop-control position field ID changed")
if position_proof is None or int(position_proof.group(1)) != 1:
    raise SystemExit("independent loop-control position field ID changed")

mapping = compact(function_chunk(encoding_text, "node_type_id"))
position_mapping = compact(function_chunk(encoding_text, "position_field_id"))
label_mapping = compact(function_chunk(encoding_text, "label_is_unlabeled"))
if "ensureresult==(sview_len(label)==0)" not in label_mapping or "returnsview_len(label)==0" not in label_mapping:
    raise SystemExit("label encodability predicate no longer exactly tests an empty label")
for variant, spec in expected.items():
    if compact(f"LoopControlKind.{variant}:{spec['node_name']}") not in mapping:
        raise SystemExit(f"node_type_id mapping changed for {variant}")
    if compact(f"LoopControlKind.{variant}:{POSITION_FIELD_NAME}") not in position_mapping:
        raise SystemExit(f"position_field_id mapping changed for {variant}")

if writer_text.count('include "./frontend_ir_loop_control_encoding.elisa"') != 1:
    raise SystemExit("frontend IR writer must include the loop-control encoding module exactly once")
if 'include "./frontend_ir_stmt.elisa"' not in writer_text:
    raise SystemExit("frontend IR writer no longer imports statement writing")

stmt_body = function_chunk(stmt_text, "ir_stmt_node")
for variant, spec in expected.items():
    arm = compact(statement_arm(stmt_body, variant))
    expected_arm = compact(f'''
        Ast::Stmt.{variant}({spec["label_name"]}, {spec["position_name"]}):
            if not FrontendIrLoopControlEncoding::label_is_unlabeled({spec["label_name"]}):
                ir_refuse(refusal, "{spec["refusal"]}")
                return 0
            ir_put_pos(&fields, &live, FrontendIrLoopControlEncoding::{POSITION_FIELD_NAME}, {spec["position_name"]}, filename)
            return ir_emit_node(bodies, nodes, FrontendIrLoopControlEncoding::{spec["node_name"]}, fields, live)
    ''')
    if arm != expected_arm:
        raise SystemExit(f"{variant} writer arm changed from the exact fail-closed encoding")

expected_positive = {
    "source_loop_control_node_type_id_is_exact",
    "source_loop_control_position_field_id_is_exact",
    "source_loop_control_label_is_unlabeled_exact",
    "every_nonempty_loop_control_label_is_rejected",
    "break_and_continue_node_tags_are_distinct",
    "shared_position_slot_keeps_distinct_loop_control_nodes",
}
expected_negative = {
    "break_and_continue_cannot_have_distinct_node_tags",
    "continue_cannot_use_the_position_field",
}


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


if declarations(positive_text) != expected_positive or declarations(negative_text) != expected_negative:
    raise SystemExit("loop-control proof theorem inventory changed")
include = 'include "../../src/driver/frontend_ir_loop_control_encoding.elisa"'
if include not in positive_text or include not in negative_text:
    raise SystemExit("loop-control proofs must include the production encoding module")
if any(f"FrontendIrLoopControlEncoding::{name}(kind)" not in positive_text for name in ("node_type_id", "position_field_id")):
    raise SystemExit("universal proofs must call both production loop-control mappings")
if "FrontendIrLoopControlEncoding::label_is_unlabeled(label)" not in positive_text:
    raise SystemExit("label proof must call the production loop-control encodability predicate")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("loop-control encoding proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, ENCODING, WRITER, STMT_WRITER, TYPE_TABLE,
    HERE / "proof_product_gate.py", Path(__file__), POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, WRITER, STMT_WRITER]),
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
    "scope": "BreakStmt and ContinueStmt node tags, shared Position field, and label refusal",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
