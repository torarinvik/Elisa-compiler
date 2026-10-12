"""Admit the proved StringView index guard against runtime and LLVM lowering."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "sview_index_bounds.elisa"
NEGATIVE = HERE / "sview_index_bounds_rejected.elisa"
INDEX_READ = ROOT / "src/backend/codegen_expr_index_read.elisa"
SHORT_CIRCUIT = ROOT / "src/backend/codegen_match_arm_facts.elisa"
BINARY_TAIL = ROOT / "src/backend/codegen_expr_binary_tail.elisa"
FIELD_READ = ROOT / "src/backend/codegen_expr_field_read.elisa"
TYPE_PLACE = ROOT / "src/backend/codegen_expression_type_place.elisa"
LLVM_BINDINGS = ROOT / "src/backend/llvm_c.elisa"
RUNTIME_DECL = ROOT / "src/backend/codegen_runtime_decl.elisa"
INFER = ROOT / "src/semantic/resolve_types_infer.elisa"
UNKNOWN_FIELD = ROOT / "src/semantic/check_unknown_field_access.elisa"
EASM_PARSER = ROOT / "src/backend/easm_verify_function.elisa"
EASM_DECIMAL = ROOT / "src/backend/easm_checked_decimal.elisa"
RUNTIME_STRINGS = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
RUNTIME_WRAPPER = ROOT / "elisacore_std/runtime.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_body(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one production function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


index_source = INDEX_READ.read_text()
inline = compact(function_body(index_source, "emit_inline_sview_index"))
index_emitter = compact(function_body(index_source, "emit_expression_index_read"))
short_circuit = compact(function_body(SHORT_CIRCUIT.read_text(), "emit_short_circuit"))
binary_tail = compact(BINARY_TAIL.read_text())
runtime_index = compact(function_body(RUNTIME_STRINGS.read_text(), "string_view_index"))
field_emitter = compact(function_body(FIELD_READ.read_text(), "emit_expression_field_read"))
place_type = compact(function_body(TYPE_PLACE.read_text(), "expression_type_of_place"))
infer_source = compact(function_body(INFER.read_text(), "infer_expression_type"))
unknown_fields = compact(function_body(UNKNOWN_FIELD.read_text(), "runtime_struct_has_field"))
parser = compact(function_body(EASM_PARSER.read_text(), "easm_parse_i64_checked"))
decimal_parser = compact(function_body(EASM_DECIMAL.read_text(), "parse_signed"))
wrapper = compact(function_body(RUNTIME_WRAPPER.read_text(), "ctx_string_view_index"))

# The first term is the signed nonnegative-length check; the second is an
# unsigned less-than over the i64 index bits. Together, LLVM rejects negative
# indexes as well as indexes at or beyond the length. Keep the load dominated by
# that branch and retain the zero result on every rejected path.
required_inline = (
    'i64_type:LLVMTypeRef=LLVMInt64TypeInContext(ctx)',
    'length:LLVMValueRef=LLVMBuildExtractValue(builder,view,1,"sview.idx.len")',
    'length_ok:LLVMValueRef=LLVMBuildICmp(builder,39,length,zero,"sview.idx.len.ok")',
    'index_ok:LLVMValueRef=LLVMBuildICmp(builder,36,index,length,"sview.idx.in")',
    'in_range:LLVMValueRef=LLVMBuildAnd(builder,length_ok,index_ok,"sview.idx.ok")',
    '_=LLVMBuildStore(builder,zero,slot)',
    '_=LLVMBuildCondBr(builder,in_range,read_block,join_block)',
    'LLVMBuildGEP2(builder,LLVMInt8TypeInContext(ctx),data,indices_pointer,1,"sview.idx.ptr")',
    'LLVMBuildLoad2(builder,LLVMInt8TypeInContext(ctx),byte_pointer,"sview.idx.byte")',
    'LLVMBuildZExt(builder,byte,i64_type,"sview.idx.wide")',
)
if not all(fragment in inline for fragment in required_inline):
    raise SystemExit("inline StringView indexing no longer guards and zero-extends the byte load")
llvm_predicates = compact(LLVM_BINDINGS.read_text())
if "LLVMIntPredicate:EQ=32,NE=33,UGT=34,UGE=35,ULT=36,ULE=37" not in llvm_predicates or \
        "SGT=38,SGE=39,SLT=40,SLE=41" not in llvm_predicates:
    raise SystemExit("LLVM comparison predicate assignments changed without updating the proof binding")
read_block = inline.split('LLVMPositionBuilderAtEnd(builder,read_block)', 1)
if len(read_block) != 2 or read_block[1].find('LLVMBuildGEP2(') < 0 or \
        read_block[1].find('LLVMBuildLoad2(') < read_block[1].find('LLVMBuildGEP2(') or \
        read_block[1].find('LLVMBuildBr(builder,join_block)') < read_block[1].find('LLVMBuildLoad2('):
    raise SystemExit("inline StringView byte dereference escaped its guarded read block")
if 'ifstructs.target.target_pointer_bits==64:' not in index_emitter or \
        'runtime.sview_index' not in index_emitter or \
        'emit_expression(index_expression,ValueType{kind:TypeKind.Signed,bits:64}' not in index_emitter:
    raise SystemExit("non-64-bit StringView indexing no longer uses the runtime bounds-checked helper")

# The source-level `and` in the parser must lower to control flow that skips
# text[0] when the length test is false. Pin the expression dispatcher and the
# RHS block placement, since an eager Boolean AND would invalidate the proof.
if 'ifbinary_operator==TokenKind.Andorbinary_operator==TokenKind.Or:returnemit_short_circuit(binary_left,binary_operator,binary_right' not in binary_tail:
    raise SystemExit("boolean and/or no longer dispatch through short-circuit lowering")
short_circuit_steps = (
    'is_and:bool=operator==TokenKind.And',
    'ifis_and:_=LLVMBuildCondBr(builder,left_bit,rhs_block,done_block)',
    'LLVMPositionBuilderAtEnd(builder,rhs_block)',
    'emit_condition(right_expression,local_scope',
)
short_positions = [short_circuit.find(step) for step in short_circuit_steps]
if any(position < 0 for position in short_positions) or short_positions != sorted(short_positions):
    raise SystemExit("short-circuit AND no longer evaluates its RHS only after a true left side")

# Pin the source-level alias to the actual StringView length member, its inferred
# and backend scalar type, and the aggregate field extracted by code generation.
if '"len"|"length"->true' not in infer_source or \
        'InferType{kind:SemTypeKind.Int,name:"i64"}returnifobject_type.kind==SemTypeKind.Stringandobject_type.name=="sview"andis_sview_size_field' not in infer_source:
    raise SystemExit("semantic inference no longer types StringView.length as i64")
if '"len"|"length"->true' not in place_type or \
        'ValueType{kind:TypeKind.Signed,bits:64}returnifindexed_type.kind==TypeKind.CStrorindexed_type.kind==TypeKind.SView' not in place_type:
    raise SystemExit("backend expression typing no longer exposes StringView.length as signed i64")
if '"data"|"len"|"length"->true' not in field_emitter or \
        'LLVMBuildExtractValue(builder,sview_value,1,"sview.len")' not in field_emitter:
    raise SystemExit("StringView.length no longer reads the length field from its runtime pair")
if '"StringView"->whenfield:"data"|"len"|"length"->true' not in unknown_fields:
    raise SystemExit("unknown-field validation no longer recognizes StringView.length")

runtime_decl = compact(RUNTIME_DECL.read_text())
if 'sview_fields:mutabledarray[LLVMTypeRef]=[pointer_type,int64_type]' not in runtime_decl or \
        'sview_index_params:mutabledarray[LLVMTypeRef]=[sview_type,int64_type]' not in runtime_decl or \
        'sview_index_type:LLVMTypeRef=LLVMFunctionType(int64_type,sview_index_pointer,2,0)' not in runtime_decl:
    raise SystemExit("StringView runtime layout/index ABI no longer uses pointer-plus-i64 and an i64 index")

# The compiler's checked-decimal parser exercises the exact `.length` and `[0]`
# syntax whose bounds are proved here. The fallback wrapper must preserve the
# production runtime index helper's semantics.
if 'iftext.length>0andtext[0]==ASCII_MINUS:' not in decimal_parser or \
        'returnEasmCheckedDecimal::parse_signed(text)' not in parser:
    raise SystemExit("checked-decimal parser no longer guards its first-byte read with text.length")
runtime_steps = (
    '0returnifview.len<0',
    'view_len:usize=view.len.usize()',
    '0returnifview_len.i64()!=view.len',
    '0returnifindex<0orindex>=view.len',
    'index_usize:usize=index.usize()',
    '0returnifindex_usize.i64()!=index',
    'returnview.data[index_usize].i64()',
)
positions = [runtime_index.find(step) for step in runtime_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("runtime StringView indexing no longer validates length/index before dereference")
if 'returnstring_view_index(view,index)' not in wrapper:
    raise SystemExit("runtime StringView index ABI wrapper no longer delegates to the checked helper")

positive_names = {
    "sview_index_guard",
    "index_zero_is_guarded_by_a_positive_length",
    "parser_first_byte_is_within_a_nonempty_view",
    "negative_index_never_passes_the_guard",
    "index_at_end_never_passes_the_guard",
    "an_unrepresentable_length_never_passes_the_guard",
    "an_unrepresentable_index_never_passes_the_guard",
    "accepted_index_is_strictly_inside_the_view",
}
negative_names = {
    "false_claim_accepts_a_negative_index",
    "false_claim_accepts_the_one_past_end_index",
    "false_claim_accepts_an_unrepresentable_length",
    "false_claim_accepts_an_unrepresentable_index",
}


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declaration_names(POSITIVE) != positive_names:
    raise SystemExit("StringView bounds proof inventory changed")
if declaration_names(NEGATIVE) != negative_names or \
        'include "./sview_index_bounds.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("StringView bounds negative controls changed")

positive_text = compact(POSITIVE.read_text())
required_models = (
    "ensure result == (length >= 0 and length_fits_usize and index >= 0 and index_fits_usize and index < length) return length >= 0 and length_fits_usize and index >= 0 and index_fits_usize and index < length",
    "requires length > 0 and index == 0 and length_fits_usize and index_fits_usize ensure result == true return length >= 0 and length_fits_usize and index >= 0 and index_fits_usize and index < length",
    "requires length > 0 and index == 0 ensure result == true return index >= 0 and index < length",
    "requires index < 0 ensure result == true return not sview_index_guard(length, index, length_fits_usize, index_fits_usize)",
    "requires length >= 0 ensure result == true return not sview_index_guard(length, length, length_fits_usize, index_fits_usize)",
    "requires not length_fits_usize ensure result == true return not sview_index_guard(length, index, length_fits_usize, index_fits_usize)",
    "requires not index_fits_usize ensure result == true return not sview_index_guard(length, index, length_fits_usize, index_fits_usize)",
    "requires sview_index_guard(length, index, length_fits_usize, index_fits_usize) ensure result == true return length >= 0 and length_fits_usize and index >= 0 and index_fits_usize and index < length",
)
if not all(compact(model) in positive_text for model in required_models):
    raise SystemExit("StringView bounds proofs no longer establish their stated arithmetic guards")
negative_text = compact(NEGATIVE.read_text())
required_false_claims = (
    "requires index < 0 ensure result == true return sview_index_guard(length, index, length_fits_usize, index_fits_usize)",
    "requires length >= 0 ensure result == true return sview_index_guard(length, length, length_fits_usize, index_fits_usize)",
    "requires not length_fits_usize ensure result == true return sview_index_guard(length, index, length_fits_usize, index_fits_usize)",
    "requires not index_fits_usize ensure result == true return sview_index_guard(length, index, length_fits_usize, index_fits_usize)",
)
if not all(compact(model) in negative_text for model in required_false_claims):
    raise SystemExit("StringView bounds negative controls no longer challenge the boundary laws")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("StringView index proofs require a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    INDEX_READ,
    SHORT_CIRCUIT,
    BINARY_TAIL,
    FIELD_READ,
    TYPE_PLACE,
    LLVM_BINDINGS,
    RUNTIME_DECL,
    INFER,
    UNKNOWN_FIELD,
    EASM_PARSER,
    EASM_DECIMAL,
    RUNTIME_STRINGS,
    RUNTIME_WRAPPER,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 16
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "StringView index proof report changed across repeated runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 24 and negative["summary"]["proven"] == 20
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", "false_claim_accepts_a_negative_index"),
    ("ensure-unproven", "false_claim_accepts_the_one_past_end_index"),
    ("ensure-unproven", "false_claim_accepts_an_unrepresentable_length"),
    ("ensure-unproven", "false_claim_accepts_an_unrepresentable_index"),
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "StringView signed-length, negative-index, one-past-end, and first-byte access guards across runtime and LLVM lowering",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
