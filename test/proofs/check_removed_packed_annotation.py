"""Admit a source-linked proof of the removed packed-annotation diagnostics."""
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
SOURCE = ROOT / "src/semantic/check_removed_packed_annotation.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARALLEL_PASSES = ROOT / "src/semantic/semantic_parallel_passes.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
POSITIVE = HERE / "removed_packed_annotation.elisa"
NEGATIVE = HERE / "removed_packed_annotation_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

REMOVED_PACKED_PASS_ID = 208
REMOVED_PACKED_BATCH_START = 208
REMOVED_PACKED_BATCH_SIZE = 3

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def code_signature(source: str, function_name: str):
    lines = function_section(source, function_name).splitlines()
    code_lines = [line.split("#", 1)[0].rstrip() for line in lines]
    first = next((line for line in code_lines if line.strip()), "")
    base_indent = len(first) - len(first.lstrip(" \t"))
    return tuple(
        (len(line) - len(line.lstrip(" \t")) - base_indent, compact(line))
        for line in code_lines if line.strip()
    )


def wrapped_loop_mutation(source: str) -> str:
    lines = source.splitlines()
    markers = [index for index, line in enumerate(lines)
               if line.strip() == "for annotation in file.enum_annotations |table|:"]
    if len(markers) != 1:
        return source
    start = markers[0]
    indent = len(lines[start]) - len(lines[start].lstrip(" \t"))
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= indent:
            break
        end += 1
    lines.insert(start, " " * indent + "if false:")
    for index in range(start + 1, end + 1):
        lines[index] = "    " + lines[index]
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


source_text = SOURCE.read_text()
expected_function = """def check_removed_packed_annotation(file: Ast::File&, table: lmut SymbolTable) -> void:
    can Memory.Allocate, Abort.Panic:
        for annotation in file.enum_annotations |table|:
            table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.RemovedPackedAbiAnnotation, name: annotation.owner, line: annotation.line, expected: "", actual: ""}) if annotation.name == "packed_abi"
            table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.RemovedPackedPrefixAnnotation, name: annotation.owner, line: annotation.line, expected: "", actual: ""}) if annotation.name == "packed_prefix"
            table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.RemovedCbindPrefixAnnotation, name: annotation.owner, line: annotation.line, expected: "", actual: ""}) if annotation.name == "c_bind_prefix"
"""
if code_signature(source_text, "check_removed_packed_annotation") != code_signature(expected_function, "check_removed_packed_annotation"):
    raise SystemExit("removed packed-annotation pass no longer matches its exact guarded diagnostic loop")

proof_text = POSITIVE.read_text()
expected_policy = """def diagnostic_name(annotation_name: sview) -> sview:
    ensure result == (
        when annotation_name:
            "packed_abi" -> PACKED_ABI_DIAGNOSTIC_NAME
            "packed_prefix" -> PACKED_PREFIX_DIAGNOSTIC_NAME
            "c_bind_prefix" -> CBIND_PREFIX_DIAGNOSTIC_NAME
            _ -> ""
    )
    return when annotation_name:
        "packed_abi" -> PACKED_ABI_DIAGNOSTIC_NAME
        "packed_prefix" -> PACKED_PREFIX_DIAGNOSTIC_NAME
        "c_bind_prefix" -> CBIND_PREFIX_DIAGNOSTIC_NAME
        _ -> ""
"""
expected_mapping_theorem = """def source_removed_annotation_mapping_is_exact(annotation_name: sview) -> sview:
    ensure result == (
        when annotation_name:
            "packed_abi" -> RemovedPackedAnnotationSpecification::PACKED_ABI_DIAGNOSTIC_NAME
            "packed_prefix" -> RemovedPackedAnnotationSpecification::PACKED_PREFIX_DIAGNOSTIC_NAME
            "c_bind_prefix" -> RemovedPackedAnnotationSpecification::CBIND_PREFIX_DIAGNOSTIC_NAME
            _ -> ""
    )
    return RemovedPackedAnnotationSpecification::diagnostic_name(annotation_name)
"""
if code_signature(proof_text, "diagnostic_name") != code_signature(expected_policy, "diagnostic_name"):
    raise SystemExit("proof classifier no longer matches the exact removed-annotation pattern table")
if code_signature(proof_text, "source_removed_annotation_mapping_is_exact") != code_signature(expected_mapping_theorem, "source_removed_annotation_mapping_is_exact"):
    raise SystemExit("source-linked theorem no longer states the exact removed-annotation contract")

annotation_pairs = (
    ("packed_abi", "RemovedPackedAbiAnnotation"),
    ("packed_prefix", "RemovedPackedPrefixAnnotation"),
    ("c_bind_prefix", "RemovedCbindPrefixAnnotation"),
)
for annotation_name, diagnostic_name in annotation_pairs:
    if compact(source_text).count(f"annotation.name==\"{annotation_name}\"") != 1:
        raise SystemExit(f"production pass no longer checks {annotation_name} exactly once")
    if compact(source_text).count(f"kind:DiagnosticKind.{diagnostic_name}") != 1:
        raise SystemExit(f"production pass no longer emits {diagnostic_name} exactly once")
if compact(source_text).count("name:annotation.owner,line:annotation.line") != len(annotation_pairs):
    raise SystemExit("removed packed-annotation diagnostics no longer identify the source annotation owner and line")
if 'include "./check_removed_packed_annotation.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic root no longer includes the removed packed-annotation pass")
parallel = compact(PARALLEL_PASSES.read_text())
if f"ifpass_id=={REMOVED_PACKED_PASS_ID}:table<-check_removed_packed_annotation(loop_view,table)" not in parallel:
    raise SystemExit("parallel semantic dispatch no longer calls the proved removed packed-annotation pass")
pipeline = compact(SEMANTIC_API.read_text())
if f"par_pass_run(file,&loop_view,flags,table,shared_pool,{REMOVED_PACKED_BATCH_START},{REMOVED_PACKED_BATCH_SIZE})" not in pipeline:
    raise SystemExit("semantic pipeline no longer schedules the removed packed-annotation pass")

mutations = (
    source_text.replace('annotation.name == "packed_abi"', 'annotation.name == "packed_abi_v2"', 1),
    source_text.replace("DiagnosticKind.RemovedPackedPrefixAnnotation", "DiagnosticKind.RemovedPackedAbiAnnotation", 1),
    source_text.replace('name: annotation.owner, line: annotation.line', 'name: "", line: annotation.line', 1),
    wrapped_loop_mutation(source_text),
)
for mutation in mutations:
    if mutation == source_text or code_signature(mutation, "check_removed_packed_annotation") == code_signature(expected_function, "check_removed_packed_annotation"):
        raise SystemExit("source checker failed to detect a diagnostic mapping or unreachable-loop mutation")

positive_names = {
    "source_removed_annotation_mapping_is_exact",
    "each_removed_annotation_has_its_diagnostic",
    "nearby_annotation_names_are_not_removed",
    "removed_annotation_diagnostic_names_are_distinct",
}
negative_names = {
    "false_packed_abi_has_no_diagnostic",
    "false_prefix_uses_abi_diagnostic",
    "false_unknown_annotation_has_a_diagnostic",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != expected:
        raise SystemExit(f"{path.name} theorem inventory changed")

for annotation_name, diagnostic_name in annotation_pairs:
    if f'"{annotation_name}"' not in proof_text or f'"{diagnostic_name}"' not in proof_text:
        raise SystemExit(f"proof no longer covers the production mapping {annotation_name} -> {diagnostic_name}")
if 'include "./removed_packed_annotation.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer exercise the admitted annotation classifier")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("removed packed-annotation proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    SOURCE, SEMANTIC, PARALLEL_PASSES, SEMANTIC_API, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
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
assert positive["summary"]["declarations"] == positive["summary"]["proven"] == len(positive_names)
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "removed packed-annotation proof report changed across repeated runs"
assert positive_names == {row["name"] for row in positive["declaration_details"] if row.get("verified")}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] in {"failed", "disproved"}
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "exact removed packed annotation names, diagnostic kinds, and scheduled semantic pass",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
