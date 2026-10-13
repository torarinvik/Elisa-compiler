"""Replay source-bound dense NodeKey root and origin-row proofs."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
HERE = Path(__file__).resolve().parent
POSITIVE = HERE / "dense_node_key_root.elisa"
NEGATIVE = HERE / "dense_node_key_root_rejected.elisa"
SOURCE = ROOT / "src/semantic/check_dense_node_key_root.elisa"
CONTAINER_OPS = ROOT / "src/backend/codegen_container_ops.elisa"
CODEGEN_CALLS = ROOT / "src/backend/codegen_stmt_expr_calls.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

POSITIVE_NAMES = {
    "dense_node_key_root_mismatch",
    "same_dense_key_store_path_is_accepted",
    "a_different_store_root_is_rejected",
    "a_different_member_on_the_same_root_is_rejected",
    "root_node_table_handle_is_exempt",
    "dense_key_origin_counts_remain_aligned_after_one_append",
    "found_dense_key_slot_is_in_bounds_for_both_origin_rows",
    "latest_dense_key_slot_model",
    "newest_recorded_dense_key_origin_wins",
}
NEGATIVE_NAMES = {
    "a_different_store_root_is_accepted",
    "an_exact_store_path_is_rejected",
    "a_root_node_table_key_is_reported_as_mismatched",
    "synchronized_origin_appends_can_diverge",
    "a_found_dense_key_slot_can_exceed_an_origin_row",
    "an_older_dense_key_origin_wins_over_the_latest",
    "a_present_dense_key_origin_is_reported_missing",
}


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


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


def source_errors(source_text: str, container_ops_text: str, codegen_calls_text: str) -> list[str]:
    errors = []
    try:
        path = compact(function_section(source_text, "dense_store_path"))
        key_slot = compact(function_section(source_text, "dense_key_slot"))
        name_exists = compact(function_section(source_text, "dense_name_exists"))
        record = compact(function_section(source_text, "note_dense_key"))
        initializer = compact(function_section(source_text, "dense_node_table_initializer"))
        check = compact(function_section(source_text, "check_dense_key_expression"))
        walk = compact(function_section(source_text, "walk_dense_key_statements"))
        declarations = compact(function_section(source_text, "check_dense_key_declarations"))
        entry = compact(function_section(source_text, "check_dense_node_key_root"))
        push = compact(function_section(container_ops_text, "emit_darray_push"))
        push_call_dispatch = compact(function_section(codegen_calls_text, "emit_statement_expr_calls"))
    except SystemExit as error:
        return [str(error)]

    path_steps = (
        "Expr.Ident(name,line):root<-name",
        "Expr.Field(Expr.Ident(name,ident_line),field,field_line):root<-namemember<-field",
        "Expr.Paren(inner,line):dense_store_path(inner,root,member)",
    )
    path_positions = [path.find(fragment) for fragment in path_steps]
    if any(position < 0 for position in path_positions) or path_positions != sorted(path_positions):
        errors.append("dense-store path recognition no longer records a root and one direct field through parentheses")

    key_slot_steps = (
        "whileindex>0|index:usize=names.count|:",
        "index<-index-1",
        "index.int()returnifnames[index]==wanted",
        "return-1",
    )
    key_slot_positions = [key_slot.find(fragment) for fragment in key_slot_steps]
    if any(position < 0 for position in key_slot_positions) or key_slot_positions != sorted(key_slot_positions):
        errors.append("dense-key origin lookup no longer searches backward for the most recent recorded name")
    if "fornameinnames:true" not in name_exists or "returnfalse" not in name_exists:
        errors.append("NodeTable origin lookup no longer uses exact name membership")

    record_steps = (
        'ifcallee_name=="dense_key"andarguments.count>=2:',
        "dense_store_path(arguments[1],root,member)",
        "ifroot!=\"\":",
        "key_names.push(name)",
        "store_roots.push(root)",
        "store_members.push(member)",
    )
    record_positions = [record.find(fragment) for fragment in record_steps]
    if any(position < 0 for position in record_positions) or record_positions != sorted(record_positions):
        errors.append("dense-key registration no longer stores the source root and member in aligned rows")
    for fragment in ("key_names.push(name)", "store_roots.push(root)", "store_members.push(member)"):
        if record.count(fragment) != 1:
            errors.append(f"dense-key registration must append exactly one row to {fragment.split('.')[0]}")
    all_source = compact(source_text)
    for fragment in ("key_names.push(name)", "store_roots.push(root)", "store_members.push(member)"):
        if all_source.count(fragment) != 1:
            errors.append(f"dense-key source now has another write to parallel origin rows: {fragment}")

    initializer_steps = (
        'Expr.Call(Expr.IndexN(Expr.Ident(name,ident_line),type_arguments,index_line),arguments,argument_names,line):',
        'Expr.Call(Expr.Ident(name,ident_line),arguments,argument_names,line):',
    )
    initializer_positions = [initializer.find(fragment) for fragment in initializer_steps]
    if (any(position < 0 for position in initializer_positions) or initializer_positions != sorted(initializer_positions)
            or initializer.count('returnname=="node_table_fill"') != 2):
        errors.append("NodeTable exemption no longer recognizes exactly the node_table_fill initializer spellings")

    check_steps = (
        "Expr.Index(store,Expr.Ident(key_name,key_line),line):",
        "slot:int=dense_key_slot(key_names,key_name)",
        "whilehas_key|has_key:bool=slot>=0,table|:",
        "dense_store_path(store,root,member)",
        "mismatched:bool=root!=store_roots[slot.usize()]ormember!=store_members[slot.usize()]",
        "is_node_table:bool=dense_name_exists(node_tables,root)andmember==\"\"",
        'table.diagnostics<-table.diagnostics.push(Diagnostic{kind:DiagnosticKind.DenseNodeKeyRootMismatch,name:key_name,line:line.line,expected:"",actual:""})ifroot!=""andmismatchedandnotis_node_table',
    )
    check_positions = [check.find(fragment) for fragment in check_steps]
    if any(position < 0 for position in check_positions) or check_positions != sorted(check_positions):
        errors.append("dense-key indexing no longer reports unequal roots or fields, subject to the NodeTable exception")

    if ('Stmt.VarDecl(name,type_expression,value,line):'
            'note_dense_key(name,value,key_names,store_roots,store_members)'
            'node_tables.push(name)ifdense_node_table_initializer(value)'
            'table<-check_dense_key_expression(value,key_names,store_roots,store_members,node_tables,table)') not in walk:
        errors.append("dense-key and NodeTable rows are no longer collected from local initializers before checking their values")
    if ('Decl.Func(name,params,return_type,body,effects,decorators,line):'
            'key_names:mutabledarray[sview]=[]'
            'store_roots:mutabledarray[sview]=[]'
            'store_members:mutabledarray[sview]=[]'
            'node_tables:mutabledarray[sview]=[]'
            'table<-walk_dense_key_statements(body,key_names,store_roots,store_members,node_tables,table)') not in declarations:
        errors.append("dense-key origin rows are no longer scoped per function body")
    if "table<-check_dense_key_declarations(declarations,table)" not in entry:
        errors.append("the semantic dense NodeKey root pass no longer visits declarations")

    push_steps = (
        'needed:LLVMValueRef=LLVMBuildAdd(builder,count,LLVMConstInt(int64_type,1,0),"push.needed")',
        "indices:mutabledarray[LLVMValueRef]=[count]",
        'LLVMBuildGEP2(builder,llvm_type_of(element_type,structs,ctx),items,indices_pointer,1,"push.slot")',
        "_=LLVMBuildStore(builder,pushed_value,slot)",
        "darray_store_size(builder,needed,count_pointer,ctx,structs.target.target_pointer_bits)",
        "returntrue",
    )
    push_positions = [push.find(fragment) for fragment in push_steps]
    if any(position < 0 for position in push_positions) or push_positions != sorted(push_positions):
        errors.append("darray.push no longer writes at the old count and commits exactly count + 1 on success")
    push_call_branch_text = 'ifpush_type.kind==TypeKind.DArrayandpush_method=="push"andpush_arguments.count==1:'
    push_call_start = push_call_dispatch.find(push_call_branch_text)
    push_call_branch = push_call_dispatch[push_call_start:] if push_call_start >= 0 else ""
    if ('emit_darray_push(push_slot,push_type,push_arguments[0],local_scope,fns,structs,generics,push_growth_runtime,m,ctx,builder)' not in push_call_branch
            or 'returnEmitStatus.Open' not in push_call_branch):
        errors.append("statement-position darray.push no longer routes through the count-incrementing emitter")
    return errors


def validate_model() -> None:
    positive = POSITIVE.read_text()
    negative = NEGATIVE.read_text()
    formula = ('store_root!=""and(store_root!=key_rootorstore_member!=key_member)and'
               'not(store_root_is_node_tableandstore_member=="")')
    body = compact(function_section(positive, "dense_node_key_root_mismatch"))
    if f"ensureresult==({formula})" not in body or f"return{formula}" not in body:
        raise SystemExit("dense NodeKey mismatch model no longer matches the source decision")

    expected = {
        "same_dense_key_store_path_is_accepted": "requireskey_root==store_rootandkey_member==store_memberandstore_root!=\"\"",
        "a_different_store_root_is_rejected": "requiresnot(store_root_is_node_tableandstore_member==\"\")",
        "a_different_member_on_the_same_root_is_rejected": "requiresnot(store_root_is_node_tableandstore_member==\"\")",
        "root_node_table_handle_is_exempt": "returndense_node_key_root_mismatch(key_root,key_member,store_root,\"\",true)",
    }
    for name, fragment in expected.items():
        if fragment not in compact(function_section(positive, name)):
            raise SystemExit(f"dense NodeKey proof {name} lost its required path conditions")

    transition = compact(function_section(positive, "dense_key_origin_counts_remain_aligned_after_one_append"))
    if ("requireskey_count==root_countandroot_count==member_count" not in transition or
            "requireskey_count<18446744073709551615.u64()" not in transition or
            "key_after:u64=key_count+1.u64()" not in transition or
            "root_after:u64=root_count+1.u64()" not in transition or
            "member_after:u64=member_count+1.u64()" not in transition or
            "returnkey_after==root_afterandroot_after==member_after" not in transition):
        raise SystemExit("dense-key parallel-table transition theorem no longer models one successful append per table")
    slot_bound = compact(function_section(positive, "found_dense_key_slot_is_in_bounds_for_both_origin_rows"))
    if ("requiresslot<key_count" not in slot_bound or
            "requireskey_count==root_countandroot_count==member_count" not in slot_bound or
            "returnslot<root_countandslot<member_count" not in slot_bound):
        raise SystemExit("dense-key slot bound no longer follows from parallel origin-row lengths")

    latest = compact(function_section(positive, "latest_dense_key_slot_model"))
    for fragment in (
        "ensuresresult.foundimpliesresult.index<names.count",
        "ensuresresult.foundimpliesnames[result.index]==wanted",
        "ensuresresult.foundimplies(foralllaterinresult.index+1.usize()..<names.count:names[later]!=wanted)",
        "ensuresnotresult.foundimplies(forallcandidatein0..<names.count:names[candidate]!=wanted)",
        "invariantforalllaterinindex..<names.count:names[later]!=wanted",
        "index<-index-1.usize()",
        "return(true,index)ifnames[index]==wanted",
    ):
        if fragment not in latest:
            raise SystemExit("dense-key latest-origin lookup model lost its reverse-scan proof contract")
    rebound = compact(function_section(positive, "newest_recorded_dense_key_origin_wins"))
    if ('names:darray[sview]=["key","key"]' not in rebound or
            'roots:darray[sview]=[old_root,new_root]' not in rebound or
            'latest_dense_key_slot_model(names,"key")' not in rebound or
            'returnselected.index==1.usize()androots[selected.index]==new_root' not in rebound):
        raise SystemExit("dense-key rebinding model no longer checks that the latest same-name origin wins")

    if declarations(POSITIVE) != POSITIVE_NAMES:
        raise SystemExit("dense NodeKey positive proof inventory changed")
    if declarations(NEGATIVE) != NEGATIVE_NAMES or 'include "./dense_node_key_root.elisa"' not in negative:
        raise SystemExit("dense NodeKey false-claim inventory changed")
    false_claims = {
        "a_different_store_root_is_accepted": 'returnnotdense_node_key_root_mismatch("left","","right","",false)',
        "an_exact_store_path_is_rejected": 'returndense_node_key_root_mismatch("left","field","left","field",false)',
        "a_root_node_table_key_is_reported_as_mismatched": 'returndense_node_key_root_mismatch("left","","node_table","",true)',
        "synchronized_origin_appends_can_diverge": 'returnkey_after!=root_afterorroot_after!=member_after',
        "a_found_dense_key_slot_can_exceed_an_origin_row": 'returnslot>=root_countorslot>=member_count',
        "an_older_dense_key_origin_wins_over_the_latest": 'returnselected.foundandselected.index==0.usize()',
        "a_present_dense_key_origin_is_reported_missing": 'returnnotselected.found',
    }
    for name, expression in false_claims.items():
        if "ensureresult==true" not in compact(function_section(negative, name)) or expression not in compact(function_section(negative, name)):
            raise SystemExit(f"dense NodeKey false-claim control {name} no longer contradicts the source rule")


text = SOURCE.read_text()
container_ops = CONTAINER_OPS.read_text()
codegen_calls = CODEGEN_CALLS.read_text()
errors = source_errors(text, container_ops, codegen_calls)
if errors:
    raise SystemExit("\n".join(errors))
validate_model()

# Mutation controls ensure the source binding rejects both weakening the mismatch
# disjunction and reversing the report guard.
mutated_path = text.replace(
    "mismatched: bool = root != store_roots[slot.usize()] or member != store_members[slot.usize()]",
    "mismatched: bool = root != store_roots[slot.usize()] and member != store_members[slot.usize()]",
    1,
)
if mutated_path == text or not source_errors(mutated_path, container_ops, codegen_calls):
    raise SystemExit("source gate failed to reject requiring both root and member to differ")
mutated_guard = text.replace("and not is_node_table", "and is_node_table", 1)
if mutated_guard == text or not source_errors(mutated_guard, container_ops, codegen_calls):
    raise SystemExit("source gate failed to reject reversing the NodeTable exception")

mutated_push = container_ops.replace(
    'needed: LLVMValueRef = LLVMBuildAdd(builder, count, LLVMConstInt(int64_type, 1, 0), "push.needed")',
    'needed: LLVMValueRef = LLVMBuildAdd(builder, count, LLVMConstInt(int64_type, 2, 0), "push.needed")',
    1,
)
if mutated_push == container_ops or not source_errors(text, mutated_push, codegen_calls):
    raise SystemExit("source gate failed to reject a darray.push that advances its count by more than one")

mutated_origin_rows = text.replace("store_members.push(member)", "pass", 1)
if mutated_origin_rows == text or not source_errors(mutated_origin_rows, container_ops, codegen_calls):
    raise SystemExit("source gate failed to reject dropping one of the parallel dense-key origin appends")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("dense NodeKey root proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), POSITIVE, NEGATIVE, SOURCE, CONTAINER_OPS, CODEGEN_CALLS,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert positive == run(POSITIVE)[1], "dense NodeKey root proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"]: row["kind"] for row in negative["findings"]} == {
    name: "ensure-unproven" for name in NEGATIVE_NAMES
}
assert negative["summary"]["unproven"] == len(NEGATIVE_NAMES)
assert negative == run(NEGATIVE)[1], "dense NodeKey false-claim report changed across repeated runs"
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "dense NodeKey proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "recorded dense NodeKey path decision and origin-row alignment/bounds",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
