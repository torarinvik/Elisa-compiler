"""Kernel-check the production annotation owner/name bucket hash."""
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
HASH_SOURCE = ROOT / "src/backend/codegen_annotation_pair_hash.elisa"
INDEX_SOURCE = ROOT / "src/backend/codegen_annotation_pair_index.elisa"
MODULE_SOURCE = ROOT / "src/backend/codegen_module.elisa"
FACADE = ROOT / "src/backend/codegen.elisa"
POSITIVE = HERE / "backend_annotation_pair_bucket.elisa"
NEGATIVE = HERE / "backend_annotation_pair_bucket_rejected.elisa"
POSITIVE_NAMES = {
    "production_pair_bucket_matches_recursive_spec",
    "production_pair_bucket_is_in_range",
    "equal_owner_name_pairs_share_a_bucket",
    "tuple_separator_splits_equal_concatenations",
    "empty_pair_uses_the_delimited_offset_bucket",
}
NEGATIVE_NAMES = {
    "false_pair_bucket_is_outside_table_range",
    "false_empty_pair_bucket_omits_separator",
    "false_tuple_separator_ignores_owner_name_boundary",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact_code(text: str) -> tuple[tuple[int, str], ...]:
    rows = []
    for line in text.splitlines():
        code = line.split("#", 1)[0].expandtabs(4)
        if code.strip():
            indent = len(code) - len(code.lstrip())
            rows.append((indent, " ".join(code.lstrip().split())))
    if not rows:
        return ()
    base = min(indent for indent, _ in rows)
    return tuple((indent - base, code) for indent, code in rows)


def function_section(text: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", text))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one declaration named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^\s*def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_function(path: Path, name: str, expected: str) -> None:
    if compact_code(function_section(path.read_text(), name)) != compact_code(expected):
        raise SystemExit(f"{path.name}:{name} changed without updating its proof gate")


hash_text = HASH_SOURCE.read_text()
index_text = INDEX_SOURCE.read_text()
facade_text = FACADE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_owner_spec = """
ghost def annotation_pair_owner_hash_suffix(owner: sview, index: usize, hash: u64) -> u64:
    requires index <= sview_len(owner)
    decreases sview_len(owner) - index
    return hash if index == sview_len(owner)
    return annotation_pair_owner_hash_suffix(owner, index + 1.usize(), (hash ^ sview_at(owner, index).u64()) * ANNOTATION_PAIR_HASH_PRIME)
"""
expected_name_spec = """
ghost def annotation_pair_name_hash_suffix(name: sview, index: usize, hash: u64) -> u64:
    requires index <= sview_len(name)
    decreases sview_len(name) - index
    return hash if index == sview_len(name)
    return annotation_pair_name_hash_suffix(name, index + 1.usize(), (hash ^ sview_at(name, index).u64()) * ANNOTATION_PAIR_HASH_PRIME)
"""
expected_pair_spec = """
ghost def annotation_pair_hash_spec(owner: sview, name: sview) -> u64:
    owner_hash: u64 = annotation_pair_owner_hash_suffix(owner, 0.usize(), ANNOTATION_PAIR_HASH_OFFSET)
    delimited_hash: u64 = (owner_hash ^ 255.u64()) * ANNOTATION_PAIR_HASH_PRIME
    return annotation_pair_name_hash_suffix(name, 0.usize(), delimited_hash)
"""
expected_bucket = """
def annotation_pair_bucket(owner: sview, name: sview) -> usize can[Abort.Panic]:
    ensure result == (annotation_pair_hash_spec(owner, name) % ANNOTATION_PAIR_BUCKETS.u64()).usize()
    ensure result < ANNOTATION_PAIR_BUCKETS
    hash: mutable u64 = ANNOTATION_PAIR_HASH_OFFSET
    for offset in 0..<sview_len(owner) |hash, owner|:
        invariant offset <= sview_len(owner)
        invariant annotation_pair_owner_hash_suffix(owner, offset, hash) == annotation_pair_owner_hash_suffix(owner, 0.usize(), ANNOTATION_PAIR_HASH_OFFSET)
        hash <- (hash ^ sview_at(owner, offset).u64()) * ANNOTATION_PAIR_HASH_PRIME
    owner_hash: u64 = hash
    hash <- (hash ^ 255.u64()) * ANNOTATION_PAIR_HASH_PRIME
    for offset in 0..<sview_len(name) |hash, name|:
        invariant offset <= sview_len(name)
        invariant annotation_pair_name_hash_suffix(name, offset, hash) == annotation_pair_name_hash_suffix(name, 0.usize(), (owner_hash ^ 255.u64()) * ANNOTATION_PAIR_HASH_PRIME)
        hash <- (hash ^ sview_at(name, offset).u64()) * ANNOTATION_PAIR_HASH_PRIME
    return (hash % ANNOTATION_PAIR_BUCKETS.u64()).usize()
"""
for name, expected in (
    ("annotation_pair_owner_hash_suffix", expected_owner_spec),
    ("annotation_pair_name_hash_suffix", expected_name_spec),
    ("annotation_pair_hash_spec", expected_pair_spec),
    ("annotation_pair_bucket", expected_bucket),
):
    require_function(HASH_SOURCE, name, expected)

expected_builder = """
def annotation_pairs_ready(annotations: darray[Ast::EnumAnnotation]&) -> bool can[Abort.Panic]:
    false return if annotations.count == 0
    base: mutable uintptr = 0
    can Unsafe.PointerCast:
        base <- (&annotations[0]).cast[uintptr]
    first_line: u32 = annotations[0].line
    last_line: u32 = annotations[annotations.count - 1].line
    if base == (annotation_pair_base can Global.Read) and annotations.count == (annotation_pair_rows can Global.Read) and first_line == (annotation_pair_first_line can Global.Read) and last_line == (annotation_pair_last_line can Global.Read) and (annotation_pair_state can Global.Read) != 0:
        return (annotation_pair_state can Global.Read) == 1
    can Global.Write:
        annotation_pair_base <- base
    can Global.Write:
        annotation_pair_rows <- annotations.count
    can Global.Write:
        annotation_pair_first_line <- first_line
    can Global.Write:
        annotation_pair_last_line <- last_line
    can Global.Write:
        annotation_pair_state <- 0
    if annotations.count > ANNOTATION_PAIR_CAPACITY:
        can Global.Write:
            annotation_pair_state <- 2
        return false
    previous_touched_count: usize = (annotation_pair_touched_count can Global.Read)
    for touched_row in 0..<previous_touched_count |previous_touched_count|:
        bucket: usize = (annotation_pair_touched_buckets can Global.Read)[touched_row].usize()
        can Global.Write:
            annotation_pair_heads[bucket] <- 0
    can Global.Write:
        annotation_pair_touched_count <- 0
    touched_count: mutable usize = 0
    for row in 0..<annotations.count |annotations, touched_count|:
        bucket: usize = annotation_pair_bucket(annotations[row].owner, annotations[row].name)
        can Global.Write:
            annotation_pair_next[row] <- 0
        first: u32 = (annotation_pair_heads can Global.Read)[bucket]
        if first != 0:
            last: u32 = (annotation_pair_tails can Global.Read)[bucket]
            can Global.Write:
                annotation_pair_next[last.usize() - 1] <- (row + 1).u32()
            can Global.Write:
                annotation_pair_tails[bucket] <- (row + 1).u32()
        else:
            can Global.Write:
                annotation_pair_touched_buckets[touched_count] <- bucket.u32()
            touched_count <- touched_count + 1.usize()
            can Global.Write:
                annotation_pair_touched_count <- touched_count
            can Global.Write:
                annotation_pair_heads[bucket] <- (row + 1).u32()
            can Global.Write:
                annotation_pair_tails[bucket] <- (row + 1).u32()
    can Global.Write:
        annotation_pair_state <- 1
    return true
"""
expected_invalidator = """
def annotation_pair_cache_invalidate() -> void can[Global.Write]:
    annotation_pair_state <- 0
"""
expected_find = """
def annotation_pair_find(annotations: darray[Ast::EnumAnnotation]&, owner: sview, name: sview, from_row: i64) -> i64 can[Abort.Panic]:
    if (annotation_pairs_ready(annotations) can Global{Read,Write}):
        cursor: mutable u32 = (annotation_pair_heads can Global.Read)[annotation_pair_bucket(owner, name)] if from_row < 0 else (annotation_pair_next can Global.Read)[from_row.usize()]
        while cursor != 0 |cursor, annotations, owner, name|:
            row: usize = cursor.usize() - 1
            row.i64() return if annotations[row].owner == owner and annotations[row].name == name
            cursor <- (annotation_pair_next can Global.Read)[row]
        return -1
    start: usize = 0 if from_row < 0 else from_row.usize() + 1
    for row in start..<annotations.count |annotations, owner, name|:
        row.i64() return if annotations[row].owner == owner and annotations[row].name == name
    return -1
"""
require_function(INDEX_SOURCE, "annotation_pair_cache_invalidate", expected_invalidator)
require_function(INDEX_SOURCE, "annotation_pairs_ready", expected_builder)
require_function(INDEX_SOURCE, "annotation_pair_find", expected_find)
builder_shape = compact_code(function_section(index_text, "annotation_pairs_ready"))
overflow_check = next(i for i, (_, line) in enumerate(builder_shape)
                      if line == "if annotations.count > ANNOTATION_PAIR_CAPACITY:")
clear_old_buckets = next(i for i, (_, line) in enumerate(builder_shape)
                         if line.startswith("previous_touched_count: usize"))
if overflow_check > clear_old_buckets:
    raise SystemExit("oversized fallback must preserve the previous touched-bucket list")

module_text = MODULE_SOURCE.read_text()
module_lines = function_section(module_text, "emit_module_core").splitlines()
expected_module_entry = compact_code("""
    can Global.Write:
        annotation_pair_cache_invalidate()
    structs: mutable StructTable = new_struct_table(ctx, target_data, checked_contracts)
""")
if compact_code("\n".join(module_lines[1:]))[:len(expected_module_entry)] != expected_module_entry or \
        module_text.count("annotation_pair_cache_invalidate()") != 1:
    raise SystemExit("module emission must invalidate the annotation-pair cache before using a new annotation stream")

if "const ANNOTATION_PAIR_BUCKETS: usize = 65536" not in hash_text or \
        "const ANNOTATION_PAIR_HASH_OFFSET: u64 = 14695981039346656037" not in hash_text or \
        "const ANNOTATION_PAIR_HASH_PRIME: u64 = 1099511628211" not in hash_text:
    raise SystemExit("production pair bucket constants changed")
if "global mutable annotation_pair_touched_count: usize" not in index_text or \
        "global mutable annotation_pair_touched_buckets: array[u32, 65536]" not in index_text:
    raise SystemExit("production touched-bucket clearing index changed")
if "def annotation_pair_bucket(" in index_text or "const ANNOTATION_PAIR_BUCKETS" in index_text:
    raise SystemExit("pair hash must have one independently imported, proved production implementation")
if index_text.count("annotation_pair_bucket(") != 2:
    raise SystemExit("pair-index construction and lookup must both use the proved production bucket helper")
for table in ("annotation_pair_heads", "annotation_pair_tails"):
    if f"global mutable {table}: array[u32, 65536]" not in index_text:
        raise SystemExit(f"{table} capacity changed from the proved pair bucket count")
if "global mutable annotation_pair_next: array[u32, 1048576]" not in index_text:
    raise SystemExit("per-row collision chain capacity changed from the bounded row count")
hash_include = 'include "./codegen_annotation_pair_hash.elisa"'
index_include = 'include "./codegen_annotation_pair_index.elisa"'
if facade_text.count(hash_include) != 1 or facade_text.count(index_include) != 1 or \
        facade_text.index(hash_include) > facade_text.index(index_include):
    raise SystemExit("backend facade must include the pair hash before its table consumers")
if 'include "../../src/backend/codegen_annotation_pair_hash.elisa"' not in positive_text:
    raise SystemExit("the theorem must import the production bucket implementation directly")
if not negative_text.startswith('include "./backend_annotation_pair_bucket.elisa"'):
    raise SystemExit("negative controls must include the admitted pair-bucket theorems")
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("annotation pair bucket proof inventory changed")

proof_shapes = {
    "production_pair_bucket_matches_recursive_spec": """
        def production_pair_bucket_matches_recursive_spec(owner: sview, name: sview) -> bool can[Abort.Panic]:
            ensure result == true
            can Abort.Panic:
                return annotation_pair_bucket(owner, name) == (annotation_pair_hash_spec(owner, name) % ANNOTATION_PAIR_BUCKETS.u64()).usize()
    """,
    "production_pair_bucket_is_in_range": """
        def production_pair_bucket_is_in_range(owner: sview, name: sview) -> bool can[Abort.Panic]:
            ensure result == true
            can Abort.Panic:
                return annotation_pair_bucket(owner, name) < ANNOTATION_PAIR_BUCKETS
    """,
    "equal_owner_name_pairs_share_a_bucket": """
        def equal_owner_name_pairs_share_a_bucket(left_owner: sview, left_name: sview, right_owner: sview, right_name: sview) -> bool can[Abort.Panic]:
            requires left_owner == right_owner and left_name == right_name
            ensure result == true
            can Abort.Panic:
                return annotation_pair_bucket(left_owner, left_name) == annotation_pair_bucket(right_owner, right_name)
    """,
    "tuple_separator_splits_equal_concatenations": """
        def tuple_separator_splits_equal_concatenations() -> bool can[Abort.Panic]:
            ensure result == true
            can Abort.Panic:
                return annotation_pair_bucket("ab", "c") != annotation_pair_bucket("a", "bc")
    """,
    "empty_pair_uses_the_delimited_offset_bucket": """
        def empty_pair_uses_the_delimited_offset_bucket() -> bool can[Abort.Panic]:
            ensure result == true
            can Abort.Panic:
                return annotation_pair_bucket("", "") == (((ANNOTATION_PAIR_HASH_OFFSET ^ 255.u64()) * ANNOTATION_PAIR_HASH_PRIME) % ANNOTATION_PAIR_BUCKETS.u64()).usize()
    """,
}
for name, expected in proof_shapes.items():
    require_function(POSITIVE, name, expected)

negative_shapes = {
    "false_pair_bucket_is_outside_table_range": """
        def false_pair_bucket_is_outside_table_range(owner: sview, name: sview) -> bool can[Abort.Panic]:
            ensure result == true
            can Abort.Panic:
                return annotation_pair_bucket(owner, name) >= ANNOTATION_PAIR_BUCKETS
    """,
    "false_empty_pair_bucket_omits_separator": """
        def false_empty_pair_bucket_omits_separator() -> bool can[Abort.Panic]:
            ensure result == true
            can Abort.Panic:
                return annotation_pair_bucket("", "") == 0
    """,
    "false_tuple_separator_ignores_owner_name_boundary": """
        def false_tuple_separator_ignores_owner_name_boundary() -> bool can[Abort.Panic]:
            ensure result == true
            can Abort.Panic:
                return annotation_pair_bucket("ab", "c") == annotation_pair_bucket("a", "bc")
    """,
}
for name, expected in negative_shapes.items():
    require_function(NEGATIVE, name, expected)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("annotation pair bucket proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    HASH_SOURCE, INDEX_SOURCE, MODULE_SOURCE, FACADE, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
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
assert not positive["findings"]
verified_positive = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert POSITIVE_NAMES <= verified_positive
assert "annotation_pair_bucket" in verified_positive, "production bucket contract was not kernel-replayed"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "kernel_scope": "production owner/name FNV-1a fold with a 0xFF tuple separator and an in-range modulo bucket",
    "source_shape_checks": "oversized fallback preserves prior touched buckets; rebuild clears/records each touched bucket in row order; lookup follows direct-head/next chains with exact pair comparison and linear fallback; module entry invalidates the cache",
    "not_yet_proven": "kernel proof of the chain invariant and end-to-end lookup equivalence; cache freshness when one annotation stream mutates in place without changing its pointer, count, or endpoint lines",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
