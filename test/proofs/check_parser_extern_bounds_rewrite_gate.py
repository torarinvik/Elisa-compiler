"""Admit the extern-bounds fail-closed rewrite gate against its parser source."""
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
SOURCE = ROOT / "src/parser/parser_extern_bounds.elisa"
POSITIVE = HERE / "parser_extern_bounds_rewrite_gate.elisa"
NEGATIVE = HERE / "parser_extern_bounds_rewrite_gate_rejected.elisa"

POSITIVE_SHAPES = {
    "bounds_rewrite_gate_is_exact": (
        "ensure result == not (failed or no_valid_pairs) "
        "return not (failed or no_valid_pairs)"
    ),
    "failed_validation_never_rewrites": (
        "requires failed ensure result == false "
        "return not (failed or no_valid_pairs)"
    ),
    "empty_pair_set_never_rewrites": (
        "requires not failed and no_valid_pairs ensure result == false "
        "return not (failed or no_valid_pairs)"
    ),
    "valid_pairs_enter_rewrite": (
        "requires not failed and not no_valid_pairs ensure result == true "
        "return not (failed or no_valid_pairs)"
    ),
    "malformed_arity_is_rejected": (
        "ensure result == (no_arguments or is_odd) return no_arguments or is_odd"
    ),
    "both_parameter_names_must_exist": (
        "ensure result == (pointer_found and length_found) return pointer_found and length_found"
    ),
    "pair_indices_must_be_distinct_and_unused": (
        "ensure result == not (same_index or pointer_reused or length_reused) "
        "return not (same_index or pointer_reused or length_reused)"
    ),
    "pointer_parameter_must_be_required_reference": (
        "ensure result == (is_ref and not is_optional) return is_ref and not is_optional"
    ),
    "length_parameter_must_be_nonreference_integer": (
        "ensure result == (not is_ref and is_integer_type) return not is_ref and is_integer_type"
    ),
}
NEGATIVE_SHAPES = {
    "false_claim_failed_validation_can_rewrite": (
        "requires failed ensure result == true "
        "return not (failed or no_valid_pairs)"
    ),
    "false_claim_reference_length_parameter_is_valid": (
        "requires is_ref ensure result == true return not is_ref and is_integer_type"
    ),
}
ELISA_INDENT_WIDTH = 4
PROOF_PROCESS_TIMEOUT_SECONDS = 60
OBLIGATIONS_PER_FALSE_CLAIM = 2
SOURCE_CONSTANTS = (
    "EXTERN_BOUNDS_NO_ARGUMENTS:u32=0",
    "EXTERN_BOUNDS_ARGUMENTS_PER_PAIR:u32=2",
    "EXTERN_BOUNDS_NO_VALID_PAIRS:usize=0",
    "EXTERN_BOUNDS_INVALID_PARAMETER_INDEX:i64=-1",
    "EXTERN_BOUNDS_POINTER_ARGUMENT_OFFSET:usize=0",
    "EXTERN_BOUNDS_LENGTH_ARGUMENT_OFFSET:usize=1",
    "EXTERN_BOUNDS_CPART_STRIDE:u32=8",
    "EXTERN_BOUNDS_CPART_WHOLE:u32=0",
    "EXTERN_BOUNDS_CPART_POINTER:u32=1",
    "EXTERN_BOUNDS_CPART_LENGTH:u32=2",
    "EXTERN_BOUNDS_NO_FN_TYPE_LINE:u32=0",
    "EXTERN_BOUNDS_NO_FN_TYPE_PARAM_COUNT:u32=0",
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


def direct_children(lines: list[str], parent_index: int, parent_indent: int) -> list[tuple[int, str]]:
    children = []
    for index in range(parent_index + 1, len(lines)):
        line = lines[index]
        content = line.lstrip(" \t")
        if not content or content.startswith("#"):
            continue
        indent = len(line) - len(content)
        if indent <= parent_indent:
            break
        if indent == parent_indent + ELISA_INDENT_WIDTH:
            children.append((index, content))
    return children


def require_extern_bounds_source_layout(source: str) -> None:
    compact_source = compact(source)
    if any(constant not in compact_source for constant in SOURCE_CONSTANTS):
        raise SystemExit("extern-bounds layout, sentinels, and C parameter tags must use named constants")
    required_constant_uses = (
        "returnEXTERN_BOUNDS_INVALID_PARAMETER_INDEX",
        "new_index.push(EXTERN_BOUNDS_INVALID_PARAMETER_INDEX)",
        "fn_type_line:EXTERN_BOUNDS_NO_FN_TYPE_LINE",
        "fn_type_param_count:EXTERN_BOUNDS_NO_FN_TYPE_PARAM_COUNT",
        "code:mutableu32=EXTERN_BOUNDS_CPART_WHOLE",
        "*EXTERN_BOUNDS_CPART_STRIDE+EXTERN_BOUNDS_CPART_LENGTH",
        "*EXTERN_BOUNDS_CPART_STRIDE+EXTERN_BOUNDS_CPART_POINTER",
        "*EXTERN_BOUNDS_CPART_STRIDE+EXTERN_BOUNDS_CPART_WHOLE",
    )
    if any(use not in compact_source for use in required_constant_uses):
        raise SystemExit("extern-bounds sentinels and C parameter encoding must use their named constants")
    forbidden_magic_expressions = (
        "return-1",
        "arg_count%2",
        "arg_count/2",
        "pair*2",
        "ptr_index<0",
        "len_index<0",
        "ptr_indices.count==0",
        "new_index.push(-1)",
        "fn_type_line:0",
        "fn_type_param_count:0",
        ".u32()*8",
    )
    if any(expression in compact_source for expression in forbidden_magic_expressions):
        raise SystemExit("extern-bounds implementation contains a raw layout, sentinel, or C tag number")

    section = function_section(source, "apply_extern_bounds")
    lines = section.splitlines()
    function_index = next((index for index, line in enumerate(lines)
                           if re.match(r"\s*def apply_extern_bounds\(", line)), None)
    if function_index is None:
        raise SystemExit("extern-bounds rewrite function header is missing")
    function_indent = len(lines[function_index]) - len(lines[function_index].lstrip(" \t"))
    function_children = direct_children(lines, function_index, function_indent)
    if [compact(line) for _, line in function_children] != ["canAbort.Panic,Memory.Allocate:"]:
        raise SystemExit("extern-bounds rewrite steps must remain inside one effect-scoped body")

    can_index = function_children[0][0]
    can_indent = len(lines[can_index]) - len(lines[can_index].lstrip(" \t"))
    can_children = direct_children(lines, can_index, can_indent)
    expected_can_children = [
        "decorators:darray[Ast::Annotation]=parser.pending_decorators",
        "ptr_indices:mutabledarray[i64]=[]",
        "len_indices:mutabledarray[i64]=[]",
        "failed:mutablebool=false",
        "fordecoratorindecorators|parser,ptr_indices,len_indices,failed,arity|:",
        "returniffailedorptr_indices.count==EXTERN_BOUNDS_NO_VALID_PAIRS",
        "forpair_indexin0..<ptr_indices.count|parser,ptr_indices,len_indices|:",
        "kept:mutabledarray[Ast::ExternParam]=[]",
        "new_index:mutabledarray[i64]=[]",
        "foroffsetin0..<arity.usize()|kept,new_index,parser,ptr_indices,len_indices|:",
        "foroffsetin0..<arity.usize()|parser,new_index,ptr_indices,len_indices|:",
        "parser.extern_params<-parser.extern_params.truncate(param_start.usize())",
        "forrowinkept|parser|:",
        "arity<-kept.count.u32()",
    ]
    if [compact(line) for _, line in can_children] != expected_can_children:
        raise SystemExit("extern-bounds validation and early return must precede every rewrite step")

    decorator_index = can_children[4][0]
    decorator_indent = len(lines[decorator_index]) - len(lines[decorator_index].lstrip(" \t"))
    decorator_children = direct_children(lines, decorator_index, decorator_indent)
    expected_decorator_children = [
        "continueifdecorator.name!=\"bounds\"orfailed",
        "ifdecorator.arg_count==EXTERN_BOUNDS_NO_ARGUMENTSordecorator.arg_count%EXTERN_BOUNDS_ARGUMENTS_PER_PAIR!=0:",
        "forpairin0..<(decorator.arg_count/EXTERN_BOUNDS_ARGUMENTS_PER_PAIR)|parser,ptr_indices,len_indices,failed,arity|:",
    ]
    if [compact(line) for _, line in decorator_children] != expected_decorator_children:
        raise SystemExit("failed decorators must stop later bounds pairs before valid indices are recorded")

    pair_index = decorator_children[2][0]
    pair_indent = len(lines[pair_index]) - len(lines[pair_index].lstrip(" \t"))
    pair_children = direct_children(lines, pair_index, pair_indent)
    expected_pair_children = [
        "continueiffailed",
        "ptr_name:sview=parser.annotation_args[decorator.arg_start.usize()+(pair*EXTERN_BOUNDS_ARGUMENTS_PER_PAIR).usize()+EXTERN_BOUNDS_POINTER_ARGUMENT_OFFSET]",
        "len_name:sview=parser.annotation_args[decorator.arg_start.usize()+(pair*EXTERN_BOUNDS_ARGUMENTS_PER_PAIR).usize()+EXTERN_BOUNDS_LENGTH_ARGUMENT_OFFSET]",
        "ptr_index:i64=bounds_param_index(parser,param_start,arity,ptr_name)",
        "len_index:i64=bounds_param_index(parser,param_start,arity,len_name)",
        "ifptr_index==EXTERN_BOUNDS_INVALID_PARAMETER_INDEXorlen_index==EXTERN_BOUNDS_INVALID_PARAMETER_INDEX:",
        "ifptr_index==len_indexorbounds_index_listed(ptr_indices,ptr_index)orbounds_index_listed(len_indices,ptr_index)orbounds_index_listed(ptr_indices,len_index)orbounds_index_listed(len_indices,len_index):",
        "ptr_row:Ast::ExternParam=parser.extern_params[param_start.usize()+ptr_index.usize()]",
        "ifnotptr_row.is_reforptr_row.optional:",
        "len_row:Ast::ExternParam=parser.extern_params[param_start.usize()+len_index.usize()]",
        "iflen_row.is_refornotbounds_type_is_integer(len_row.type_name):",
        "ptr_indices.push(ptr_index)",
        "len_indices.push(len_index)",
    ]
    if [compact(line) for _, line in pair_children] != expected_pair_children:
        raise SystemExit("each bounds pair must pass all direct validation steps before recording indices")


source_text = SOURCE.read_text()
require_extern_bounds_source_layout(source_text)
body = compact(function_section(source_text, "apply_extern_bounds"))
if body.count("failed:mutablebool=false") != 1 or body.count("failed<-false") != 0:
    raise SystemExit("preflight failure state must start false and remain sticky")
if "fordecoratorindecorators|parser,ptr_indices,len_indices,failed,arity|:" not in body or \
        "continueifdecorator.name!=" not in body or "orfailed" not in body:
    raise SystemExit("failed validation must stop processing later bounds decorators")
if "continueiffailed" not in body:
    raise SystemExit("failed validation must stop processing later pairs")

failure_guards = (
    "ifdecorator.arg_count==EXTERN_BOUNDS_NO_ARGUMENTSordecorator.arg_count%EXTERN_BOUNDS_ARGUMENTS_PER_PAIR!=0:",
    "ifptr_index==EXTERN_BOUNDS_INVALID_PARAMETER_INDEXorlen_index==EXTERN_BOUNDS_INVALID_PARAMETER_INDEX:",
    "ifptr_index==len_indexor",
    "ifnotptr_row.is_reforptr_row.optional:",
    "iflen_row.is_refornotbounds_type_is_integer(len_row.type_name):",
)
guard_positions = [body.find(fragment) for fragment in failure_guards]
if any(position < 0 for position in guard_positions) or guard_positions != sorted(guard_positions):
    raise SystemExit("bounds pair failures must be rejected in the checked arity/name/alias/pointer/length order")
if body.count("failed<-true") != len(failure_guards):
    raise SystemExit("every failed bounds validation must set the sticky failure flag exactly once")

for guard in failure_guards:
    start = body.find(guard)
    next_guard = min((p for p in guard_positions if p > start), default=len(body))
    branch = body[start:next_guard]
    if "failed<-true" not in branch or "continue" not in branch:
        raise SystemExit(f"validation branch {guard} must set failed before continuing")

source_lines = function_section(source_text, "apply_extern_bounds").splitlines()
for guard in failure_guards:
    guard_index = next((index for index, line in enumerate(source_lines)
                        if compact(line).startswith(guard)), None)
    if guard_index is None:
        raise SystemExit(f"validation branch {guard} is missing from the source layout")
    guard_indent = len(source_lines[guard_index]) - len(source_lines[guard_index].lstrip(" \t"))
    branch_children = direct_children(source_lines, guard_index, guard_indent)
    compact_children = [compact(line) for _, line in branch_children]
    if (len(compact_children) < 3 or
            not any("enum_annotations.push" in line for line in compact_children[:-2]) or
            compact_children[-2:] != ["failed<-true", "continue"]):
        raise SystemExit(f"validation branch {guard} must directly record an error, set failed, and continue")

if "bounds_type_is_integer(name:sview)->bool:returnmatchname:" not in compact(
        function_section(SOURCE.read_text(), "bounds_type_is_integer")):
    raise SystemExit("length validation must use the closed integer-type classifier")
type_classifier = compact(function_section(SOURCE.read_text(), "bounds_type_is_integer"))
if set(re.findall(r'"([^"]*)"', type_classifier)) != {
        "usize", "isize", "int", "uint", "i8", "i16", "i32", "i64",
        "u8", "u16", "u32", "u64", "uintptr"} or "_:false" not in type_classifier:
    raise SystemExit("bounds length types must use the exact closed integer whitelist")

guard = "returniffailedorptr_indices.count==EXTERN_BOUNDS_NO_VALID_PAIRS"
guard_pos = body.find(guard)
if guard_pos < 0 or body.count(guard) != 1:
    raise SystemExit("signature rewrite must have one early return for failure or an empty valid-pair set")
if body.find("ptr_indices.push(ptr_index)") < guard_positions[-1] or \
        body.find("len_indices.push(len_index)") < guard_positions[-1]:
    raise SystemExit("only fully validated pointer/length pairs may enter the rewrite arrays")
rewrite_markers = (
    "parser.extern_params<-parser.extern_params.truncate(param_start.usize())",
    "parser.extern_params<-parser.extern_params.push(row)",
    "arity<-kept.count.u32()",
)
mutation_positions = [body.find(marker) for marker in rewrite_markers]
if any(position < guard_pos for position in mutation_positions) or any(position < 0 for position in mutation_positions):
    raise SystemExit("the early return must precede every extern parameter or arity mutation")
if any(body.find(marker) < guard_pos for marker in ("kept:mutabledarray[Ast::ExternParam]=[]", "new_index:mutabledarray[i64]=[]")):
    raise SystemExit("rewrite output buffers must not be built before the fail-closed gate")


mutated_guard = source_text.replace(
    "                return if failed or ptr_indices.count == EXTERN_BOUNDS_NO_VALID_PAIRS",
    "                if failed:\n                    return if failed or ptr_indices.count == EXTERN_BOUNDS_NO_VALID_PAIRS",
    1,
)
if mutated_guard == source_text:
    raise SystemExit("could not construct the nested rewrite-gate mutation regression")
mutated_body = compact(function_section(mutated_guard, "apply_extern_bounds"))
legacy_guard_position = mutated_body.find(guard)
legacy_rewrite_positions = [mutated_body.find(marker) for marker in rewrite_markers]
if (legacy_guard_position < 0 or
        any(position < legacy_guard_position for position in legacy_rewrite_positions) or
        any(mutated_body.find(marker) < legacy_guard_position for marker in
            ("kept:mutabledarray[Ast::ExternParam]=[]", "new_index:mutabledarray[i64]=[]"))):
    raise SystemExit("nested rewrite-gate mutation no longer passes the legacy token-order checks")
try:
    require_extern_bounds_source_layout(mutated_guard)
except SystemExit:
    pass
else:
    raise SystemExit("source layout gate accepted the rewrite guard nested under only the failure branch")

positive_names = set(POSITIVE_SHAPES)
negative_names = set(NEGATIVE_SHAPES)
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names:
    raise SystemExit("extern-bounds rewrite proof inventory is incomplete or contains extras")
for path, shapes in ((POSITIVE, POSITIVE_SHAPES), (NEGATIVE, NEGATIVE_SHAPES)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer states its intended fail-closed theorem")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("extern-bounds rewrite proof requires a strict proof build")

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
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert (negative["summary"]["obligations"] ==
        positive["summary"]["obligations"] + OBLIGATIONS_PER_FALSE_CLAIM * len(negative_names))
assert negative["summary"]["proven"] == negative["summary"]["obligations"] - len(negative_names)
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "extern @bounds validation predicates and fail-closed signature rewrite gate",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
