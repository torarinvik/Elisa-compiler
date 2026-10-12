"""Admit the function return-type pool read guard against backend source."""
from __future__ import annotations

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
SOURCE = ROOT / "src/backend/codegen_fn_types.elisa"
POSITIVE = HERE / "backend_fn_return_pool_bounds.elisa"
NEGATIVE = HERE / "backend_fn_return_pool_bounds_rejected.elisa"

POSITIVE_SHAPES = {
    "fn_return_pool_read_is_selected": (
        "ensure result == (is_fn and index_in_bounds) return is_fn and index_in_bounds"
    ),
    "non_function_never_reads_fn_return_pool": (
        "requires not is_fn ensure result == false return is_fn and index_in_bounds"
    ),
    "out_of_range_function_never_reads_fn_return_pool": (
        "requires is_fn and not index_in_bounds ensure result == false "
        "return is_fn and index_in_bounds"
    ),
    "in_range_function_reads_fn_return_pool": (
        "requires is_fn and index_in_bounds ensure result == true "
        "return is_fn and index_in_bounds"
    ),
}
NEGATIVE_SHAPES = {
    "false_claim_non_function_reads_fn_return_pool": (
        "requires not is_fn ensure result == true return is_fn and index_in_bounds"
    ),
    "false_claim_out_of_range_function_reads_fn_return_pool": (
        "requires is_fn and not index_in_bounds ensure result == true "
        "return is_fn and index_in_bounds"
    ),
}
ELISA_INDENT_WIDTH = 4
PROOF_PROCESS_TIMEOUT_SECONDS = 60
POSITIVE_OBLIGATION_COUNT = 8
NEGATIVE_OBLIGATION_COUNT = 12
NEGATIVE_PROVEN_OBLIGATION_COUNT = 10
RETURN_POOL_SOURCE_FRAGMENTS = (
    "unmodeled_type()returniffn_type.kind!=TypeKind.Fn",
    "unmodeled_type()returniffn_type.bits.usize()>=structs.function_types.fn_pool_returns.count",
    "returncopied_type(structs.function_types.fn_pool_returns[fn_type.bits.usize()])",
)

if not __debug__:
    raise SystemExit("run without Python -O")


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


def direct_children(lines: list[str], parent_index: int, parent_indent: int) -> list[str]:
    children = []
    for line in lines[parent_index + 1:]:
        content = line.lstrip(" \t")
        if not content or content.startswith("#"):
            continue
        indent = len(line) - len(content)
        if indent <= parent_indent:
            break
        if indent == parent_indent + ELISA_INDENT_WIDTH:
            children.append(content)
    return children


def require_return_pool_layout(source: str) -> None:
    section = function_section(source, "fn_return_type_of")
    body = compact(section)
    positions = [body.find(fragment) for fragment in RETURN_POOL_SOURCE_FRAGMENTS]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("fn return metadata must check kind and pool bounds before reading the side table")
    if body.count("structs.function_types.fn_pool_returns[") != 1:
        raise SystemExit("the guarded return-type lookup must be the only return-pool read")

    lines = section.splitlines()
    header_index = next((index for index, line in enumerate(lines)
                         if re.match(r"\s*def fn_return_type_of\(", line)), None)
    if header_index is None:
        raise SystemExit("fn return-type lookup function header is missing")
    header = lines[header_index]
    function_indent = len(header) - len(header.lstrip(" \t"))
    expected_children = [
        "unmodeled_type() return if fn_type.kind != TypeKind.Fn",
        "unmodeled_type() return if fn_type.bits.usize() >= structs.function_types.fn_pool_returns.count",
        "return copied_type(structs.function_types.fn_pool_returns[fn_type.bits.usize()])",
    ]
    children = direct_children(lines, header_index, function_indent)
    if children != expected_children:
        raise SystemExit("kind guard, pool bound, and return-pool read must be direct function steps in order")


source_text = SOURCE.read_text()
require_return_pool_layout(source_text)
mutated_bounds_guard = source_text.replace(
    "            unmodeled_type() return if fn_type.bits.usize() >= structs.function_types.fn_pool_returns.count",
    "            if fn_type.kind != TypeKind.Fn:\n                unmodeled_type() return if fn_type.bits.usize() >= structs.function_types.fn_pool_returns.count",
    1,
)
if mutated_bounds_guard == source_text:
    raise SystemExit("could not construct the misplaced bounds-guard mutation regression")
legacy_body = compact(function_section(mutated_bounds_guard, "fn_return_type_of"))
legacy_positions = [legacy_body.find(fragment) for fragment in RETURN_POOL_SOURCE_FRAGMENTS]
if (any(position < 0 for position in legacy_positions) or
        legacy_positions != sorted(legacy_positions) or
        legacy_body.count("structs.function_types.fn_pool_returns[") != 1):
    raise SystemExit("misplaced bounds-guard mutation no longer passes the legacy anchor regression")
try:
    require_return_pool_layout(mutated_bounds_guard)
except SystemExit:
    pass
else:
    raise SystemExit("source layout gate accepted a bounds guard nested under the non-function branch")

positive_names = set(POSITIVE_SHAPES)
negative_names = set(NEGATIVE_SHAPES)
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names:
    raise SystemExit("function return-pool proof inventory is incomplete or contains extras")
for path, shapes in ((POSITIVE, POSITIVE_SHAPES), (NEGATIVE, NEGATIVE_SHAPES)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer states its intended pool-safety condition")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("function return-pool proof requires a strict proof build")

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
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert (negative["summary"]["obligations"] == NEGATIVE_OBLIGATION_COUNT and
        negative["summary"]["proven"] == NEGATIVE_PROVEN_OBLIGATION_COUNT)
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "first-class function return-pool reads require a function kind and an in-bounds pool index",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
