"""Admit the borrow-field wildcard matcher against the production semantic pass."""
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
POSITIVE = HERE / "borrow_field_path_policy.elisa"
NEGATIVE = HERE / "borrow_field_path_policy_rejected.elisa"
POLICY = ROOT / "src/semantic/borrow_field_path_policy.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
BORROW_CHECK = ROOT / "src/semantic/check_borrow_after_move.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return " ".join(" ".join(line.split("#", 1)[0].split()) for line in source.splitlines()).strip()


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:@|(?:ghost[ \t]+)?def )", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def proof_body(source: str, name: str) -> str:
    section = function_section(source, name)
    colon = section.find(":\n")
    if colon < 0:
        raise SystemExit(f"could not find body of {name}")
    return compact(section[colon + 2:]).replace("can Abort.Panic: ", "")


expected_policy = """
def wildcard_matches(candidate: sview, field: sview, prefix_end: usize) -> bool:
    ensure result == (
        candidate.len > prefix_end and
        candidate.len - prefix_end == WILDCARD_SUFFIX_LENGTH and
        prefix_end < field.len and
        field[prefix_end] == ASCII_FIELD_SEPARATOR and
        candidate[prefix_end] == ASCII_FIELD_SEPARATOR and
        candidate[candidate.len - INDEX_STEP] == ASCII_WILDCARD and
        (forall prefix_index in 0..<prefix_end:
            candidate[prefix_index] == field[prefix_index])
    )
    can Abort.Panic:
        candidate_length: usize = candidate.len
        false return if prefix_end >= field.len
        false return if prefix_end >= candidate_length
        false return if candidate_length - prefix_end != WILDCARD_SUFFIX_LENGTH
        false return if field[prefix_end] != ASCII_FIELD_SEPARATOR
        false return if candidate[prefix_end] != ASCII_FIELD_SEPARATOR
        false return if candidate[candidate_length - INDEX_STEP] != ASCII_WILDCARD
        index: mutable usize = 0
        while index < prefix_end |index, candidate, field, prefix_end|:
            decreases prefix_end - index
            invariant index <= prefix_end
            invariant (forall prior in 0..<index:
                candidate[prior] == field[prior])
            false return if candidate[index] != field[index]
            index <- index + INDEX_STEP
        return true
"""
policy_text = POLICY.read_text()
if compact(function_section(policy_text, "wildcard_matches")) != compact(expected_policy):
    raise SystemExit("borrow field wildcard implementation or proof contract changed")
for declaration in (
    "const ASCII_FIELD_SEPARATOR: u8 = 46",
    "const ASCII_WILDCARD: u8 = 42",
    "const WILDCARD_SUFFIX_LENGTH: usize = 2",
    "const INDEX_STEP: usize = 1",
):
    if compact(declaration) not in compact(policy_text):
        raise SystemExit(f"borrow field wildcard byte policy changed: {declaration}")

semantic_text = SEMANTIC.read_text()
policy_include = 'include "./borrow_field_path_policy.elisa"'
borrow_include = 'include "./check_borrow_after_move.elisa"'
if policy_include not in semantic_text or borrow_include not in semantic_text or \
        semantic_text.index(policy_include) > semantic_text.index(borrow_include):
    raise SystemExit("production semantic module must load the proved wildcard policy before the borrow pass")
expected_wrapper = """
def bam_borrow_wildcard_matches(candidate: sview, field: sview, prefix_end: usize) -> bool:
    can Abort.Panic:
        return SemanticBorrowFieldPath::wildcard_matches(candidate, field, prefix_end)
"""
if compact(function_section(BORROW_CHECK.read_text(), "bam_borrow_wildcard_matches")) != compact(expected_wrapper):
    raise SystemExit("borrow flow no longer delegates wildcard matching to the proved policy")
borrow_text = BORROW_CHECK.read_text()
for caller in ("bam_borrow_wildcard_row", "bam_borrow_snapshot_owners"):
    caller_body = compact(function_section(borrow_text, caller))
    if "SemanticBorrowFieldPath::ASCII_FIELD_SEPARATOR" not in caller_body:
        raise SystemExit(f"{caller} must use the proved field-separator constant")
key_hash = compact(function_section(borrow_text, "bam_borrow_wildcard_key_hash"))
for hash_byte in (
    "BORROW_WILDCARD_KEY_HASH_NAME_SEPARATOR.u64()",
    "SemanticBorrowFieldPath::ASCII_FIELD_SEPARATOR.u64()",
    "SemanticBorrowFieldPath::ASCII_WILDCARD.u64()",
):
    if hash_byte not in key_hash:
        raise SystemExit(f"wildcard key hashing must use named byte constants: {hash_byte}")
if compact("const BORROW_WILDCARD_KEY_HASH_NAME_SEPARATOR: u8 = 255") not in compact(borrow_text):
    raise SystemExit("wildcard key hash name separator must remain an explicit domain byte")

positive_names = {
    "wildcard_matches_its_exact_byte_path_spec",
    "root_field_wildcard_matches_descendant",
    "nested_field_wildcard_matches_descendant",
    "field_path_prefix_must_match_exactly",
    "wildcard_suffix_requires_dot_then_star",
    "wildcard_suffix_must_end_at_candidate_boundary",
    "prefix_end_must_be_inside_the_field",
}
negative_names = {
    "mismatched_parent_is_accepted",
    "nonwildcard_suffix_is_accepted",
    "extra_suffix_byte_is_accepted",
    "out_of_range_prefix_is_accepted",
    "candidate_prefix_past_end_is_accepted",
}
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
for path, source, expected, label in (
    (POSITIVE, positive_text, positive_names, "positive"),
    (NEGATIVE, negative_text, negative_names, "negative"),
):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source))
    if actual != expected:
        raise SystemExit(f"{label} borrow-field proof declaration inventory changed")
    if '../../src/semantic/borrow_field_path_policy.elisa' not in source and path == POSITIVE:
        raise SystemExit("positive proof no longer imports the production wildcard matcher")
    for name in expected:
        if function_section(source, name).count("can Abort.Panic:") != 1:
            raise SystemExit(f"{label} proof must handle the production matcher effect: {name}")

formula = """(
    candidate.len > prefix_end and
    candidate.len - prefix_end == SemanticBorrowFieldPath::WILDCARD_SUFFIX_LENGTH and
    prefix_end < field.len and
    field[prefix_end] == SemanticBorrowFieldPath::ASCII_FIELD_SEPARATOR and
    candidate[prefix_end] == SemanticBorrowFieldPath::ASCII_FIELD_SEPARATOR and
    candidate[candidate.len - SemanticBorrowFieldPath::INDEX_STEP] == SemanticBorrowFieldPath::ASCII_WILDCARD and
    (forall prefix_index in 0..<prefix_end:
        candidate[prefix_index] == field[prefix_index])
)"""
expected_positive = {
    "wildcard_matches_its_exact_byte_path_spec": (
        "ensure result == true return SemanticBorrowFieldPath::wildcard_matches(candidate, field, prefix_end) == " + formula
    ),
    "root_field_wildcard_matches_descendant": (
        'ensure result == true return SemanticBorrowFieldPath::wildcard_matches("a.*", "a.member", 1.usize())'
    ),
    "nested_field_wildcard_matches_descendant": (
        'ensure result == true return SemanticBorrowFieldPath::wildcard_matches("root.child.*", "root.child.leaf", 10.usize())'
    ),
    "field_path_prefix_must_match_exactly": (
        'ensure result == false return SemanticBorrowFieldPath::wildcard_matches("root.child.*", "root.other.leaf", 10.usize())'
    ),
    "wildcard_suffix_requires_dot_then_star": (
        'ensure result == false return SemanticBorrowFieldPath::wildcard_matches("a.x", "a.child", 1.usize())'
    ),
    "wildcard_suffix_must_end_at_candidate_boundary": (
        'ensure result == false return SemanticBorrowFieldPath::wildcard_matches("a.**", "a.child", 1.usize())'
    ),
    "prefix_end_must_be_inside_the_field": (
        'ensure result == false return SemanticBorrowFieldPath::wildcard_matches("a.*", "a", 1.usize())'
    ),
}
for name, expected in expected_positive.items():
    if proof_body(positive_text, name) != compact(expected):
        raise SystemExit(f"positive borrow-field theorem changed: {name}")

expected_negative = {
    "mismatched_parent_is_accepted": 'ensure result == true return SemanticBorrowFieldPath::wildcard_matches("root.child.*", "root.other.leaf", 10.usize())',
    "nonwildcard_suffix_is_accepted": 'ensure result == true return SemanticBorrowFieldPath::wildcard_matches("a.x", "a.child", 1.usize())',
    "extra_suffix_byte_is_accepted": 'ensure result == true return SemanticBorrowFieldPath::wildcard_matches("a.**", "a.child", 1.usize())',
    "out_of_range_prefix_is_accepted": 'ensure result == true return SemanticBorrowFieldPath::wildcard_matches("a.*", "a", 1.usize())',
    "candidate_prefix_past_end_is_accepted": 'ensure result == true return SemanticBorrowFieldPath::wildcard_matches("a.*", "a..child", 3.usize())',
}
for name, expected in expected_negative.items():
    if proof_body(negative_text, name) != compact(expected):
        raise SystemExit(f"negative borrow-field false claim changed: {name}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("borrow-field proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    POLICY, SEMANTIC, BORROW_CHECK,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"] and not positive["findings"]
assert positive == run(POSITIVE)[1], "borrow-field proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] - negative["summary"]["proven"] == len(negative_names)
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact nested-field wildcard matching and bounds-safe prefix scan",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
