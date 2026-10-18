"""Bind the backend owner-bucket hash to a recursive byte-fold proof."""
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
SOURCE = ROOT / "src/backend/codegen_annotation_row_index.elisa"
HASH_SOURCE = ROOT / "src/backend/codegen_annotation_row_hash.elisa"
FACADE = ROOT / "src/backend/codegen.elisa"
POSITIVE = HERE / "backend_annotation_index_hash.elisa"
NEGATIVE = HERE / "backend_annotation_index_hash_rejected.elisa"
POSITIVE_NAMES = {
    "annotation_hash_matches_recursive_spec",
    "empty_text_returns_offset_basis",
    "ascii_a_matches_fnv1a64",
    "equal_owner_strings_share_a_bucket",
}
NEGATIVE_NAMES = {"false_claim_ascii_a_hash_is_zero"}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact_code(text: str) -> tuple[str, ...]:
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
        if line_indent == len(indent) and re.match(r"(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", stripped):
            end = match.end() + line_match.start()
            break
        if line_indent <= len(indent) and stripped in {"public:", "private:"}:
            end = match.end() + line_match.start()
            break
    return text[match.start():end]


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


source_text = SOURCE.read_text()
hash_text = HASH_SOURCE.read_text()
facade_text = FACADE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

if compact_code(function_section(hash_text, "annotation_index_hash_prefix")) != compact_code('''
ghost def annotation_index_hash_prefix(text: sview, index: usize, hash: u64) -> u64:
    requires index <= text.len
    decreases index
    ensure index == 0 implies result == hash
    ensure index > 0 implies result == (annotation_index_hash_prefix(text, index - 1.usize(), hash) ^ text[index - 1.usize()].u64()) * ANNOTATION_INDEX_HASH_PRIME
    return hash if index == 0
    return (annotation_index_hash_prefix(text, index - 1.usize(), hash) ^ text[index - 1.usize()].u64()) * ANNOTATION_INDEX_HASH_PRIME
'''):
    raise SystemExit("hash prefix reference no longer defines the recursive FNV-1a byte fold")

if compact_code(function_section(hash_text, "annotation_index_hash")) != compact_code('''
def annotation_index_hash(text: sview) -> u64:
    ensure result == annotation_index_hash_prefix(text, text.len, ANNOTATION_INDEX_HASH_OFFSET)
    hash: mutable u64 = ANNOTATION_INDEX_HASH_OFFSET
    for offset in 0..<text.len |hash, text|:
        invariant offset <= text.len
        invariant hash == annotation_index_hash_prefix(text, offset, ANNOTATION_INDEX_HASH_OFFSET)
        hash <- (hash ^ text[offset].u64()) * ANNOTATION_INDEX_HASH_PRIME
    assert hash == annotation_index_hash_prefix(text, text.len, ANNOTATION_INDEX_HASH_OFFSET)
    return hash
'''):
    raise SystemExit("production owner hash contract or loop invariant changed without updating its proof")

if "const ANNOTATION_INDEX_HASH_OFFSET: u64 = 14695981039346656037" not in hash_text:
    raise SystemExit("production hash offset basis changed")
if "const ANNOTATION_INDEX_HASH_PRIME: u64 = 1099511628211" not in hash_text:
    raise SystemExit("production hash prime changed")
hash_include = 'include "./codegen_annotation_row_hash.elisa"'
index_include = 'include "./codegen_annotation_row_index.elisa"'
if facade_text.count(hash_include) != 1 or facade_text.count(index_include) != 1:
    raise SystemExit("backend facade must include both annotation index modules exactly once")
if facade_text.index(hash_include) > facade_text.index(index_include):
    raise SystemExit("annotation hash must be compiled before its table-index consumers")

first = compact_code(function_section(source_text, "annotation_owner_first"))
pair = compact_code(function_section(source_text, "annotation_pair_present"))
expected_first = compact_code('''
def annotation_owner_first(structs: StructTable&, owner: sview) -> i64 can[Abort.Panic]:
    can Abort.Panic:
        return head if structs.annotations.annotation_owner_heads.get(annotation_index_hash(owner)) is head else ANNOTATION_INDEX_NONE
''')
expected_pair = compact_code('''
def annotation_pair_present(structs: StructTable&, annotations: darray[Ast::EnumAnnotation]&, owner: sview, name: sview) -> bool can[Abort.Panic]:
    can Abort.Panic:
        row: mutable i64 = annotation_owner_first(structs, owner)
        while row >= 0 |row, structs, annotations, owner, name|:
            return true if annotations[row.usize()].owner == owner and annotations[row.usize()].name == name
            row <- structs.annotations.annotation_owner_next[row.usize()]
        return false
''')
if first != expected_first:
    raise SystemExit("owner lookup no longer uses the verified hash as its bucket key")
if pair != expected_pair:
    raise SystemExit("candidate rows must traverse the owner chain and compare exact owner/name fields")

if 'include "../../src/backend/codegen_annotation_row_hash.elisa"' not in positive_text:
    raise SystemExit("proof must import the production owner-hash implementation")
if not negative_text.startswith('include "./backend_annotation_index_hash.elisa"'):
    raise SystemExit("negative control must include the admitted production-linked proof")
if declarations(positive_text) != POSITIVE_NAMES or declarations(negative_text) != NEGATIVE_NAMES:
    raise SystemExit("annotation-index proof inventory changed")

proof_shapes = {
    "annotation_hash_matches_recursive_spec": '''ghost def annotation_hash_matches_recursive_spec(text: sview) -> bool:
    ensure result == true
    return annotation_index_hash(text) == annotation_index_hash_prefix(text, text.len, ANNOTATION_INDEX_HASH_OFFSET)''',
    "empty_text_returns_offset_basis": '''def empty_text_returns_offset_basis() -> bool:
    ensure result == true
    return annotation_index_hash("") == ANNOTATION_INDEX_HASH_OFFSET''',
    "ascii_a_matches_fnv1a64": '''def ascii_a_matches_fnv1a64() -> bool:
    ensure result == true
    return annotation_index_hash("a") == 12638187200555641996.u64()''',
    "equal_owner_strings_share_a_bucket": '''def equal_owner_strings_share_a_bucket(left: sview, right: sview) -> bool:
    requires left == right
    ensure result == true
    return annotation_index_hash(left) == annotation_index_hash(right)''',
}
for name, expected in proof_shapes.items():
    if compact_code(function_section(positive_text, name)) != compact_code(expected):
        raise SystemExit(f"positive theorem {name} changed without updating its source-bound gate")

if compact_code(function_section(negative_text, "false_claim_ascii_a_hash_is_zero")) != compact_code('''
def false_claim_ascii_a_hash_is_zero() -> bool:
    ensure result == true
    return annotation_index_hash("a") == 0
'''):
    raise SystemExit("negative control no longer claims the intentionally false hash value")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("annotation-index hash proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, HASH_SOURCE, FACADE,
    POSITIVE, NEGATIVE, *source_closure,
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
assert "annotation_index_hash" in verified_positive, "production owner hash contract was not replayed"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "kernel_scope": "production owner hash equals its recursive FNV-1a byte-fold specification; equal owner strings therefore share a bucket",
    "source_shape_checks": "the production lookup selects the hash bucket, traverses its owner chain, and compares exact owner/name fields before accepting a row",
    "not_yet_proven": "owner-chain construction invariant, cache freshness/lifetime, and equivalence of indexed lookup to a full annotation scan",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": [row["name"] for row in negative["findings"]],
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
