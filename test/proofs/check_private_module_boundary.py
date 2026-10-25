"""Bind private-module visibility proofs to the production semantic helper."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/semantic/private_module_boundary.elisa"
CONSUMER = ROOT / "src/semantic/check_private_member_access.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARSER = ROOT / "src/parser/parser_decl_module.elisa"
SYMBOLS = ROOT / "src/semantic/symbols.elisa"
POSITIVE = HERE / "private_module_boundary.elisa"
NEGATIVE = HERE / "private_module_boundary_rejected.elisa"
CALL_SHAPES = ROOT / "test/repro/private_call_overload_visibility_shapes.elisa"
CALL_SHAPES_SMOKE = ROOT / "test/parity/private_call_overload_visibility_shapes_smoke.sh"
ROOT_OVERLOADS = ROOT / "test/repro/private_call_root_overload_hidden_import.elisa"
ROOT_OVERLOADS_SMOKE = ROOT / "test/parity/private_call_root_overload_hidden_import_smoke.sh"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source_text = SOURCE.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
parser_text = PARSER.read_text()
symbols_text = SYMBOLS.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
call_shapes_text = CALL_SHAPES.read_text()
call_shapes_smoke_text = CALL_SHAPES_SMOKE.read_text()
root_overloads_text = ROOT_OVERLOADS.read_text()
root_overloads_smoke_text = ROOT_OVERLOADS_SMOKE.read_text()

expected_prefix = '''
def prefix_matches(text: sview, prefix: sview) -> bool:
    ensure result == (
        text.len >= prefix.len and
        (forall index in 0..<text.len:
            index >= prefix.len or text[index] == prefix[index]
        )
    )
    return false if text.len < prefix.len
    while index < prefix.len |index: usize = 0, text, prefix|:
        decreases prefix.len - index
        invariant index <= prefix.len and prefix.len <= text.len
        invariant forall checked in 0..<index: text[checked] == prefix[checked]
        return false if text[index] != prefix[index]
        index <- index + 1.usize()
    assert forall checked in 0..<prefix.len:
        text[checked] == prefix[checked]
    return true
'''
expected_within = '''
def within_module(current_module: sview, owner: sview) -> bool can[Abort.Panic]:
    ensure result == (
        current_module == owner or (
            owner.len > 0 and
            current_module.len > owner.len and
            current_module.len - owner.len > MODULE_SEPARATOR_LENGTH and
            prefix_matches(current_module, owner) and
            current_module[owner.len] == ASCII_COLON and
            current_module[owner.len + 1.usize()] == ASCII_COLON
        )
    )
    can Abort.Panic:
        return true if current_module == owner
        false return if owner.len == 0 or current_module.len <= owner.len
        false return if current_module.len - owner.len <= MODULE_SEPARATOR_LENGTH
        false return if not prefix_matches(current_module, owner)
        return current_module[owner.len] == ASCII_COLON and
            current_module[owner.len + 1.usize()] == ASCII_COLON
'''
if "moduleSemanticPrivateModuleBoundary:" not in compact(source_text) or \
        "constASCII_COLON:u8=58" not in compact(source_text) or \
        "constMODULE_SEPARATOR_LENGTH:usize=2" not in compact(source_text):
    raise SystemExit("private-module boundary helper or its exact delimiter constants are missing")
if compact(function_section(source_text, "prefix_matches")) != compact(expected_prefix):
    raise SystemExit("prefix matcher changed without updating its source-bound proof")
if compact(function_section(source_text, "within_module")) != compact(expected_within):
    raise SystemExit("module-boundary predicate changed without updating its source-bound proof")
if consumer_text.count('include "./private_module_boundary.elisa"') != 1:
    raise SystemExit("private-member checker must include the proved module-boundary helper exactly once")
if semantic_text.count('include "./check_private_member_access.elisa"') != 1:
    raise SystemExit("semantic root must include the private-member checker exactly once")
if "pma_prefix_matches" in consumer_text:
    raise SystemExit("duplicate private path-prefix logic must remain removed from the semantic checker")
consumer = compact(function_section(consumer_text, "pma_within_module"))
if consumer != compact('''
def pma_within_module(current_module: sview, owner: sview) -> bool:
    can Abort.Panic:
        return SemanticPrivateModuleBoundary::within_module(current_module, owner)
'''):
    raise SystemExit("production private-member boundary wrapper no longer delegates to the proved helper")
unqualified_owner = compact(function_section(consumer_text, "pma_unqualified_owner"))
unqualified_call_owner = compact(function_section(consumer_text, "pma_unqualified_call_owner"))
private_import_owner = compact(function_section(consumer_text, "pma_unqualified_private_import_owner"))
scope_member = compact(function_section(consumer_text, "pma_report_scope_member"))
if not all(fragment in unqualified_owner for fragment in (
        "pma_has_global_value(table,member)",
        "pma_unqualified_private_import_owner(table,current_module,private_index,annotations,member)",
        "pma_has_public_imported_function_value(table,private_index,annotations,current_module,member,owner)")) or \
        not all(fragment in unqualified_call_owner for fragment in (
        "pma_has_global_non_callable_value(table,member)",
        "pma_unqualified_private_import_owner(table,current_module,private_index,annotations,member)")) or \
        "pma_within_module(current_module,owner)" not in private_import_owner or \
        "pma_within_module(current_module,owner)" not in scope_member:
    raise SystemExit("qualified and unqualified private-member checks must share the proved boundary predicate")

# Parser markers and semantic symbols share declaration-head offsets. Identifier token
# positions are a distinct span and must not be used to recover per-overload visibility.
private_position = compact(function_section(parser_text, "private_member_declaration_position"))
private_record = compact(function_section(parser_text, "record_private_member_if"))
collect_functions = compact(function_section(symbols_text, "collect_range_with_variadics"))
if "head_offset:usize=parser.private_declaration_head_offset()" not in private_position or \
        "returnAst::pos_of_token(token)" not in private_position or \
        "offset:member_position.offset" not in private_record:
    raise SystemExit("private-member annotation must preserve the parser's declaration-head offset")
if "Decl.Func(name,params,return_type,body,effects,decorators,line)" not in collect_functions or \
        "SymbolKind.Func,line.line,required" not in collect_functions or \
        "line.offset,function_pos" not in collect_functions:
    raise SystemExit("function symbols must retain the declaration-head offset from the parsed function position")

# Overload visibility must be tied to the exact private declaration. Calls may skip a
# spelling-only private report only when a visible sibling can win Core's call ranking
# and every exact private candidate is ineligible, incompatible, or outranked under the
# subset this checker can prove; unknown call shapes remain fail-closed.
private_index_build = compact(function_section(consumer_text, "pma_build_index"))
private_symbol_marker = compact(function_section(consumer_text, "pma_symbol_has_private_marker"))
public_call_sibling_rank = compact(function_section(consumer_text, "pma_public_call_sibling_rank"))
private_candidate_rank = compact(function_section(consumer_text, "pma_private_candidate_excluded_by_public_rank"))
core_arity_filter = compact(function_section(consumer_text, "pma_symbol_core_accepts_receiver_arity"))
private_call_exclusion = compact(function_section(consumer_text, "pma_private_call_overloads_excluded"))
global_value_lookup = compact(function_section(consumer_text, "pma_has_global_value"))
global_non_callable_lookup = compact(function_section(consumer_text, "pma_has_global_non_callable_value"))
bare_owner_lookup = compact(function_section(consumer_text, "pma_unqualified_owner"))
call_owner_lookup = compact(function_section(consumer_text, "pma_unqualified_call_owner"))
private_import_owner_lookup = compact(function_section(consumer_text, "pma_unqualified_private_import_owner"))
public_imported_value = compact(function_section(consumer_text, "pma_has_public_imported_function_value"))
private_import_visibility = compact(function_section(consumer_text, "pma_private_imported_module_member_visible"))
public_import_visibility = compact(function_section(consumer_text, "pma_public_imported_module_member_visible"))
imported_member_visibility = compact(function_section(consumer_text, "pma_imported_module_member_visible"))
candidate_module_visibility = compact(function_section(consumer_text, "pma_unqualified_candidate_module_visible"))
selective_import_status = compact(function_section(consumer_text, "pma_selective_import_target_status"))
using_member_registration = compact(function_section(consumer_text, "pma_selective_annotation_is_using_member"))
import_scope_visibility = compact(function_section(consumer_text, "pma_import_scope_visible"))
argument_type_probe = compact(function_section(consumer_text, "pma_argument_type_name"))
call_target_normalizer = compact(function_section(consumer_text, "pma_normalize_call_callee"))
call_index_walker = compact(function_section(consumer_text, "pma_report_call_callee_indices"))
private_report = compact(function_section(consumer_text, "pma_report"))
private_index_init = compact(consumer_text)
if not all(fragment in private_index_build for fragment in (
        "index.declaration_offsets.push(annotation.offset)",
        "index.modules.push(module_annotation.name)")) or not all(fragment in private_symbol_marker for fragment in (
        "index.declaration_offsets[index_position]==symbol.offset",
        "index.names[index_position]==symbol.name",
        "index.modules[index_position]==symbol.module_owner")):
    raise SystemExit("private overload visibility must match the parser's declaration-position marker to its exact symbol")
if not all(fragment in private_call_exclusion for fragment in (
        'returnfalseifanyargument_nameinargument_nameswhereargument_name!=""',
        "pma_public_call_sibling_rank(index,table,annotations,owner,member,current_module,unqualified_call,arguments,bound,bound_types)",
        "pma_symbol_core_accepts_receiver_arity(table,symbol,arguments.count)",
        "pma_private_candidate_excluded_by_public_rank(table,annotations,symbol,public_rank.rank,actual_type)",
        "returnprivate_candidates>0.usize()andall_excluded")) or not all(fragment in core_arity_filter for fragment in (
        "symbol.arity_max==4294967295",
        "table.function_param_has_default[row]",
        "symbol.arity_max==argument_count.u32()")):
    raise SystemExit("private-call suppression must match Core's coarse arity filter and remain fail-closed for named or unknown calls")
if not all(fragment in global_value_lookup for fragment in (
        'symbol.kind!=SymbolKind.Moduleandsymbol.module_owner==""',
        "returnfalse")) or not all(fragment in global_non_callable_lookup for fragment in (
        'symbol.kind!=SymbolKind.Moduleandsymbol.kind!=SymbolKind.Funcandsymbol.module_owner==""',
        "returnfalse")):
    raise SystemExit("global-name shadowing must use explicit root ownership, not counts that conflate imported overloads")
if not all(fragment in bare_owner_lookup for fragment in (
        "pma_has_global_value(table,member)",
        "pma_unqualified_private_import_owner(table,current_module,private_index,annotations,member)",
        "pma_has_public_imported_function_value(table,private_index,annotations,current_module,member,owner)")) or not all(fragment in call_owner_lookup for fragment in (
        "pma_has_global_non_callable_value(table,member)",
        "pma_unqualified_private_import_owner(table,current_module,private_index,annotations,member)")) or \
        "pma_has_global_value" in call_owner_lookup or "pma_has_global_non_callable_value" in bare_owner_lookup or \
        "pma_is_private" not in private_import_owner_lookup:
    raise SystemExit("bare global functions must shadow values while call lookup still checks imported private overloads")
if not all(fragment in public_imported_value for fragment in (
        "symbol.kind!=SymbolKind.Func",
        "pma_module_owns(table,symbol.module_owner,member)",
        "pma_unqualified_candidate_module_visible(index,annotations,current_module,symbol.module_owner,member)",
        "notpma_symbol_has_private_marker(index,symbol)")) or "pma_has_public_imported_function_value(table,private_index,annotations,current_module,member,owner)" not in bare_owner_lookup:
    raise SystemExit("a visible public callable import must keep a same-name private wildcard function from blocking its value")
if "pma_public_imported_module_member_visible(index,annotations,current_module,owner,member)" not in imported_member_visibility or not all(fragment in candidate_module_visibility for fragment in (
        "pma_imported_module_member_visible(index,annotations,current_module,candidate_module,member)",
        "pma_is_private(index,owner,segment)",
        "notpma_within_module(current_module,owner)")):
    raise SystemExit("public import alternatives must be visible in scope and outside every private module path")
if not all(fragment in private_import_visibility for fragment in (
        "__binding_wildcard_import",
        "pma_selective_import_target_status(annotations,current_module,owner,member)",
        "target.foundand(nottarget.knownortarget.first)")) or not all(fragment in public_import_visibility for fragment in (
        "__binding_wildcard_import",
        "target.foundandtarget.knownandtarget.first")) or not all(fragment in selective_import_status for fragment in (
        "member_annotation.offset",
        "member_annotation.module",
        "source_annotation.name==owner",
        "candidate_is_using",
        "known_order")) or not all(fragment in using_member_registration for fragment in (
        'annotation.name=="__using_member"',
        "annotation.offset==member_annotation.offset")) or "returntrueifimport_scope==\"\"" not in import_scope_visibility:
    raise SystemExit("import visibility must preserve root/ancestor scope, first selective target, and Core's using-member registration order")
if not all(fragment in public_call_sibling_rank for fragment in (
        "pma_argument_type_name(arguments[0],bound,bound_types)",
        "pma_symbol_has_private_marker(index,symbol)",
        "ifnotunqualified_call:continueifsymbol.module_owner!=owner",
        "pma_unqualified_candidate_module_visible(index,annotations,current_module,symbol.module_owner,member)",
        "first_parameter.name==actual_type",
        "actual_type==\"int\"and(first_parameter.kind==SemTypeKind.Intorfirst_parameter.kind==SemTypeKind.Char)",
        "pma_generic_parameter_identity(annotations,first_parameter.name,symbol)")) or not all(fragment in candidate_module_visibility for fragment in (
        'candidate_module==""orpma_within_module(current_module,candidate_module)',
        "pma_imported_module_member_visible(index,annotations,current_module,candidate_module,member)")) or not all(fragment in private_candidate_rank for fragment in (
        'actual_type=="bool"',
        "public_rank>0.usize()",
        "pma_generic_parameter_identity(annotations,first_parameter.name,symbol)")):
    raise SystemExit("private-call suppression must prove exact public formals outrank private generic candidates while ties stay fail-closed")
if not all(fragment in argument_type_probe for fragment in (
        "Expr.IntLit(_,_)",
        'return"int"',
        "Expr.FloatLit(_,_)",
        'return"f64"')):
    raise SystemExit("PMA must recognize Core's untyped integer and default float receiver types before suppressing a private generic winner")
if not all(fragment in call_target_normalizer for fragment in (
        "Expr.Paren(inner,_)",
        "Expr.Index(object,_,_)ifpma_is_private_function_target(object,current_module,index,annotations,table,bound)",
        "Expr.IndexN(object,_,_)ifpma_is_private_function_target(object,current_module,index,annotations,table,bound)")) or not all(fragment in call_index_walker for fragment in (
        "Expr.Index(object,argument,_)",
        "Expr.IndexN(object,arguments,_)",
        "pma_report(argument,current_module,index,annotations,table,bound,bound_types)")):
    raise SystemExit("parenthesized and explicit-generic private call targets must normalize without dropping index-argument checks")
bare_call = private_report.index("Expr.Ident(callee_name,callee_line):")
qualified_call = private_report.index("Expr.Scope(base,callee_name,callee_line):")
qualified_body = private_report[qualified_call:]
qualified_order = (
    "pma_report(base,current_module,index,annotations,table,bound,bound_types)",
    "owner:sview@source=pma_scope_owner(index,table,base,callee_name)",
    "pma_private_call_overloads_excluded(index,table,annotations,owner,callee_name,current_module,false,arguments,argument_names,bound,bound_types)",
    "table.diagnostics<-table.diagnostics.push(Diagnostic{kind:DiagnosticKind.PrivateMemberAccess,name:callee_name",
)
if bare_call > qualified_call or not all(fragment in private_report for fragment in (
        "normalized_callee:Ast::Expr=pma_normalize_call_callee(callee,current_module,index,annotations,table,bound)",
        "matchnormalized_callee:",
        "pma_unqualified_call_owner(table,current_module,index,annotations,bound,callee_name)",
        "pma_private_call_overloads_excluded(index,table,annotations,owner,callee_name,current_module,true,arguments,argument_names,bound,bound_types)",
        "pma_report_call_callee_indices(callee,current_module,index,annotations,table,bound,bound_types)ifnormalized_callee_is_path")) or \
        not all(fragment in qualified_body for fragment in qualified_order) or \
        sorted(qualified_body.index(fragment) for fragment in qualified_order) != [qualified_body.index(fragment) for fragment in qualified_order] or \
        "notpma_within_module(current_module,owner)andnotprivate_candidates_excluded" not in qualified_body:
    raise SystemExit("call checking must normalize private call forms, preserve private base barriers, and check selected overload families")
if "declaration_offsets:mutabledarray[u32]" not in private_index_init or \
        "declaration_offsets:[]" not in private_index_init:
    raise SystemExit("private declaration offsets must be initialized alongside the member index")
if not all(fragment in call_shapes_text for fragment in (
        "return (Provider::dispatch)(value)",
        "return Provider::dispatch[bool](value)",
        "return dispatch(value)",
        "return dispatch[bool](value)",
        "return Provider::sealed(value)",
        "return BroadProvider::prefer(value)",
        "return LiteralProvider::choose(7)",
        "return wrap(fetch)",
        "return wrap(retrieve)",
        "def public_concrete_over_private_generic(value: i64)",
        "def public_concrete_literal_winner()",
        "def public_selective_function_value()")) or not all(fragment in call_shapes_smoke_text for fragment in (
        'private_call_overload_visibility_shapes.elisa',
        '[[ $(grep -cF \'is private to module\' <<< "$stage0_output") == 1 ]]',
        '[[ $(grep -cF \'is private to module\' <<< "$stage1_output") == 1 ]]')):
    raise SystemExit("call-shape fixture must cover parenthesized, explicit-generic, and private-only visibility controls")

if not all(fragment in root_overloads_text for fragment in (
        "def choose(value: i64)",
        "def prefer[T](value: T)",
        "def choose[T](value: T)",
        "def prefer(value: bool)",
        "return choose(value)",
        "return prefer(value)",
        "def local_rank[T](value: T)",
        "from Provider import local_rank",
        "def local_rank(value: bool)",
        "def local_concrete_wins(value: bool)",
        "return local_rank(value)")) or not all(fragment in root_overloads_smoke_text for fragment in (
        'private_call_root_overload_hidden_import.elisa',
        'grep -q \'^P 0$\' <<< "$stage1_output"',
        'is private to module')):
    raise SystemExit("root/local overload fixture must bind generic and concrete visible winners against private imported candidates")

if 'include "../../src/semantic/private_module_boundary.elisa"' not in positive_text or \
        'include "./private_module_boundary.elisa"' not in negative_text:
    raise SystemExit("boundary proof fixtures must include the production helper")
positive_names = {
    "prefix_classifier_matches_its_bytewise_spec",
    "module_containment_classifier_matches_exact_separator_spec",
    "owner_and_descendant_are_inside_private_boundary",
    "similar_prefix_and_parent_are_outside_private_boundary",
    "empty_owner_only_contains_the_identical_empty_path",
}
negative_names = {
    "false_claim_similar_textual_prefix_is_a_child",
    "false_claim_parent_module_is_inside_child_boundary",
    "false_claim_separator_without_child_is_a_descendant",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("private-module boundary proof inventory changed")

expected_positive_claims = {
    "prefix_classifier_matches_its_bytewise_spec": "SemanticPrivateModuleBoundary::prefix_matches(text,prefix)==(text.len>=prefix.lenand(forallindexin0..<text.len:index>=prefix.lenortext[index]==prefix[index]))",
    "module_containment_classifier_matches_exact_separator_spec": "SemanticPrivateModuleBoundary::within_module(current_module,owner)==(current_module==owneror(owner.len>0andcurrent_module.len>owner.lenandcurrent_module.len-owner.len>SemanticPrivateModuleBoundary::MODULE_SEPARATOR_LENGTHandSemanticPrivateModuleBoundary::prefix_matches(current_module,owner)andcurrent_module[owner.len]==SemanticPrivateModuleBoundary::ASCII_COLONandcurrent_module[owner.len+1.usize()]==SemanticPrivateModuleBoundary::ASCII_COLON))",
    "owner_and_descendant_are_inside_private_boundary": 'SemanticPrivateModuleBoundary::within_module("A::Paint","A::Paint")andSemanticPrivateModuleBoundary::within_module("A::Paint::Brush","A::Paint")andSemanticPrivateModuleBoundary::within_module("A::Paint::Brush::Wet","A::Paint")',
    "similar_prefix_and_parent_are_outside_private_boundary": 'notSemanticPrivateModuleBoundary::within_module("A::Painter::Brush","A::Paint")andnotSemanticPrivateModuleBoundary::within_module("A","A::Paint")andnotSemanticPrivateModuleBoundary::within_module("A::Paint::","A::Paint")',
    "empty_owner_only_contains_the_identical_empty_path": 'SemanticPrivateModuleBoundary::within_module("","")andnotSemanticPrivateModuleBoundary::within_module("A","")',
}
expected_negative_claims = {
    "false_claim_similar_textual_prefix_is_a_child": 'SemanticPrivateModuleBoundary::within_module("A::Painter","A::Paint")',
    "false_claim_parent_module_is_inside_child_boundary": 'SemanticPrivateModuleBoundary::within_module("A","A::Paint")',
    "false_claim_separator_without_child_is_a_descendant": 'SemanticPrivateModuleBoundary::within_module("A::Paint::","A::Paint")',
}
for name, claim in expected_positive_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive proof {name} no longer establishes its source-bound claim")
for name, claim in expected_negative_claims.items():
    section = compact(function_section(negative_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"false-claim control {name} no longer asserts the rejected claim")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("private-module boundary proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, CONSUMER, SEMANTIC,
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
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "private-module boundary proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "private-module boundary proof inputs changed during admission"
