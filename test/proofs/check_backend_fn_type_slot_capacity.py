"""Admit the u32 capacity guard for first-class function type slots."""
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
POSITIVE = HERE / "backend_fn_type_slot_capacity.elisa"
NEGATIVE = HERE / "backend_fn_type_slot_capacity_rejected.elisa"
POSITIVE_NAMES = {
    "appended_function_type_slot_is_representable",
    "final_representable_slot_is_admitted",
    "first_unrepresentable_slot_is_rejected",
}
NEGATIVE_NAMES = {"false_claim_first_unrepresentable_slot_fits"}
GUARD = "return unmodeled_type() if structs.function_types.fn_pool_returns.count > MAX_FN_TYPE_SLOT"

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


source_text = SOURCE.read_text()
if compact("const MAX_FN_TYPE_SLOT: usize = 4294967295") not in compact(source_text):
    raise SystemExit("function type slot bound no longer matches the u32 index ceiling")
for name in ("intern_fn_type", "intern_error_fn_type"):
    body = compact(function_section(source_text, name))
    guard_position = body.find(compact(GUARD))
    append_position = body.find("fn_pool_returns.push(return_type)")
    cast_position = body.find("fn_pool_returns.count-1).u32()")
    if min(guard_position, append_position, cast_position) < 0 or not guard_position < append_position < cast_position:
        raise SystemExit(f"{name} must reject an unrepresentable slot before append and u32 conversion")
if compact(source_text).count("fn_pool_returns.push(return_type)") != 2:
    raise SystemExit("a function return-pool append was added outside the guarded interning paths")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("function type slot proof inventory changed")
if 'include "./backend_fn_type_slot_capacity.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer includes the admitted slot-capacity proof")
if compact("MAX_FN_TYPE_SLOT: i64 = 4294967295") not in compact(POSITIVE.read_text()):
    raise SystemExit("numeric proof no longer uses the source u32 slot ceiling")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("function type slot proof requires a strict proof build")
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
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "both function-type interning paths reject a slot above u32 before appending",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
