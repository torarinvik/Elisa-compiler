"""Admit a source-bound bounds proof for the bytes.as_cstr() terminator slot."""
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
FACADE = ROOT / "src/backend/codegen.elisa"
STRING_VIEWS = ROOT / "src/backend/codegen_string_views.elisa"
CONTAINER_OPS = ROOT / "src/backend/codegen_container_ops.elisa"
GUARDS = ROOT / "src/backend/codegen_guards.elisa"
VALUE_TYPE = ROOT / "src/backend/codegen_value_type.elisa"
POLICY = ROOT / "src/backend/codegen_cstr_terminator_policy.elisa"
POSITIVE = HERE / "backend_cstr_terminator.elisa"
NEGATIVE = HERE / "backend_cstr_terminator_rejected.elisa"

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


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


policy_text = POLICY.read_text()
policy_shapes = {
    "target_size_max": """
def target_size_max(pointer_bits: u32) -> u64:
    ensure result == (U32_MAX if pointer_bits == POINTER_BITS_32 else (U64_MAX if pointer_bits == POINTER_BITS_64 else 0))
    return match pointer_bits:
        32: U32_MAX
        64: U64_MAX
        _: 0
""",
    "count_plus_one_is_representable": """
def count_plus_one_is_representable(count: u64, pointer_bits: u32) -> bool:
    ensure result == (count < target_size_max(pointer_bits))
    return count < target_size_max(pointer_bits)
""",
    "terminator_capacity": """
def terminator_capacity(count: u64, pointer_bits: u32) -> u64:
    requires pointer_bits == POINTER_BITS_32 or pointer_bits == POINTER_BITS_64
    requires count != U64_MAX
    requires count < target_size_max(pointer_bits)
    ensure result == count + TERMINATOR_EXTRA_BYTES
    ensure result > count
    ensure result <= target_size_max(pointer_bits)
    return count + TERMINATOR_EXTRA_BYTES
""",
    "terminator_index_is_in_bounds": """
def terminator_index_is_in_bounds(count: u64, capacity: u64, pointer_bits: u32) -> bool:
    requires pointer_bits == POINTER_BITS_32 or pointer_bits == POINTER_BITS_64
    requires count != U64_MAX
    requires count < target_size_max(pointer_bits)
    requires capacity >= terminator_capacity(count, pointer_bits)
    ensure result == true
    return count < capacity
""",
}
if compact("const POINTER_BITS_32: u32 = 32") not in compact(policy_text) or \
        compact("const POINTER_BITS_64: u32 = 64") not in compact(policy_text):
    raise SystemExit("C-string policy lost named target pointer-width constants")
if compact("const U32_MAX: u64 = 4294967295") not in compact(policy_text):
    raise SystemExit("C-string terminator arithmetic model changed its 32-bit usize bound")
if compact("const U64_MAX: u64 = 18446744073709551615u64") not in compact(policy_text):
    raise SystemExit("C-string terminator arithmetic model changed its u64 bound")
if compact("const TERMINATOR_EXTRA_BYTES: u64 = 1") not in compact(policy_text):
    raise SystemExit("C-string terminator model no longer reserves exactly one byte")
for name, expected in policy_shapes.items():
    if compact(function_section(policy_text, name)) != compact(expected):
        raise SystemExit(f"production C-string terminator policy {name} changed")

facade_text = compact(FACADE.read_text())
policy_include = compact('include "./codegen_cstr_terminator_policy.elisa"')
env_include = compact('include "./codegen_env.elisa"')
string_views_include = compact('include "./codegen_string_views.elisa"')
if (facade_text.find(policy_include) < 0 or facade_text.find(env_include) < 0 or
        facade_text.find(policy_include) >= facade_text.find(env_include) or
        facade_text.find(string_views_include) < 0):
    raise SystemExit("the C-string arithmetic policy is not included before its production consumer")

string_views_text = STRING_VIEWS.read_text()
string_views_compact = compact(string_views_text)
for field_constant in (
    "const DARRAY_ITEMS_FIELD_INDEX: u32 = 0",
    "const DARRAY_COUNT_FIELD_INDEX: u32 = 1",
):
    if compact(field_constant) not in string_views_compact:
        raise SystemExit("as_cstr no longer loads the byte pointer and logical count from their DArray header slots")
if compact("const DARRAY_CSTR_TERMINATOR_EXTRA_BYTES: u64 = BackendCStrTerminatorPolicy::TERMINATOR_EXTRA_BYTES") not in compact(string_views_text):
    raise SystemExit("as_cstr no longer consumes the proved one-byte terminator policy")
cstr = compact(function_section(string_views_text, "emit_as_cstr_builtin"))
ordered_cstr_steps = (
    "nullreturnifarguments.count!=0",
    'nullreturnifac_name!="as_cstr"',
    "nullreturnifac_type.kind!=TypeKind.DArray",
    "nullreturnifac_element.kind!=TypeKind.Unsignedorac_element.bits!=8",
    "ac_count:LLVMValueRef=darray_load_size_i64(ac_count_pointer,ctx,builder,\"darray.cstr.count\",structs.target.target_pointer_bits)",
    "ac_target_size_max:LLVMValueRef=LLVMConstInt(ac_i64,BackendCStrTerminatorPolicy::target_size_max(structs.target.target_pointer_bits),0)",
    "ac_count_can_grow:LLVMValueRef=LLVMBuildICmp(builder,LLVMIntPredicate::ULT,ac_count,ac_target_size_max,\"darray.cstr.count.can.grow\")",
    "ac_function:LLVMValueRef=LLVMGetBasicBlockParent(LLVMGetInsertBlock(builder))",
    "ac_limit_trap:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,ac_function,\"darray.cstr.count.limit\")",
    "ac_limit_ok:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,ac_function,\"darray.cstr.count.valid\")",
    "_=LLVMBuildCondBr(builder,ac_count_can_grow,ac_limit_ok,ac_limit_trap)",
    "LLVMPositionBuilderAtEnd(builder,ac_limit_trap)",
    "emit_trap_unreachable(m,ctx,builder)",
    "LLVMPositionBuilderAtEnd(builder,ac_limit_ok)",
    "ac_extra:LLVMValueRef=LLVMConstInt(ac_i64,DARRAY_CSTR_TERMINATOR_EXTRA_BYTES,0)",
    "emit_checked_reserve_binary(ac_count,ac_extra,false,m,ctx,builder,structs.target.target_pointer_bits)isac_needed",
    "emit_darray_reserve(ac_slot,ac_type,ac_needed,structs,ac_growth_runtime,m,ctx,builder)",
    "ac_items_pointer:LLVMValueRef=LLVMBuildStructGEP2(builder,ac_header,ac_slot,DARRAY_ITEMS_FIELD_INDEX,\"darray.cstr.items.ptr\")",
    "ac_items:LLVMValueRef=LLVMBuildLoad2(builder,LLVMPointerTypeInContext(ctx,0),ac_items_pointer,\"darray.cstr.items\")",
    "ac_terminator:LLVMValueRef=LLVMBuildGEP2(builder,LLVMInt8TypeInContext(ctx),ac_items,ac_indices_pointer,1,\"darray.cstr.nul.ptr\")",
    "LLVMBuildStore(builder,LLVMConstInt(LLVMInt8TypeInContext(ctx),0,0),ac_terminator)",
    "returnac_items",
)
positions = [cstr.find(step) for step in ordered_cstr_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("as_cstr no longer checks count+1, reserves first, then writes NUL at the old byte count")
if cstr.count("LLVMBuildStore(") != 1:
    raise SystemExit("as_cstr changed its sole byte store; logical darray count must remain unchanged")
if cstr.count("LLVMBuildGEP2(") != 1 or "ac_indices:mutabledarray[LLVMValueRef]=[ac_count]" not in cstr:
    raise SystemExit("as_cstr terminator address is no longer based on the original count in bytes")
if cstr.count("LLVMBuildCondBr(") != 1 or cstr.count("emit_trap_unreachable(m,ctx,builder)") != 1:
    raise SystemExit("as_cstr must trap when count+1 cannot fit the target's usize")

target_pointer_bits = compact(function_section(VALUE_TYPE.read_text(), "target_pointer_bits"))
if target_pointer_bits != compact("""
def target_pointer_bits() -> u32:
    return 32 if getenv("ELISA_STAGE1_WASM") is wasm_target
    return 64
"""):
    raise SystemExit("target size bound must cover the compiler's exact 32-bit and 64-bit targets")
trap_source = compact(function_section(GUARDS.read_text(), "emit_trap_unreachable"))
if 'trap_name:cstr="llvm.trap"' not in trap_source or "LLVMBuildUnreachable(builder)" not in trap_source:
    raise SystemExit("the C-string target-width rejection no longer terminates with a trap")

container_text = CONTAINER_OPS.read_text()
checked_add = compact(function_section(container_text, "emit_checked_reserve_binary"))
overflow_binary = compact(function_section(container_text, "emit_overflow_binary"))
if ("ifemit_overflow_binary(left,right,multiply,m,ctx,builder,target_bits)isresult:" not in checked_add or
        "_=LLVMBuildCondBr(builder,result.overflow,trap_block,continue_block)" not in checked_add or
        "emit_trap_unreachable(m,ctx,builder)" not in checked_add or
        "returnresult.value" not in checked_add):
    raise SystemExit("checked reserve arithmetic no longer traps before exposing an overflowing result")
if ('intrinsic_name:sview="llvm.umul.with.overflow"ifmultiplyelse"llvm.uadd.with.overflow"' not in overflow_binary or
        'call:LLVMValueRef=LLVMBuildCall2(builder,LLVMGlobalGetValueType(intrinsic_fn),intrinsic_fn,arguments_pointer,2,"checked.binary")' not in overflow_binary):
    raise SystemExit("non-multiplying reserve bounds no longer use the checked unsigned-add intrinsic")

reserve = compact(function_section(container_text, "emit_darray_reserve"))
reserve_steps = (
    "normalized_needed:mutableLLVMValueRef=darray_size_value_i64(needed,ctx,builder,\"reserve.needed.i64\")",
    "emit_checked_target_size(normalized_needed,m,ctx,builder,structs.target.target_pointer_bits)istarget_sized_needed",
    "capacity:LLVMValueRef=darray_load_size_i64(capacity_pointer,ctx,builder,\"reserve.cap\",structs.target.target_pointer_bits)",
    "enough:LLVMValueRef=LLVMBuildICmp(builder,35,capacity,normalized_needed,\"reserve.cap.ok\")",
    "_=LLVMBuildCondBr(builder,enough,done_block,grow_block)",
    "darray_store_size(builder,normalized_needed,capacity_pointer,ctx,structs.target.target_pointer_bits)",
)
reserve_positions = [reserve.find(step) for step in reserve_steps]
if any(position < 0 for position in reserve_positions) or reserve_positions != sorted(reserve_positions):
    raise SystemExit("successful exact darray reserve no longer leaves capacity at least the requested element count")
if (reserve.count("darray_store_size(builder,normalized_needed,capacity_pointer,ctx,structs.target.target_pointer_bits)") != 2 or
        reserve.rfind("returntrue") < reserve.rfind("darray_store_size(builder,normalized_needed,capacity_pointer,ctx,structs.target.target_pointer_bits)")):
    raise SystemExit("exact reserve no longer stores the requested capacity in both successful growth branches")
if "count_pointer" in reserve or reserve.count("capacity_pointer") < 4:
    raise SystemExit("reserve must update capacity while preserving the logical element count")
if "geometric:bool=false" not in reserve or "emit_darray_reserve(ac_slot,ac_type,ac_needed,structs,ac_growth_runtime,m,ctx,builder)" not in cstr:
    raise SystemExit("as_cstr must use exact reserve growth to at least count+1 without changing logical count")

if 'include "../../src/backend/codegen_cstr_terminator_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive C-string proof no longer imports the production arithmetic policy")
if 'include "./backend_cstr_terminator.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer import the positive C-string proofs")
positive_names = {
    "target_32_bit_uses_the_u32_size_maximum",
    "target_64_bit_uses_the_u64_size_maximum",
    "unsupported_target_width_has_no_reservable_capacity",
    "required_capacity_is_exactly_one_past_count",
    "every_admitted_terminator_index_fits_its_capacity",
    "maximum_count_cannot_reserve_an_extra_byte",
    "the_largest_admitted_32_bit_count_has_a_representable_terminator_capacity",
    "the_largest_admitted_64_bit_count_has_a_representable_terminator_capacity",
}
negative_names = {
    "false_claim_required_capacity_equals_count",
    "false_claim_maximum_32_bit_count_can_grow_by_one",
    "false_claim_maximum_64_bit_count_can_grow_by_one",
}
if declaration_names(POSITIVE) != positive_names or declaration_names(NEGATIVE) != negative_names:
    raise SystemExit("C-string terminator proof inventory changed")
positive_claims = {
    "target_32_bit_uses_the_u32_size_maximum": """
def target_32_bit_uses_the_u32_size_maximum() -> bool:
    ensure result == true
    return BackendCStrTerminatorPolicy::target_size_max(BackendCStrTerminatorPolicy::POINTER_BITS_32) == BackendCStrTerminatorPolicy::U32_MAX
""",
    "target_64_bit_uses_the_u64_size_maximum": """
def target_64_bit_uses_the_u64_size_maximum() -> bool:
    ensure result == true
    return BackendCStrTerminatorPolicy::target_size_max(BackendCStrTerminatorPolicy::POINTER_BITS_64) == BackendCStrTerminatorPolicy::U64_MAX
""",
    "unsupported_target_width_has_no_reservable_capacity": """
def unsupported_target_width_has_no_reservable_capacity(pointer_bits: u32) -> bool:
    requires pointer_bits != BackendCStrTerminatorPolicy::POINTER_BITS_32
    requires pointer_bits != BackendCStrTerminatorPolicy::POINTER_BITS_64
    ensure result == true
    return BackendCStrTerminatorPolicy::target_size_max(pointer_bits) == 0
""",
    "required_capacity_is_exactly_one_past_count": """
def required_capacity_is_exactly_one_past_count(count: u64, pointer_bits: u32) -> bool:
    requires pointer_bits == BackendCStrTerminatorPolicy::POINTER_BITS_32 or pointer_bits == BackendCStrTerminatorPolicy::POINTER_BITS_64
    requires BackendCStrTerminatorPolicy::count_plus_one_is_representable(count, pointer_bits)
    requires count < BackendCStrTerminatorPolicy::target_size_max(pointer_bits)
    ensure result == true
    return BackendCStrTerminatorPolicy::terminator_capacity(count, pointer_bits) == count + BackendCStrTerminatorPolicy::TERMINATOR_EXTRA_BYTES
""",
    "every_admitted_terminator_index_fits_its_capacity": """
def every_admitted_terminator_index_fits_its_capacity(count: u64, capacity: u64, pointer_bits: u32) -> bool:
    requires pointer_bits == BackendCStrTerminatorPolicy::POINTER_BITS_32 or pointer_bits == BackendCStrTerminatorPolicy::POINTER_BITS_64
    requires BackendCStrTerminatorPolicy::count_plus_one_is_representable(count, pointer_bits)
    requires count < BackendCStrTerminatorPolicy::target_size_max(pointer_bits)
    requires capacity >= BackendCStrTerminatorPolicy::terminator_capacity(count, pointer_bits)
    ensure result == true
    return BackendCStrTerminatorPolicy::terminator_index_is_in_bounds(count, capacity, pointer_bits)
""",
    "maximum_count_cannot_reserve_an_extra_byte": """
def maximum_count_cannot_reserve_an_extra_byte() -> bool:
    ensure result == true
    return not BackendCStrTerminatorPolicy::count_plus_one_is_representable(BackendCStrTerminatorPolicy::U64_MAX, BackendCStrTerminatorPolicy::POINTER_BITS_64)
""",
    "the_largest_admitted_32_bit_count_has_a_representable_terminator_capacity": """
def the_largest_admitted_32_bit_count_has_a_representable_terminator_capacity() -> bool:
    ensure result == true
    largest_count: u64 = BackendCStrTerminatorPolicy::U32_MAX - BackendCStrTerminatorPolicy::TERMINATOR_EXTRA_BYTES
    return BackendCStrTerminatorPolicy::count_plus_one_is_representable(largest_count, BackendCStrTerminatorPolicy::POINTER_BITS_32) and BackendCStrTerminatorPolicy::terminator_capacity(largest_count, BackendCStrTerminatorPolicy::POINTER_BITS_32) == BackendCStrTerminatorPolicy::U32_MAX
""",
    "the_largest_admitted_64_bit_count_has_a_representable_terminator_capacity": """
def the_largest_admitted_64_bit_count_has_a_representable_terminator_capacity() -> bool:
    ensure result == true
    largest_count: u64 = BackendCStrTerminatorPolicy::U64_MAX - BackendCStrTerminatorPolicy::TERMINATOR_EXTRA_BYTES
    return BackendCStrTerminatorPolicy::count_plus_one_is_representable(largest_count, BackendCStrTerminatorPolicy::POINTER_BITS_64) and BackendCStrTerminatorPolicy::terminator_capacity(largest_count, BackendCStrTerminatorPolicy::POINTER_BITS_64) == BackendCStrTerminatorPolicy::U64_MAX
""",
}
negative_claims = {
    "false_claim_required_capacity_equals_count": """
def false_claim_required_capacity_equals_count(count: u64, pointer_bits: u32) -> bool:
    requires pointer_bits == BackendCStrTerminatorPolicy::POINTER_BITS_32 or pointer_bits == BackendCStrTerminatorPolicy::POINTER_BITS_64
    requires BackendCStrTerminatorPolicy::count_plus_one_is_representable(count, pointer_bits)
    requires count < BackendCStrTerminatorPolicy::target_size_max(pointer_bits)
    ensure result == true
    return BackendCStrTerminatorPolicy::terminator_capacity(count, pointer_bits) == count
""",
    "false_claim_maximum_32_bit_count_can_grow_by_one": """
def false_claim_maximum_32_bit_count_can_grow_by_one() -> bool:
    ensure result == true
    return BackendCStrTerminatorPolicy::count_plus_one_is_representable(BackendCStrTerminatorPolicy::U32_MAX, BackendCStrTerminatorPolicy::POINTER_BITS_32)
""",
    "false_claim_maximum_64_bit_count_can_grow_by_one": """
def false_claim_maximum_64_bit_count_can_grow_by_one() -> bool:
    ensure result == true
    return BackendCStrTerminatorPolicy::count_plus_one_is_representable(BackendCStrTerminatorPolicy::U64_MAX, BackendCStrTerminatorPolicy::POINTER_BITS_64)
""",
}
for name, expected in positive_claims.items():
    if compact(function_section(POSITIVE.read_text(), name)) != compact(expected):
        raise SystemExit(f"positive C-string proof {name} changed its theorem")
for name, expected in negative_claims.items():
    if compact(function_section(NEGATIVE.read_text(), name)) != compact(expected):
        raise SystemExit(f"negative C-string control {name} changed its false theorem")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("C-string terminator proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", FACADE, STRING_VIEWS,
    CONTAINER_OPS, GUARDS, VALUE_TYPE, POLICY, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
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
assert {item["name"] for item in positive["declaration_details"] if item.get("verified")} == positive_names
assert positive == replay(POSITIVE)[1], "C-string terminator proof report changed across repeated runs"

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {finding["name"] for finding in negative["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert negative_names.isdisjoint({item["name"] for item in negative["declaration_details"] if item.get("verified")})

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product or pinned source tree changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-bound count+1 capacity and in-bounds byte terminator index for bytes.as_cstr()",
    "proofs": len(positive_names),
    "producer_proven": positive["summary"]["proven"],
    "independently_replayed": positive["replay"]["replayed"],
    "false_claims_rejected": sorted(negative_names),
    "sources_sha256": hashes_before,
}))
