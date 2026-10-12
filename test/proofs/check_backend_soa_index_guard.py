"""Admit source-bound proofs for signed row validation and SoA element accesses."""
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
POSITIVE = HERE / "backend_soa_index_guard.elisa"
NEGATIVE = HERE / "backend_soa_index_guard_rejected.elisa"
GUARDS = ROOT / "src/backend/codegen_guards.elisa"
CALL_RECEIVER = ROOT / "src/backend/codegen_call_receiver.elisa"
PLACE = ROOT / "src/backend/codegen_place.elisa"
LOOPS = ROOT / "src/backend/codegen_stmt_loops.elisa"
STRUCT_CHAIN = ROOT / "src/backend/codegen_struct_chain_type.elisa"
LLVM_BINDINGS = ROOT / "src/backend/llvm_c.elisa"
LLVM_CONFIG = shutil.which(os.environ.get("LLVM_CONFIG", "llvm-config"))

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


def require_ordered(source: str, steps: tuple[str, ...], label: str) -> None:
    cursor = 0
    positions: list[int] = []
    for step in steps:
        position = source.find(step, cursor)
        positions.append(position)
        if position >= 0:
            cursor = position + len(step)
    if any(position < 0 for position in positions):
        raise SystemExit(f"{label} changed its proved operation order: {positions}")


def llvm_integer_predicates() -> dict[str, int]:
    if LLVM_CONFIG is None:
        raise SystemExit("llvm-config is required to bind SoA predicates to LLVM")
    include_dir = subprocess.run([LLVM_CONFIG, "--includedir"], check=True,
                                 capture_output=True, text=True, timeout=15).stdout.strip()
    header = Path(include_dir) / "llvm-c/Core.h"
    if not header.is_file():
        raise SystemExit(f"LLVM C API header is missing: {header}")
    text = header.read_text()
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


positive_names = {
    "soa_valid_guard",
    "signed_negative_row_is_rejected",
    "nonnegative_signed_row_keeps_count_result",
    "unsigned_row_uses_count_result",
}
negative_names = {
    "false_claim_signed_negative_row_can_be_valid",
    "false_claim_nonnegative_out_of_range_row_can_be_valid",
}
if declarations(POSITIVE) != positive_names:
    raise SystemExit("SoA row-guard proof inventory changed")
if declarations(NEGATIVE) != negative_names or \
        'include "./backend_soa_index_guard.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("SoA row-guard rejection controls changed")

predicates = llvm_integer_predicates()
if predicates.get("LLVMIntULT") != 36 or predicates.get("LLVMIntSGE") != 39:
    raise SystemExit("LLVM unsigned-less-than or signed-greater-equal predicate changed")
binding_text = compact(LLVM_BINDINGS.read_text())
if "ULT:i32=36" not in binding_text or "SGE:i32=39" not in binding_text:
    raise SystemExit("Elisa LLVMIntPredicate bindings no longer match LLVM")

guard_body = compact(function_section(GUARDS.read_text(), "emit_count_bounds_guard"))
require_ordered(guard_body, (
    'unsigned_valid:LLVMValueRef=LLVMBuildICmp(builder,36,compare_index,compare_count,"wd.in_bounds.unsigned")',
    "ifindex_is_signed:",
    'index_nonnegative:LLVMValueRef=LLVMBuildICmp(builder,39,index,LLVMConstInt(index_type,0,0),"wd.index.nonnegative")',
    'valid<-LLVMBuildAnd(builder,index_nonnegative,unsigned_valid,"wd.in_bounds.signed")',
    "_=LLVMBuildCondBr(builder,valid,ok_block,fail_block)",
), "shared signed SoA count guard")

valid_body = compact(function_section(CALL_RECEIVER.read_text(), "emit_call_receiver"))
require_ordered(valid_body, (
    'ifmethod_name=="valid"andarguments.count==1:',
    'emit_index_value_pair(arguments[0],ValueType{kind:TypeKind.Signed,bits:64},local_scope,fns,structs,generics,runtime,m,ctx,builder)issoa_valid_row_values:',
    'soa_valid_count:LLVMValueRef=darray_load_size_i64(soa_valid_count_pointer,ctx,builder,"soa.valid.count",structs.target.target_pointer_bits)',
    'soa_valid_in_bounds:LLVMValueRef=LLVMBuildICmp(builder,LLVMIntPredicate::ULT,soa_valid_row_values.target_value,soa_valid_count,"soa.valid.in_bounds")',
    "ifsoa_valid_row_values.is_signed:",
    'soa_valid_nonnegative:LLVMValueRef=LLVMBuildICmp(builder,LLVMIntPredicate::SGE,soa_valid_row_values.source_value,LLVMConstInt(soa_valid_source_type,0,0),"soa.valid.nonnegative")',
    'returnLLVMBuildAnd(builder,soa_valid_nonnegative,soa_valid_in_bounds,"soa.valid")',
    "returnsoa_valid_in_bounds",
), "rows.valid signed membership guard")

place_body = compact(function_section(PLACE.read_text(), "struct_chain_address"))
require_ordered(place_body, (
    "Expr.Index(soa_row_object,soa_row_index,soa_row_line):",
    "emit_index_value_pair(soa_row_index,ValueType{kind:TypeKind.Signed,bits:64},local_scope,fns,structs,generics,runtime,m,ctx,builder)issoa_row_index_values:",
    'soa_row_count_pointer:LLVMValueRef=LLVMBuildStructGEP2(builder,darray_llvm_type(structs,ctx),soa_row_col_pointer,1,"soa.row.count.ptr")',
    'soa_row_count:LLVMValueRef=darray_load_size_i64(soa_row_count_pointer,ctx,builder,"soa.row.count",structs.target.target_pointer_bits)',
    "emit_count_bounds_guard(soa_row_index_values.source_value,soa_row_count,soa_row_index_values.is_signed",
    'LLVMBuildGEP2(builder,llvm_type_of(soa_row_element,structs,ctx),soa_row_items,soa_row_offset_pointer,1,"soa.row.elem")',
), "rows[index].field checked column access")

loop_body = compact(function_section(LOOPS.read_text(), "emit_statement_loops"))
require_ordered(loop_body, (
    "ifsoa_iter_destructured:",
    'soa_de_count:LLVMValueRef=darray_load_size_i64(soa_de_count_pointer,ctx,builder,"soa.de.count",structs.target.target_pointer_bits)',
    'soa_de_at:LLVMValueRef=LLVMBuildLoad2(builder,soa_iter_i64,soa_iter_index,"soa.de.at")',
    "emit_count_bounds_guard(soa_de_at,soa_de_count,true,runtime,m,ctx,builder)",
    'soa_de_items:LLVMValueRef=LLVMBuildLoad2(builder,LLVMPointerTypeInContext(ctx,0),LLVMBuildStructGEP2(builder,darray_llvm_type(structs,ctx),soa_de_column,0,"soa.de.items.ptr"),"soa.de.items")',
    'LLVMBuildGEP2(builder,soa_de_llvm,soa_de_items,soa_de_offset_pointer,1,"soa.de.elem")',
), "destructured SoA row iteration")

binder_body = compact(function_section(STRUCT_CHAIN.read_text(), "soa_binder_element_address"))
require_ordered(binder_body, (
    'count:LLVMValueRef=darray_load_size_i64(count_pointer,ctx,builder,"soa.bind.count",structs.target.target_pointer_bits)',
    'at:LLVMValueRef=LLVMBuildLoad2(builder,LLVMInt64TypeInContext(ctx),structs.loops.soa_row_binder_indexes[binder_row],"soa.bind.at")',
    "emit_count_bounds_guard(at,count,true,runtime,m,ctx,builder)",
    "offsets:mutabledarray[LLVMValueRef]=[at]",
    'returnLLVMBuildGEP2(builder,llvm_type_of(element_type,structs,ctx),items,offsets_pointer,1,"soa.bind.elem")',
), "SoA row binder field access")

# Keep the complete set of indexed SoA element GEPs closed. Any new path must
# acquire a guard and an explicit source binding in this proof before admission.
backend_sources = sorted((ROOT / "src/backend").rglob("*.elisa"), key=str)
backend_text = "\n".join(path.read_text() for path in backend_sources)
soa_element_geps = re.findall(r'"soa\.([a-z]+)\.elem"', backend_text)
if sorted(soa_element_geps) != ["bind", "de", "row"]:
    raise SystemExit(f"SoA element GEP inventory changed: {soa_element_geps}")

positive_text = POSITIVE.read_text()
expected_positive = {
    "soa_valid_guard": "def soa_valid_guard(source_is_signed:bool,index_nonnegative:bool,unsigned_in_bounds:bool)->bool:\nensure result==(unsigned_in_bounds and (not source_is_signed or index_nonnegative))\nreturn unsigned_in_bounds and (not source_is_signed or index_nonnegative)",
    "signed_negative_row_is_rejected": "def signed_negative_row_is_rejected(unsigned_in_bounds:bool)->bool:\nensure result==true\nreturn not soa_valid_guard(true,false,unsigned_in_bounds)",
    "nonnegative_signed_row_keeps_count_result": "def nonnegative_signed_row_keeps_count_result(unsigned_in_bounds:bool)->bool:\nensure result==true\nreturn soa_valid_guard(true,true,unsigned_in_bounds)==unsigned_in_bounds",
    "unsigned_row_uses_count_result": "def unsigned_row_uses_count_result(index_nonnegative:bool,unsigned_in_bounds:bool)->bool:\nensure result==true\nreturn soa_valid_guard(false,index_nonnegative,unsigned_in_bounds)==unsigned_in_bounds",
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"SoA guard theorem {name} changed")
negative_text = NEGATIVE.read_text()
expected_negative = {
    "false_claim_signed_negative_row_can_be_valid": "def false_claim_signed_negative_row_can_be_valid(unsigned_in_bounds:bool)->bool:\nrequires unsigned_in_bounds\nensure result==true\nreturn soa_valid_guard(true,false,unsigned_in_bounds)",
    "false_claim_nonnegative_out_of_range_row_can_be_valid": "def false_claim_nonnegative_out_of_range_row_can_be_valid()->bool:\nensure result==true\nreturn soa_valid_guard(true,true,false)",
}
for name, expected in expected_negative.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"SoA false-claim control {name} changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("SoA index proofs require a strict proof build")

compiler_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
compiler_provenance = Path(str(compiler_product) + ".provenance.json").resolve(strict=True)
llvm_header = Path(subprocess.run([LLVM_CONFIG, "--includedir"], check=True,
                                  capture_output=True, text=True, timeout=15).stdout.strip()) / "llvm-c/Core.h"
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", compiler_product, compiler_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]), GUARDS, CALL_RECEIVER, PLACE,
    LOOPS, STRUCT_CHAIN, LLVM_BINDINGS, llvm_header, *backend_sources,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    assert report["kernel"]["independent_replay"] is True
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 8
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "SoA guard report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 12 and negative["summary"]["proven"] == 10
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "rows.valid negative-index rejection and bounds-before-GEP on all indexed SoA element-access paths",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
