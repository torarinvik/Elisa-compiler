"""Source-bind the final unsigned remainder step of the annotation-pair bucket hash."""
from __future__ import annotations

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
SOURCE = ROOT / "src/backend/codegen_annotation_pair_hash.elisa"
POSITIVE = HERE / "backend_annotation_pair_bucket_range.elisa"
NEGATIVE = HERE / "backend_annotation_pair_bucket_range_rejected.elisa"


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one declaration named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if not __debug__:
    raise SystemExit("run without Python -O")

source_text = SOURCE.read_text()
if "const ANNOTATION_PAIR_BUCKETS: usize = 65536" not in source_text:
    raise SystemExit("annotation-pair bucket count changed from the value modeled here")
bucket = compact(function_section(source_text, "annotation_pair_bucket"))
if hashlib.sha256(bucket.encode()).hexdigest() != \
        "093bf698c1838f8b496ed245be2d1f7616cb6104cd813b6408bee1b0443b5f27":
    raise SystemExit("annotation_pair_bucket changed since the remainder-range proof was reviewed")
if "defannotation_pair_bucket(owner:sview,name:sview)->usizecan[Abort.Panic]:" not in bucket or \
        "return(hash%ANNOTATION_PAIR_BUCKETS.u64()).usize()" not in bucket:
    raise SystemExit("annotation-pair bucket no longer returns the u64 remainder cast to usize")

expected_positive = compact("""
    def annotation_pair_hash_remainder_is_in_bucket_range(hash: u64) -> u64:
        ensure result < 65536
        return hash % 65536
""")
expected_negative = compact("""
    def false_annotation_hash_remainder_can_equal_bucket_count(hash: u64) -> u64:
        ensure result == 65536
        return hash % 65536
""")
if compact(function_section(POSITIVE.read_text(), "annotation_pair_hash_remainder_is_in_bucket_range")) != expected_positive:
    raise SystemExit("positive bucket-range theorem no longer models the production modulo operation")
if compact(function_section(NEGATIVE.read_text(), "false_annotation_hash_remainder_can_equal_bucket_count")) != expected_negative:
    raise SystemExit("false bucket-bound control changed")
if declarations(POSITIVE) != {"annotation_pair_hash_remainder_is_in_bucket_range"} or \
        declarations(NEGATIVE) != {"false_annotation_hash_remainder_can_equal_bucket_count"}:
    raise SystemExit("bucket-range proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_annotation_pair_bucket_range.elisa"'):
    raise SystemExit("bucket-range false claim must include its positive theorem")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("annotation-pair bucket-range proof requires a strict proof build")
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
                            text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert report["summary"]["semantic_diagnostics"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == 1
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 2
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "bucket-range proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == 2
assert negative["summary"]["obligations"] == 4 and negative["summary"]["proven"] == 3
assert [goal["name"] for goal in negative["goals"] if not goal["proven"]] == [
    "false_annotation_hash_remainder_can_equal_bucket_count"
]
assert negative == run(NEGATIVE)[1], "false bucket-range claim was not rejected deterministically"

for path, expected in hashes_before.items():
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise SystemExit(f"proof input changed while it was being checked: {path}")

print("annotation-pair bucket range: both positive obligations replay; remainder-equals-count control is refused")
