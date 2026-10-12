"""Replay source-linked slot-layout laws for the LLVM error-set ABI."""
import hashlib
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
PROOF = HERE / "error_set_payload_layout.elisa"
REJECTED = HERE / "error_set_payload_layout_rejected.elisa"
SOURCE = ROOT / "src/backend/codegen_abi_error_sets.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def compact(source: str) -> str:
    return "".join(source.split())


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    compact_body = compact(body)
    positions = [compact_body.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} no longer matches the checked ordered layout")


base_order = (
    "base: mutable usize = 1",
    "for offset in 0..<variant_offset",
    "base <- base + count",
    "return base",
)
try:
    require_ordered("base: mutable usize = 1; return base; for offset in 0..<variant_offset; base <- base + count", base_order, "mutation sentinel")
except SystemExit:
    pass
else:
    raise SystemExit("error-set layout order guard accepted return-before-accumulation mutation")


proof_text = PROOF.read_text()
source_text = SOURCE.read_text()
base_body = function_section(source_text, "error_set_variant_field_base")
llvm_body = function_section(source_text, "error_set_llvm_type")
require_ordered(base_body, (
    "variant_start: usize = structs.payload_enums.penum_variant_start[set_index.usize()]",
    "base: mutable usize = 1",
    "for offset in 0..<variant_offset",
    "base <- base + structs.payload_enums.penum_field_type_count[variant_start + offset]",
    "return base",
), "error-set variant base")
base_compact = compact(base_body)
if (base_compact.count("foroffsetin0..<variant_offset") != 1 or
        base_compact.count("base<-base+structs.payload_enums.penum_field_type_count[variant_start+offset]") != 1):
    raise SystemExit("error-set variant base changed its prefix accumulator cardinality")
require_ordered(llvm_body, (
    "variant_start: usize = structs.payload_enums.penum_variant_start[set_index.usize()]",
    "variant_span: usize = structs.payload_enums.penum_variant_count[set_index.usize()]",
    "set_fields: mutable darray[LLVMTypeRef] = [LLVMInt32TypeInContext(ctx)]",
    "for offset in 0..<variant_span",
    "field_start: usize = structs.payload_enums.penum_field_type_start[variant_start + offset]",
    "field_span: usize = structs.payload_enums.penum_field_type_count[variant_start + offset]",
    "for field_offset in 0..<field_span",
    "set_fields.push(llvm_type_of(copied_type(structs.payload_enums.penum_field_types[field_start + field_offset]), structs, ctx))",
    "return LLVMStructTypeInContext(ctx, set_pointer, set_fields.count.u32(), 0)",
), "error-set LLVM layout")
llvm_compact = compact(llvm_body)
if (llvm_compact.count("foroffsetin0..<variant_span") != 1 or
        llvm_compact.count("forfield_offsetin0..<field_span") != 1 or
        llvm_compact.count("set_fields.push(llvm_type_of(") != 1):
    raise SystemExit("error-set LLVM layout changed its single nested payload traversal")

# The production nesting is part of the mapping: every field iteration belongs to its
# variant iteration, and the push belongs to that field iteration.
llvm_lines = llvm_body.splitlines()
outer_line = next((line for line in llvm_lines if "for offset in 0..<variant_span" in line), None)
inner_line = next((line for line in llvm_lines if "for field_offset in 0..<field_span" in line), None)
push_line = next((line for line in llvm_lines if "set_fields.push(llvm_type_of" in line), None)
if outer_line is None or inner_line is None or push_line is None:
    raise SystemExit("error-set LLVM layout lost a payload iteration step")
indent = lambda line: len(line) - len(line.lstrip(" "))
if not indent(outer_line) < indent(inner_line) < indent(push_line):
    raise SystemExit("error-set payload field insertion is no longer nested under variant and field loops")

models = {
    "error_tag_precedes_every_payload": (
        "error_tag_precedes_every_payload(prefix_fields: i64, field_index: i64) -> bool:",
        ("requires prefix_fields >= 0 and prefix_fields <= 1000000",
         "requires field_index >= 0 and field_index <= 1000000"),
        "return 0 < 1 + prefix_fields + field_index",
    ),
    "variant_payload_slot_is_inside_its_region": (
        "variant_payload_slot_is_inside_its_region(base: i64, span: i64, field_index: i64) -> bool:",
        ("requires base >= 1 and base <= 1000000",
         "requires span >= 0 and span <= 1000000",
         "requires field_index >= 0 and field_index < span"),
        "return base + field_index < base + span",
    ),
    "adjacent_payload_regions_do_not_overlap": (
        "adjacent_payload_regions_do_not_overlap(base: i64, prior_span: i64, prior_index: i64, next_index: i64) -> bool:",
        ("requires base >= 1 and base <= 1000000",
         "requires prior_span > 0 and prior_span <= 1000000",
         "requires prior_index >= 0 and prior_index < prior_span",
         "requires next_index >= 0 and next_index <= 1000000"),
        "return base + prior_index < base + prior_span + next_index",
    ),
}
for name, (signature, requirements, conclusion) in models.items():
    section = function_section(proof_text, name)
    if signature not in section:
        raise SystemExit(f"{name} has an unexpected signature")
    actual_requirements = tuple(line.strip() for line in section.splitlines() if line.strip().startswith("requires "))
    if actual_requirements != requirements or "ensure result == true" not in section or conclusion not in section:
        raise SystemExit(f"{name} no longer proves the checked slot-layout property")
if set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", proof_text, re.MULTILINE)) != set(models):
    raise SystemExit("error-set layout proof contains a missing or unreviewed theorem")

negative_models = {
    "payload_can_precede_the_error_tag": (
        "payload_can_precede_the_error_tag(prefix_fields: i64, field_index: i64) -> bool:",
        ("requires prefix_fields >= 0 and prefix_fields <= 1000000",
         "requires field_index >= 0 and field_index <= 1000000"),
        "return 1 + prefix_fields + field_index <= 0",
    ),
    "a_payload_slot_can_escape_its_variant_region": (
        "a_payload_slot_can_escape_its_variant_region(base: i64, span: i64, field_index: i64) -> bool:",
        ("requires base >= 1 and base <= 1000000",
         "requires span >= 0 and span <= 1000000",
         "requires field_index >= 0 and field_index < span"),
        "return base + field_index >= base + span",
    ),
    "adjacent_payload_regions_can_overlap": (
        "adjacent_payload_regions_can_overlap(base: i64, prior_span: i64, prior_index: i64, next_index: i64) -> bool:",
        ("requires base >= 1 and base <= 1000000",
         "requires prior_span > 0 and prior_span <= 1000000",
         "requires prior_index >= 0 and prior_index < prior_span",
         "requires next_index >= 0 and next_index <= 1000000"),
        "return base + prior_index >= base + prior_span + next_index",
    ),
}
rejected_text = REJECTED.read_text()
for name, (signature, requirements, conclusion) in negative_models.items():
    section = function_section(rejected_text, name)
    if signature not in section:
        raise SystemExit(f"negative control {name} has an unexpected signature")
    actual_requirements = tuple(line.strip() for line in section.splitlines() if line.strip().startswith("requires "))
    if actual_requirements != requirements or "ensure result == true" not in section or conclusion not in section:
        raise SystemExit(f"negative control {name} no longer claims a false slot-layout property")
if set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", rejected_text, re.MULTILINE)) != set(negative_models):
    raise SystemExit("error-set layout negative-control inventory changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("error-set payload layout proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    PROOF,
    REJECTED,
    SOURCE,
    *source_include_closure([PROOF, REJECTED, SOURCE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                            text=True, timeout=60)
    report = json.loads(result.stdout)
    assert report["summary"]["semantic_errors"] == 0 and not report["semantic_diagnostics"]
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return result.returncode, report


positive_code, positive = run(PROOF)
assert positive_code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(models)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 6
assert positive["replay"] == {"certificates": 6, "replayed": 6, "gaps": 0}
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == set(models)
assert positive == run(PROOF)[1], "error-set payload layout proof report changed across repeated runs"

negative_code, negative = run(REJECTED)
assert negative_code == 1 and negative["status"] == "failed"
assert negative["verification_state"] in {"unknown", "disproved"}
assert negative["summary"]["declarations"] == len(negative_models)
assert negative["summary"]["obligations"] == 6 and negative["summary"]["proven"] == 3
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_models
}
if negative["verification_state"] == "disproved":
    assert all(finding["status"] == "disproved" and finding["counterexample_found"]
               for finding in negative["findings"])
else:
    # These are non-admission controls only. An unknown/timeout result is inconclusive,
    # not a proof that the false layout claims have been refuted.
    assert all(finding["status"] in {"unknown", "timeout"} and not finding["counterexample_found"]
               for finding in negative["findings"])
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
if hashes_before != hashes_after:
    raise SystemExit("error-set layout proof inputs changed while the checker was running")
