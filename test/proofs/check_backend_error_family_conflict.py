"""Admit the source-linked duplicate-family conflict gate for function error metadata."""
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
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
SOURCE = ROOT / "src/backend/codegen_fn_types.elisa"
POSITIVE = HERE / "backend_error_family_conflict.elisa"
NEGATIVE = HERE / "backend_error_family_conflict_rejected.elisa"

POSITIVE_SHAPES = {
    "duplicate_conflict_gate_is_exact": (
        "ensure result == (line_matches and offset_matches and found_nonempty and not same_family) "
        "return line_matches and offset_matches and found_nonempty and not same_family"
    ),
    "unmatched_row_cannot_conflict": (
        "requires not line_matches or not offset_matches ensure result == false "
        "return line_matches and offset_matches and found_nonempty and not same_family"
    ),
    "first_matching_row_cannot_conflict": (
        "requires line_matches and offset_matches and not found_nonempty ensure result == false "
        "return line_matches and offset_matches and found_nonempty and not same_family"
    ),
    "consistent_matching_duplicate_cannot_conflict": (
        "requires line_matches and offset_matches and found_nonempty and same_family ensure result == false "
        "return line_matches and offset_matches and found_nonempty and not same_family"
    ),
    "conflicting_matching_duplicate_must_conflict": (
        "requires line_matches and offset_matches and found_nonempty and not same_family ensure result == true "
        "return line_matches and offset_matches and found_nonempty and not same_family"
    ),
    "mismatch_without_prior_family_cannot_conflict": (
        "requires line_matches and offset_matches and not found_nonempty and not same_family ensure result == false "
        "return line_matches and offset_matches and found_nonempty and not same_family"
    ),
}
NEGATIVE_NAMES = {
    "false_claim_unmatched_row_conflicts",
    "false_claim_consistent_duplicate_conflicts",
    "false_claim_first_match_conflicts",
    "false_claim_conflict_is_accepted",
}
ELISA_INDENT_WIDTH = 4
PROOF_PROCESS_TIMEOUT_SECONDS = 60
POSITIVE_OBLIGATION_COUNT = 12
NEGATIVE_OBLIGATION_COUNT = 20
NEGATIVE_PROVEN_OBLIGATION_COUNT = 16
LEGACY_SOURCE_FRAGMENTS = (
    'found:mutablesview=""',
    "continueifstructs.function_types.fn_error_lines[index]!=lineorstructs.function_types.fn_error_offsets[index]!=offset",
    'return""iffound!=""andfound!=structs.function_types.fn_error_families[index]',
    "found<-structs.function_types.fn_error_families[index]",
    "returnfound",
)


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def direct_children(lines: list[str], parent_index: int, parent_indent: int) -> list[tuple[int, str]]:
    children = []
    for index in range(parent_index + 1, len(lines)):
        line = lines[index]
        content = line.lstrip(" \t")
        if not content or content.startswith("#"):
            continue
        indent = len(line) - len(content)
        if indent <= parent_indent:
            break
        if indent == parent_indent + ELISA_INDENT_WIDTH:
            children.append((index, content))
    return children


def legacy_ordered_anchors_pass(source: str) -> bool:
    source_body = compact(function_section(source, "fn_error_family_at_offset"))
    positions = [source_body.find(fragment) for fragment in LEGACY_SOURCE_FRAGMENTS]
    return (all(position >= 0 for position in positions) and
            positions == sorted(positions) and source_body.count('return""') == 1)


def require_conflict_source_layout(source: str) -> None:
    section = function_section(source, "fn_error_family_at_offset")
    if not legacy_ordered_anchors_pass(source):
        raise SystemExit("error-family conflict return must follow location matching and precede the found update")

    lines = section.splitlines()
    header_index = next((index for index, line in enumerate(lines)
                         if re.match(r"\s*def fn_error_family_at_offset\(", line)), None)
    if header_index is None:
        raise SystemExit("error-family lookup function header is missing")
    header = lines[header_index]
    function_indent = len(header) - len(header.lstrip(" \t"))
    function_children = direct_children(lines, header_index, function_indent)
    expected_function_children = [
        "paired: mutable usize = structs.function_types.fn_error_lines.count if structs.function_types.fn_error_lines.count < structs.function_types.fn_error_families.count else structs.function_types.fn_error_families.count",
        "paired <- structs.function_types.fn_error_offsets.count if structs.function_types.fn_error_offsets.count < paired",
        'found: mutable sview = ""',
        "for index in 0..<paired |found, offset, line, structs|:",
        "return found",
    ]
    if [line for _, line in function_children] != expected_function_children:
        raise SystemExit("error-family scan must clamp paired rows to all three parallel-array bounds")
    loop_rows = [(index, line) for index, line in function_children if line.startswith("for ")]
    if len(loop_rows) != 1 or compact(loop_rows[0][1]) != "forindexin0..<paired|found,offset,line,structs|:":
        raise SystemExit("error-family lookup must contain one directly scoped location scan")
    loop_index = loop_rows[0][0]
    loop_indent = len(lines[loop_index]) - len(lines[loop_index].lstrip(" \t"))
    loop_children = direct_children(lines, loop_index, loop_indent)
    expected_loop_children = [
        "continueifstructs.function_types.fn_error_lines[index]!=lineorstructs.function_types.fn_error_offsets[index]!=offset",
        'return""iffound!=""andfound!=structs.function_types.fn_error_families[index]',
        "found<-structs.function_types.fn_error_families[index]",
    ]
    if [compact(line) for _, line in loop_children] != expected_loop_children:
        raise SystemExit("location skip, conflict return, and family update must be direct loop steps in order")
    if not any(line == "return found" and index > loop_index for index, line in function_children):
        raise SystemExit("error-family lookup must return its accumulated family after scanning")


source_text = SOURCE.read_text()
require_conflict_source_layout(source_text)
mutated_return = source_text.replace(
    '                return "" if found != "" and found != structs.function_types.fn_error_families[index]',
    '            return "" if found != "" and found != structs.function_types.fn_error_families[index]',
    1,
)
if mutated_return == source_text:
    raise SystemExit("could not construct the loop-exit mutation regression")
if not legacy_ordered_anchors_pass(mutated_return):
    raise SystemExit("loop-exit mutation no longer passes the legacy ordered-anchor regression")
try:
    require_conflict_source_layout(mutated_return)
except SystemExit:
    pass
else:
    raise SystemExit("source layout gate accepted a conflict return moved outside the location loop")

bound_mutations = (
    (
        "zero paired-row bound",
        "paired: mutable usize = structs.function_types.fn_error_lines.count if structs.function_types.fn_error_lines.count < structs.function_types.fn_error_families.count else structs.function_types.fn_error_families.count",
        "paired: mutable usize = 0",
    ),
    (
        "missing offset-row clamp",
        "paired <- structs.function_types.fn_error_offsets.count if structs.function_types.fn_error_offsets.count < paired",
        "paired <- structs.function_types.fn_error_offsets.count",
    ),
)
for description, original, replacement in bound_mutations:
    mutated_bound = source_text.replace(original, replacement, 1)
    if mutated_bound == source_text:
        raise SystemExit(f"could not construct the {description} mutation regression")
    if not legacy_ordered_anchors_pass(mutated_bound):
        raise SystemExit(f"{description} mutation no longer passes the legacy ordered-anchor regression")
    try:
        require_conflict_source_layout(mutated_bound)
    except SystemExit:
        pass
    else:
        raise SystemExit(f"source layout gate accepted the {description} mutation")

positive_names = set(POSITIVE_SHAPES)
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("error-family conflict proof inventory is incomplete or contains extras")
for name, shape in POSITIVE_SHAPES.items():
    if compact(shape) not in compact(function_section(POSITIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer states its intended conflict-gate property")
if 'include "./backend_error_family_conflict.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the positive source-linked model")

if args.source_only:
    print(json.dumps({"source_bound": True, "positive_shapes": len(POSITIVE_SHAPES), "negative_controls": len(NEGATIVE_NAMES)}, sort_keys=True))
    raise SystemExit(0)


try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("error-family conflict proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_PROCESS_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert (positive["summary"]["obligations"] ==
        positive["summary"]["proven"] == POSITIVE_OBLIGATION_COUNT)
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(NEGATIVE_NAMES)
assert (negative["summary"]["obligations"] == NEGATIVE_OBLIGATION_COUNT and
        negative["summary"]["proven"] == NEGATIVE_PROVEN_OBLIGATION_COUNT)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == product
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay or final provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "a location-matching row with an existing nonempty, different error family returns the empty sentinel before updating the accumulator",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
