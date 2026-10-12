"""Admit source-bound proofs for backend slice offsets and lengths."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
GUARDS = ROOT / "src/backend/codegen_guards.elisa"
CALL = ROOT / "src/backend/codegen_call.elisa"
SLICES = ROOT / "src/backend/codegen_expr_slice.elisa"
POSITIVE = HERE / "backend_slice_bounds.elisa"
NEGATIVE = HERE / "backend_slice_bounds_rejected.elisa"
LLVM_CONFIG = shutil.which(os.environ.get("LLVM_CONFIG", "llvm-config"))

POSITIVE_NAMES = {
    "slice_start_clamp",
    "slice_end_clamp",
    "slice_count_from_clamped_start",
    "high_select_subtraction_matches_empty_or_difference",
    "inverted_slice_is_empty",
    "slice_start_at_extent_has_no_remaining_count",
    "string_slice_normalise_start",
    "string_slice_normalise_end",
}
NEGATIVE_NAMES = {
    "false_claim_clamped_start_can_exceed_extent",
    "false_claim_inverted_slice_has_positive_count",
    "false_claim_negative_string_start_is_nonzero",
    "false_claim_negative_string_end_becomes_zero",
}

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


def find_llvm_header() -> Path:
    if LLVM_CONFIG is None:
        raise SystemExit("llvm-config is required to bind slice predicate IDs to LLVM's C enum")
    include_dir = subprocess.run([LLVM_CONFIG, "--includedir"], check=True,
                                 capture_output=True, text=True, timeout=15).stdout.strip()
    header = Path(include_dir) / "llvm-c/Core.h"
    if not header.is_file():
        raise SystemExit(f"LLVM C API header is missing: {header}")
    return header.resolve(strict=True)


LLVM_HEADER = find_llvm_header()


def llvm_integer_predicates() -> dict[str, int]:
    text = LLVM_HEADER.read_text()
    end = re.search(r"\}\s*LLVMIntPredicate\s*;", text)
    start = text.rfind("typedef enum", 0, end.start()) if end else -1
    if end is None or start < 0:
        raise SystemExit("could not locate LLVMIntPredicate in llvm-c/Core.h")
    members = re.findall(r"\b(LLVMInt[A-Za-z0-9_]+)\s*(?:=\s*(\d+))?\s*,?", text[start:end.start()])
    values: dict[str, int] = {}
    current = -1
    for name, explicit in members:
        current = int(explicit) if explicit else current + 1
        values[name] = current
    return values


def require_ordered(source: str, steps: tuple[str, ...], label: str) -> None:
    positions = [source.find(step) for step in steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} changed its proved operation order: {positions}")


if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("slice-bounds proof inventory changed")
if 'include "./backend_slice_bounds.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the admitted slice bounds model")

predicates = llvm_integer_predicates()
for name, expected in {
    "LLVMIntUGT": 34,
    "LLVMIntUGE": 35,
    "LLVMIntULT": 36,
    "LLVMIntSGT": 38,
    "LLVMIntSGE": 39,
}.items():
    if predicates.get(name) != expected:
        raise SystemExit(f"LLVM predicate {name} changed from the proved value {expected}")

guards = GUARDS.read_text()
start = compact(function_section(guards, "emit_slice_clamp_start"))
require_ordered(start, (
    "wide_length:LLVMValueRef=slice_bound_width(length,start,builder)",
    'start_over:LLVMValueRef=LLVMBuildICmp(builder,34,start,wide_length,"slice.start.over")',
    'returnLLVMBuildSelect(builder,start_over,wide_length,start,"slice.start.clamped")',
), "slice start clamp")

count = compact(function_section(guards, "emit_slice_clamp_count"))
require_ordered(count, (
    "wide_length:LLVMValueRef=slice_bound_width(length,end,builder)",
    'end_over:LLVMValueRef=LLVMBuildICmp(builder,34,end,wide_length,"slice.end.over")',
    'clamped_end:LLVMValueRef=LLVMBuildSelect(builder,end_over,wide_length,end,"slice.end.clamped")',
    'end_after_start:LLVMValueRef=LLVMBuildICmp(builder,35,clamped_end,clamped_start,"slice.end.after.start")',
    'high:LLVMValueRef=LLVMBuildSelect(builder,end_after_start,clamped_end,clamped_start,"slice.hi")',
    'returnLLVMBuildSub(builder,high,clamped_start,"slice.count")',
), "slice count clamp")

normalise_start = compact(function_section(guards, "emit_string_slice_normalise_start"))
require_ordered(normalise_start, (
    'start_positive:LLVMValueRef=LLVMBuildICmp(builder,38,start,zero,"strslice.start.positive")',
    'returnLLVMBuildSelect(builder,start_positive,start,zero,"strslice.start")',
), "signed string start normalisation")

normalise_end = compact(function_section(guards, "emit_string_slice_normalise_end"))
require_ordered(normalise_end, (
    "wide_length:LLVMValueRef=slice_bound_width(length,end,builder)",
    'end_given:LLVMValueRef=LLVMBuildICmp(builder,39,end,zero,"strslice.end.given")',
    'returnLLVMBuildSelect(builder,end_given,end,wide_length,"strslice.end")',
), "signed string end normalisation")

call = compact(function_section(CALL.read_text(), "emit_sview_from_parts"))
require_ordered(call, (
    'sview_source_len:LLVMValueRef=LLVMBuildZExt(builder,sview_strlen_value,sview_i64,"sview.srclen.i64")iftarget_bits==32elsesview_strlen_value',
    'sview_start_positive:LLVMValueRef=LLVMBuildICmp(builder,38,start,sview_zero,"sview.start.pos")',
    'sview_start_over:LLVMValueRef=LLVMBuildICmp(builder,34,start,sview_source_len,"sview.start.over")',
    'sview_start_clamped:LLVMValueRef=LLVMBuildSelect(builder,sview_start_over,sview_source_len,start,"sview.start.clamped")',
    'sview_lo:LLVMValueRef=LLVMBuildSelect(builder,sview_start_positive,sview_start_clamped,sview_zero,"sview.lo")',
    'sview_end_bounded:LLVMValueRef=LLVMBuildICmp(builder,39,end,sview_zero,"sview.end.bounded")',
    'sview_end_over:LLVMValueRef=LLVMBuildICmp(builder,34,end,sview_source_len,"sview.end.over")',
    'sview_end_clamped:LLVMValueRef=LLVMBuildSelect(builder,sview_end_over,sview_source_len,end,"sview.end.clamped")',
    'sview_hi_raw:LLVMValueRef=LLVMBuildSelect(builder,sview_end_bounded,sview_end_clamped,sview_source_len,"sview.hi.raw")',
    'sview_hi_under:LLVMValueRef=LLVMBuildICmp(builder,36,sview_hi_raw,sview_lo,"sview.hi.under")',
    'sview_hi:LLVMValueRef=LLVMBuildSelect(builder,sview_hi_under,sview_lo,sview_hi_raw,"sview.hi")',
    'sview_gep_indices:mutabledarray[LLVMValueRef]=[sview_lo]',
    'sview_data:LLVMValueRef=LLVMBuildGEP2(builder,LLVMInt8TypeInContext(ctx),sview_src,sview_gep_pointer,1,"sview.data")',
    'LLVMBuildInsertValue(builder,sview_agg,LLVMBuildSub(builder,sview_hi,sview_lo,"sview.len"),1,"sview.ins1")',
), "cstr-to-sview construction")
if call.count('LLVMBuildSub(builder,sview_hi,sview_lo,"sview.len")') != 1:
    raise SystemExit("cstr-to-sview length is no longer the nonnegative high-minus-low span")

slices = compact(function_section(SLICES.read_text(), "emit_expression_slice"))
consumer_patterns = (
    ("darray view", 'view_clamped_start:LLVMValueRef=emit_slice_clamp_start(view_slice_start,source_count,ctx,builder)', 'view_indices:mutabledarray[LLVMValueRef]=[view_clamped_start]', 'view_data:LLVMValueRef=LLVMBuildGEP2(builder,element_llvm,source_items,view_indices_pointer,1,"view.slice.data")', 'view_len:LLVMValueRef=emit_slice_clamp_count(view_clamped_start,view_slice_end,source_count,ctx,builder)', 'view_result<-LLVMBuildInsertValue(builder,view_result,view_len,1,"view.slice.ins1")'),
    ("fixed-array reference view", 'ref_clamped_start:LLVMValueRef=emit_slice_clamp_start(ref_slice_start,ref_slice_extent,ctx,builder)', 'ref_slice_indices:mutabledarray[LLVMValueRef]=[LLVMConstInt(LLVMInt64TypeInContext(ctx),0,0),ref_clamped_start]', 'ref_slice_data:LLVMValueRef=LLVMBuildGEP2(builder,ref_slice_llvm,ref_slice_base,ref_slice_indices_pointer,2,"arrayslice.ref.data")', 'ref_slice_len:LLVMValueRef=emit_slice_clamp_count(ref_clamped_start,ref_slice_end,ref_slice_extent,ctx,builder)', 'ref_slice_result<-LLVMBuildInsertValue(builder,ref_slice_result,ref_slice_len,1,"arrayslice.ref.ins1")'),
    ("fixed-array view", 'array_clamped_start:LLVMValueRef=emit_slice_clamp_start(array_slice_start,array_slice_extent,ctx,builder)', 'array_slice_indices:mutabledarray[LLVMValueRef]=[LLVMConstInt(LLVMInt64TypeInContext(ctx),0,0),array_clamped_start]', 'array_slice_data:LLVMValueRef=LLVMBuildGEP2(builder,array_slice_llvm,array_slice_slot,array_slice_indices_pointer,2,"arrayslice.data")', 'array_slice_len:LLVMValueRef=emit_slice_clamp_count(array_clamped_start,array_slice_end,array_slice_extent,ctx,builder)', 'array_slice_result<-LLVMBuildInsertValue(builder,array_slice_result,array_slice_len,1,"arrayslice.ins1")'),
    ("sview slice", 'sview_clamped_start:LLVMValueRef=emit_slice_clamp_start(emit_string_slice_normalise_start(sview_slice_start,ctx,builder),sview_source_len,ctx,builder)', 'sview_slice_len:LLVMValueRef=emit_slice_clamp_count(sview_clamped_start,emit_string_slice_normalise_end(sview_slice_end,sview_source_len,ctx,builder),sview_source_len,ctx,builder)', 'sview_slice_indices:mutabledarray[LLVMValueRef]=[sview_clamped_start]', 'sview_slice_data_at:LLVMValueRef=LLVMBuildGEP2(builder,LLVMInt8TypeInContext(ctx),sview_slice_data,sview_slice_indices_pointer,1,"byteslice.data")', 'sview_slice_result<-LLVMBuildInsertValue(builder,sview_slice_result,sview_slice_len,1,"byteslice.ins1")'),
    ("view slice", 'view_clamped_slice_start:LLVMValueRef=emit_slice_clamp_start(view_slice_start,view_source_len,ctx,builder)', 'view_slice_len:LLVMValueRef=emit_slice_clamp_count(view_clamped_slice_start,view_slice_end,view_source_len,ctx,builder)', 'view_slice_indices:mutabledarray[LLVMValueRef]=[view_clamped_slice_start]', 'view_slice_data_at:LLVMValueRef=LLVMBuildGEP2(builder,llvm_type_of(view_slice_element,structs,ctx),view_slice_data,view_slice_indices_pointer,1,"view.slice.data.at")', 'view_slice_result<-LLVMBuildInsertValue(builder,view_slice_result,view_slice_len,1,"view.slice.ins1")'),
)
for label, *steps in consumer_patterns:
    require_ordered(slices, tuple(steps), f"{label} consumer")

cstr_dispatch = (
    'emit_sview_from_parts(slice_base,slice_start,slice_end,sview_llvm,m,ctx,builder,structs.target.target_pointer_bits)returnifslice_receiver_type.kind==TypeKind.CStr',
    'slice_len:LLVMValueRef=LLVMBuildSub(builder,slice_end,slice_start,"byteslice.len")',
)
require_ordered(slices, cstr_dispatch, "cstr and raw-pointer slice dispatch")

proof_text = POSITIVE.read_text()
expected_positive = {
    "slice_start_clamp": "def slice_start_clamp(start: u64, length: u64) -> u64:\n    ensure result == (length if start > length else start)\n    ensure result <= length\n    return length if start > length else start",
    "slice_end_clamp": "def slice_end_clamp(end: u64, length: u64) -> u64:\n    ensure result == (length if end > length else end)\n    ensure result <= length\n    return length if end > length else end",
    "slice_count_from_clamped_start": "def slice_count_from_clamped_start(start: u64, end: u64, length: u64) -> u64:\n    requires start <= length\n    ensure result == ((length if end > length else end) - start if (length if end > length else end) >= start else 0)\n    ensure result <= length - start\n    return (length if end > length else end) - start if (length if end > length else end) >= start else 0",
    "high_select_subtraction_matches_empty_or_difference": "def high_select_subtraction_matches_empty_or_difference(start: u64, end_clamped: u64) -> bool:\n    ensure result == true\n    return (end_clamped if end_clamped >= start else start) - start == (end_clamped - start if end_clamped >= start else 0)",
    "inverted_slice_is_empty": "def inverted_slice_is_empty(start: u64, end: u64, length: u64) -> bool:\n    requires start <= length and end < start\n    ensure result == true\n    return slice_count_from_clamped_start(start, end, length) == 0",
    "slice_start_at_extent_has_no_remaining_count": "def slice_start_at_extent_has_no_remaining_count(end: u64, length: u64) -> bool:\n    ensure result == true\n    return slice_count_from_clamped_start(length, end, length) == 0",
    "string_slice_normalise_start": "def string_slice_normalise_start(start: i64) -> u64:\n    ensure result == (start.u64() if start > 0 else 0)\n    return start.u64() if start > 0 else 0",
    "string_slice_normalise_end": "def string_slice_normalise_end(end: i64, length: u64) -> u64:\n    ensure result == (end.u64() if end >= 0 else length)\n    return end.u64() if end >= 0 else length",
}
for name, expected in expected_positive.items():
    if compact(function_section(proof_text, name)) != compact(expected):
        raise SystemExit(f"slice-bounds theorem {name} changed its statement or model")

expected_negative = {
    "false_claim_clamped_start_can_exceed_extent": "def false_claim_clamped_start_can_exceed_extent() -> bool:\n    ensure result == true\n    start: u64 = 9\n    length: u64 = 4\n    clamped_start: u64 = 4\n    return clamped_start > length",
    "false_claim_inverted_slice_has_positive_count": "def false_claim_inverted_slice_has_positive_count() -> bool:\n    ensure result == true\n    start: u64 = 4\n    end: u64 = 3\n    length: u64 = 6\n    count: u64 = 0\n    return count > 0",
    "false_claim_negative_string_start_is_nonzero": "def false_claim_negative_string_start_is_nonzero() -> bool:\n    ensure result == true\n    start: i64 = -1\n    normalised_start: u64 = 0\n    return normalised_start > 0",
    "false_claim_negative_string_end_becomes_zero": "def false_claim_negative_string_end_becomes_zero() -> bool:\n    ensure result == true\n    end: i64 = -1\n    length: u64 = 2\n    normalised_end: u64 = 2\n    return normalised_end == 0",
}
negative_text = NEGATIVE.read_text()
for name, expected in expected_negative.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"slice-bounds negative control {name} changed its counterexample")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("slice-bounds proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", LLVM_HEADER, GUARDS, CALL, SLICES,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert {item["name"] for item in positive["declaration_details"] if item.get("verified")} == POSITIVE_NAMES
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == replay(POSITIVE)[1], "slice-bounds proof report changed across identical runs"

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert negative["summary"]["proven"] == positive["summary"]["proven"]
assert negative["summary"]["obligations"] == negative["summary"]["proven"] + len(NEGATIVE_NAMES)
assert {item["name"] for item in negative["findings"]} == NEGATIVE_NAMES
assert all(item["kind"] == "ensure-unproven" and item["status"] in ("unknown", "disproved")
           for item in negative["findings"])
assert NEGATIVE_NAMES.isdisjoint({item["name"] for item in negative["declaration_details"] if item.get("verified")})

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product or pinned source tree changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "clamped slice offsets and counts stay within their source extent for known-length views",
    "positive_proofs": positive["summary"]["proven"],
    "independently_replayed": positive["replay"]["replayed"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
