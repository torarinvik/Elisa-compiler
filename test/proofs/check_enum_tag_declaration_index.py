"""Source-bind and replay the first-match enum-tag index proof."""
from __future__ import annotations

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
SOURCE = ROOT / "src/semantic/enum_tag_declaration_index.elisa"
LOOKUP_SOURCE = ROOT / "src/semantic/enum_tag_lookup_index.elisa"
CHECK = ROOT / "src/semantic/check_enum_tag_index.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARITY = ROOT / "test/parity/enum_tag_declaration_index_smoke.elisa"
POSITIVE = HERE / "enum_tag_declaration_index.elisa"
NEGATIVE = HERE / "enum_tag_declaration_index_rejected.elisa"
POSITIVE_NAMES = {
    "duplicate_enum_names_keep_the_first_count",
    "absent_enum_names_return_zero",
    "a_short_count_array_fails_closed",
}
NEGATIVE_NAMES = {"a_duplicate_enum_name_returns_the_last_count"}
NEGATIVE_CLAIM_NAMES = {"a_duplicate_enum_name_returns_the_last_count"}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact_code(text: str) -> tuple[str, ...]:
    """Normalize whitespace and comments while retaining line structure and token gaps."""
    lines = []
    for line in text.splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            expanded = code.expandtabs(4)
            indent = len(expanded) - len(expanded.lstrip())
            lines.append((indent, " ".join(expanded.lstrip().split())))
    if not lines:
        return ()
    base = min(indent for indent, _ in lines)
    return tuple(" " * (indent - base) + code for indent, code in lines)


def function_section(text: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", text))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    end = len(text)
    for line_match in re.finditer(r"(?m)^.*(?:\n|$)", text[match.end():]):
        line = line_match.group(0)
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        expanded = line.expandtabs(4)
        line_indent = len(expanded) - len(expanded.lstrip())
        peer_declaration = line_indent == len(indent) and re.match(r"(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", stripped)
        section_boundary = line_indent <= len(indent) and stripped in {"public:", "private:"}
        if peer_declaration or section_boundary or (line_indent <= len(indent) and stripped.startswith("include ")):
            end = match.end() + line_match.start()
            break
    return text[match.start():end]


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


def one_line(text: str) -> str:
    lines = compact_code(text)
    if len(lines) != 1:
        raise SystemExit("expected a single-line source fragment")
    return lines[0].strip()


source_text = SOURCE.read_text()
lookup_text = LOOKUP_SOURCE.read_text()
check_text = CHECK.read_text()
semantic_text = SEMANTIC.read_text()
parity_text = PARITY.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_lookup = '''
def indexed_enum_tag_count(names: darray[sview]&, counts: darray[i64]&, name: sview) -> i64:
    ensure result == enum_tag_count_from(names, counts, name, 0)
    can Abort.Panic:
        index: mutable usize = 0
        while index < names.count |index|:
            decreases names.count - index
            invariant index <= names.count
            invariant enum_tag_count_from(names, counts, name, index) == enum_tag_count_from(names, counts, name, 0)
            return 0 if index >= counts.count
            return counts[index] if names[index] == name
            index <- index + 1
        return 0
'''
if compact_code(function_section(lookup_text, "indexed_enum_tag_count")) != compact_code(expected_lookup):
    raise SystemExit("production enum-tag lookup contract or loop refinement changed without updating its proof")

expected_reference = '''
ghost def enum_tag_count_from(names: darray[sview]&, counts: darray[i64]&, name: sview, index: usize) -> i64:
    requires index <= names.count
    decreases names.count - index
    return 0 if index == names.count
    return 0 if index >= counts.count
    return counts[index] if names[index] == name
    return enum_tag_count_from(names, counts, name, index + 1)
'''
if compact_code(function_section(lookup_text, "enum_tag_count_from")) != compact_code(expected_reference):
    raise SystemExit("production recursive specification changed without updating the first-match proof")

expected_collector = '''
def collect_enum_tag_declarations(declarations: darray[Ast::Decl], names: mutable darray[sview]&, counts: mutable darray[i64]&) -> void:
    can Memory.Allocate, Abort.Panic:
        for declaration in declarations |names, counts|:
            match declaration:
                Ast::Decl.Enum(name, variants, is_const, storage, line):
                    if variants.count > 0:
                        names.push(name)
                        counts.push(variants.count.i64())
                Ast::Decl.Module(name, body, line):
                    collect_enum_tag_declarations(body, names, counts)
                Ast::Decl.Scoped(body, line):
                    collect_enum_tag_declarations(body, names, counts)
                _:
                    pass
'''
if compact_code(function_section(source_text, "collect_enum_tag_declarations")) != compact_code(expected_collector):
    raise SystemExit("enum-tag collector no longer preserves paired positive-count rows in traversal order")

integration_call = "collect_enum_tag_declarations(declarations, enum_names, enum_counts)"
if check_text.count(integration_call) != 1:
    raise SystemExit("enum-tag checker must build the indexed name/count rows exactly once")
lookup_routes = (
    "overflows: bool = array_slot >= 0 and enum_slot >= 0 and indexed_enum_tag_count(enum_names, enum_counts, enum_types[enum_slot.usize()]) > array_sizes[array_slot.usize()]",
    "enum_params.push(parameter.name) if type_name != \"\" and indexed_enum_tag_count(enum_names, enum_counts, type_name) > 0",
    "enum_types.push(type_name) if type_name != \"\" and indexed_enum_tag_count(enum_names, enum_counts, type_name) > 0",
)
if any(check_text.count(route) != 1 for route in lookup_routes):
    raise SystemExit("enum-tag checker must route the enum type and parallel metadata through the indexed lookup")
if check_text.count("indexed_enum_tag_count(enum_names, enum_counts,") != len(lookup_routes):
    raise SystemExit("enum-tag checker contains an unreviewed lookup call")
entry = compact_code(function_section(check_text, "check_enum_tag_index"))
entry_fragments = (
    "enum_names: mutable darray[sview] = []",
    "enum_counts: mutable darray[i64] = []",
    integration_call,
    "table <- check_enum_tag_index_walk(declarations, declarations, law_names, law_predicates, enum_names, enum_counts, table)",
)
if any(not any(one_line(fragment) in line for line in entry) for fragment in entry_fragments):
    raise SystemExit("enum-tag lookup precondition is no longer established by fresh paired arrays and the collector")
positions = [
    next(index for index, line in enumerate(entry) if line.strip() == one_line(fragment))
    for fragment in (entry_fragments[0], integration_call, entry_fragments[3])
]
if not (positions[0] < positions[1] < positions[2]):
    raise SystemExit("enum-tag arrays must be initialized, collected, and then passed to the walker in order")
lookup_include = 'include "./enum_tag_lookup_index.elisa"'
collector_include = 'include "./enum_tag_declaration_index.elisa"'
if semantic_text.count(lookup_include) != 1 or semantic_text.count(collector_include) != 1:
    raise SystemExit("semantic root must include the production enum-tag lookup and collector exactly once")
if semantic_text.index(lookup_include) > semantic_text.index(collector_include):
    raise SystemExit("semantic lookup must be compiled before its declaration collector")
if "indexed_enum_tag_count(names, counts, query) == original_count(declarations, query)" not in parity_text:
    raise SystemExit("existing differential fixture must continue comparing the index with the old traversal")
positive_shapes = {
    "duplicate_enum_names_keep_the_first_count": '''def duplicate_enum_names_keep_the_first_count() -> bool:
    ensure result == true
    names: darray[sview] = ["Same", "Other", "Same"]
    counts: darray[i64] = [2, 5, 9]
    can Abort.Panic:
        return indexed_enum_tag_count(names, counts, "Same") == 2''',
    "absent_enum_names_return_zero": '''def absent_enum_names_return_zero() -> bool:
    ensure result == true
    names: darray[sview] = ["Same", "Other"]
    counts: darray[i64] = [2, 5]
    can Abort.Panic:
        return indexed_enum_tag_count(names, counts, "Missing") == 0''',
    "a_short_count_array_fails_closed": '''def a_short_count_array_fails_closed() -> bool:
    ensure result == true
    names: darray[sview] = ["Same", "Other"]
    counts: darray[i64] = [2]
    can Abort.Panic:
        return indexed_enum_tag_count(names, counts, "Other") == 0''',
}
negative_shape = '''def a_duplicate_enum_name_returns_the_last_count() -> bool:
    ensure result == true
    names: darray[sview] = ["Same", "Other", "Same"]
    counts: darray[i64] = [2, 5, 9]
    can Abort.Panic:
        return indexed_enum_tag_count(names, counts, "Same") == 9'''
for name, expected in positive_shapes.items():
    if compact_code(function_section(positive_text, name)) != compact_code(expected):
        raise SystemExit(f"positive theorem {name} changed without updating its source-bound gate")
if compact_code(function_section(negative_text, "a_duplicate_enum_name_returns_the_last_count")) != compact_code(negative_shape):
    raise SystemExit("negative duplicate-name claim changed without updating its source-bound gate")

if declarations(positive_text) != POSITIVE_NAMES or declarations(negative_text) != NEGATIVE_NAMES:
    raise SystemExit(
        f"enum-tag declaration proof inventory changed: "
        f"positive={sorted(declarations(positive_text))}, negative={sorted(declarations(negative_text))}"
    )
lookup_import = 'include "../../src/semantic/enum_tag_lookup_index.elisa"'
if lookup_import not in positive_text or lookup_import not in negative_text:
    raise SystemExit("proofs must import the production enum-tag lookup module")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("enum-tag lookup proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, LOOKUP_SOURCE, CHECK, SEMANTIC, PARITY,
    *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
verified_positive = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert POSITIVE_NAMES <= verified_positive
assert "indexed_enum_tag_count" in verified_positive, "production lookup contract was not replayed"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_CLAIM_NAMES
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "production first-match lookup contract, duplicate-name stability, missing-name behavior, and fail-closed handling of short count arrays; source gates pin collector pairing and lookup routing",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": [row["name"] for row in negative["findings"]],
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
