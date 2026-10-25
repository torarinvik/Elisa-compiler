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
UNKNOWN_STATIC_IMPORT = ROOT / "test/repro/private_call_static_unknown_import.elisa"
UNKNOWN_STATIC_IMPORT_SMOKE = ROOT / "test/parity/private_call_static_unknown_import_smoke.sh"
STATIC_TRUE_IMPORT_CONTROL = ROOT / "test/repro/private_call_static_true_import_control.elisa"
STATIC_TRUE_IMPORT_CONTROL_SMOKE = ROOT / "test/parity/private_call_static_true_import_control_smoke.sh"

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
unknown_static_import_text = UNKNOWN_STATIC_IMPORT.read_text()
unknown_static_import_smoke_text = UNKNOWN_STATIC_IMPORT_SMOKE.read_text()

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
named_type_spelling_unique = compact(function_section(consumer_text, "pma_named_type_spelling_is_unique"))
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
static_if_condition_value = compact(function_section(consumer_text, "pma_static_if_condition_value"))
static_if_named_constant_value = compact(function_section(consumer_text, "pma_static_if_named_constant_value"))
static_if_row_selection = compact(function_section(consumer_text, "pma_static_if_row_selection"))
import_branch_selection = compact(function_section(consumer_text, "pma_import_branch_selection"))
import_annotation_branch_selection = compact(function_section(consumer_text, "pma_import_annotation_branch_selection"))
inactive_import_branch = compact(function_section(consumer_text, "pma_import_annotation_in_inactive_static_branch"))
uncertain_import_row = compact(function_section(consumer_text, "pma_import_row_branch_uncertain"))
active_import_annotations = compact(function_section(consumer_text, "pma_active_import_annotations"))
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
        'annotation.name=="__binding_wildcard_import"',
        "pma_selective_import_target_status(annotations,current_module,owner,member)",
        "target.foundand(nottarget.knownortarget.first)")) or not all(fragment in public_import_visibility for fragment in (
        'annotation.name=="__binding_wildcard_import"',
        "pma_import_row_branch_uncertain(annotations,annotation.owner,annotation.name,annotation.module,annotation.line,annotation.offset)",
        "target.foundandtarget.knownandtarget.first")) or not all(fragment in selective_import_status for fragment in (
        "member_annotation.offset",
        "member_annotation.module",
        "source_annotation.name==owner",
        "candidate_is_using",
        'known_order<-falseifpma_import_row_branch_uncertain(annotations,"__from_member",member_annotation.name,member_annotation.module,member_annotation.line,member_annotation.offset)',
        "known_order")) or not all(fragment in using_member_registration for fragment in (
        'annotation.name=="__using_member"',
        "annotation.offset==member_annotation.offset")) or "returntrueifimport_scope==\"\"" not in import_scope_visibility:
    raise SystemExit("import visibility must preserve root/ancestor scope, first selective target, and Core's using-member registration order")
if not all(fragment in static_if_condition_value for fragment in (
        "Expr.BoolLit(value,_)",
        "Expr.Ident(name,_)",
        "ga_static_if_target_constant(name)",
        "ga_static_if_target_predicate(name)",
        "pma_static_if_named_constant_value(name,current_module,table,depth+1)",
        "return(false,0)ifdepth>=64",
        "Expr.Unary(operator,operand,_)")) or not static_if_condition_value.endswith("_:passreturn(false,0)") or not all(fragment in static_if_named_constant_value for fragment in (
        "return(false,0)ifdepth>=64",
        "table.immutable_const_values",
        "table.immutable_const_names",
        "table.immutable_const_rows",
        "symbol.module_owner")) or not all(fragment in static_if_row_selection for fragment in (
        "file.static_if_lines",
        "file.static_if_kinds",
        "file.static_if_depths",
        "StaticIfBranch::Kind.ChainHead",
        "StaticIfBranch::Kind.Fallback",
        "pma_static_if_condition_value(file.static_if_conds[row],current_module,table,0)",
        "return(false,false)ifnotcondition.known",
        "condition.knownandcondition.value!=0",
        "return(true,false)ifrow==branch_row")) or not all(fragment in static_if_named_constant_value for fragment in (
        "selected_scope_length",
        "symbol.module_owner.len>selected_scope_length",
        "symbol.module_owner.len==selected_scope_length",
        "return(false,0)",
        "table.immutable_const_values[selected_row]")) or not all(fragment in import_branch_selection for fragment in (
        'marker.owner!=marker_owner',
        'marker.name!=marker_name',
        'marker.detail_name!=marker_detail',
        'pma_static_if_row_selection(file,marker.identity_id.usize(),module,table)',
        'marker.identity_id!=4294967295')) or not all(fragment in import_annotation_branch_selection for fragment in (
        'annotation.name=="__binding_wildcard_import"',
        '"__binding_wildcard_import_static_branch"',
        '"__from_member_static_branch"',
        '"__static_if_branch"',
        'annotation.owner=="__private_member"',
        '"__private_member_static_branch"')) or not all(fragment in inactive_import_branch for fragment in (
        'branch.knownandnotbranch.active')) or not all(fragment in uncertain_import_row for fragment in (
        'marker.owner=="__pma_unknown_static_import"',
        'marker.name==import_owner',
        'marker.detail_name==import_name')) or not all(fragment in active_import_annotations for fragment in (
        'pma_import_annotation_branch_selection(annotation,file.enum_annotations,file,table)',
        'owner:"__pma_unknown_static_import"',
        'notbranch.known')):
    raise SystemExit("PMA import visibility must filter known-inactive rows and mark unresolved static-arm imports as uncertain")
if not all(fragment in selective_import_status for fragment in (
        'pma_import_row_branch_uncertain(annotations,"__from_member",member_annotation.name,member_annotation.module,member_annotation.line,member_annotation.offset)',
        'known_order<-false')) or not all(fragment in public_import_visibility for fragment in (
        'pma_import_row_branch_uncertain(annotations,annotation.owner,annotation.name,annotation.module,annotation.line,annotation.offset)')):
    raise SystemExit("uncertain selective or wildcard imports must not establish a definite public winner")
if not all(fragment in active_import_annotations for fragment in (
        'annotation.owner=="__from_member"',
        'annotation.name=="__binding_wildcard_import"')):
    raise SystemExit("PMA filtering must cover selective and wildcard import rows")
if not all(fragment in compact(parser_text) for fragment in (
        'parser<-parser.record_static_if_branch_rows("__from_member_static_branch",member,token)',
        'parser<-parser.record_static_if_branch_markers(marker_name,detail_name,parser.current_module,token.line,token.start)',
        'owner:"__static_if_branch",name:marker_name,detail_name:detail_name,module:marker_module',
        'identity_id:branch_identity')):
    raise SystemExit("selective import parser rows must carry the member token's enclosing static-if branch identities")
private_markers = compact(function_section(parser_text, "record_static_if_branch_markers"))
if not all(fragment in private_record for fragment in (
        'parser<-parser.record_static_if_branch_markers("__private_member_static_branch",member_name,parser.current_module,section_line,member_position.offset)')) or not all(fragment in private_markers for fragment in (
        'marker_name',
        'detail_name',
        'marker_module',
        'marker_line',
        'marker_offset',
        'owner:"__static_if_branch"',
        'identity_id:branch_identity')):
    raise SystemExit("private declarations must carry their enclosing static-if branch identities")
if not all(fragment in import_annotation_branch_selection for fragment in (
        'annotation.owner=="__private_member"',
        'module_annotation.owner!="__private_member_module"',
        'pma_import_branch_selection(annotations,file,table,"__static_if_branch","__private_member_static_branch",annotation.name,member_module,annotation.line,annotation.offset)',
        '"__private_member_static_branch"',
        'module_annotation.name')) or not all(fragment in active_import_annotations for fragment in (
        'private_member_row:bool=annotation.owner=="__private_member"',
        'branch_row:bool=import_roworprivate_member_row',
        'branch.knownandnotbranch.active')):
    raise SystemExit("PMA must remove proven-inactive private declarations before building its privacy index")
check_private_entry = compact(function_section(consumer_text, "check_private_member_access"))
if not all(fragment in check_private_entry for fragment in (
        "annotations:darray[Ast::EnumAnnotation]=pma_active_import_annotations(file,table)",
        "pma_build_selective_import_index(annotations,private_index)",
        'pma_walk_declarations(file.top_decls,"",private_index,annotations,table)')):
    raise SystemExit("private-member checking must build its import index and walk declarations from branch-filtered annotations")
if not all(fragment in public_call_sibling_rank for fragment in (
        "pma_argument_type_name(arguments[0],bound,bound_types)",
        "pma_symbol_has_private_marker(index,symbol)",
        "ifnotunqualified_call:continueifsymbol.module_owner!=owner",
        "pma_unqualified_candidate_module_visible(index,annotations,current_module,symbol.module_owner,member)",
        "first_parameter.name==actual_type",
        "actual_type==\"int\"and(first_parameter.kind==SemTypeKind.Intorfirst_parameter.kind==SemTypeKind.Char)",
        "symbol.module_owner==\"\"orpma_within_module(current_module,symbol.module_owner)",
        "candidate_rank<-2.usize()",
        "first_parameter.kind==SemTypeKind.Namedandfirst_parameter.name==actual_typeandpma_named_type_spelling_is_unique(table,first_parameter.name)",
        "pma_generic_parameter_identity(annotations,first_parameter.name,symbol)")) or not all(fragment in candidate_module_visibility for fragment in (
        'candidate_module==""orpma_within_module(current_module,candidate_module)',
        "pma_imported_module_member_visible(index,annotations,current_module,candidate_module,member)")) or not all(fragment in private_candidate_rank for fragment in (
        'actual_type=="bool"',
        "public_rank>0.usize()",
        "pma_generic_parameter_identity(annotations,first_parameter.name,symbol)")):
    raise SystemExit("private-call suppression must prove exact public formals outrank private generic candidates while ties stay fail-closed")
if not all(fragment in named_type_spelling_unique for fragment in (
        "symbol.name!=name",
        "type_symbol:bool=symbol.kind==SymbolKind.Structorsymbol.kind==SymbolKind.Enumorsymbol.kind==SymbolKind.Aliasor(symbol.kind==SymbolKind.Externandsymbol.opaque_extern_type)",
        "nottype_symbol",
        "returnfalseiffound",
        "found<-true",
        "returnfound")):
    raise SystemExit("named-formal ranking must fail closed when a type spelling belongs to multiple nominal declarations")
if not all(fragment in private_candidate_rank for fragment in (
        "public_rank>1.usize()",
        "public_rank>0.usize()")):
    raise SystemExit("direct lexical winners must outrank imported candidates before same-tier receiver specificity")
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
static_private_branch_match = re.search(r"(?ms)^module StaticPrivateBranchProvider:\n(.*?)(?=^(?:module |static if |using |from |def ))", call_shapes_text)
static_private_branch_fixture = static_private_branch_match.group(1) if static_private_branch_match else ""
if not all(fragment in compact(static_private_branch_fixture) for fragment in (
        "staticiffalse:private:defchoose()",
        "staticelse:public:defchoose()")):
    raise SystemExit("private-branch control must pair an inactive private declaration with an active public declaration of the same name")
if not all(fragment in call_shapes_text for fragment in (
        "return (Provider::dispatch)(value)",
        "return Provider::dispatch[bool](value)",
        "return dispatch(value)",
        "return dispatch[bool](value)",
        "return Provider::sealed(value)",
        "return BroadProvider::prefer(value)",
        "return NamedProvider::inspect(value)",
        "return QualifiedNamedProvider::inspect(value)",
        "return LiteralProvider::choose(7)",
        "return wrap(fetch)",
        "return wrap(retrieve)",
        "static if false:",
        "static else:",
        "from InactivePrivateProvider import pick",
        "from ActivePublicProvider import pick",
        "def inactive_branch_private_import_does_not_shadow_public()",
        "return pick()",
        "module StaticPrivateBranchProvider:",
        "def inactive_branch_private_declaration_does_not_hide_public()",
        "return StaticPrivateBranchProvider::choose()",
        "def public_concrete_over_private_generic(value: i64)",
        "def public_named_concrete_over_private_generic(value: UniqueWidget)",
        "def same_spelling_different_modules_private_generic_winner(value: Widget)",
        "def public_concrete_literal_winner()",
        "def public_selective_function_value()")) or not all(fragment in call_shapes_smoke_text for fragment in (
        'private_call_overload_visibility_shapes.elisa',
        '[[ $(grep -cF \'is private to module\' <<< "$stage0_output") == 2 ]]',
        '[[ $(grep -cF \'is private to module\' <<< "$stage1_output") == 2 ]]',
        "QualifiedNamedProvider.inspect")):
    raise SystemExit("call-shape fixture must cover parenthesized, explicit-generic, static-import visibility, and private-only controls")

if not all(fragment in unknown_static_import_text for fragment in (
        "const USE_PUBLIC_IMPORT: bool = true",
        "const USE_PRIVATE_WILDCARD: bool = false",
        "static if USE_PUBLIC_IMPORT:",
        "using PrivateWildcardProvider",
        "using PublicWildcardProvider",
        "from PublicProvider import pick",
        "static else:",
        "from PrivateProvider import pick",
        "def pick[T](value: T) -> i64:",
        "return pick(true)")) or not all(fragment in unknown_static_import_smoke_text for fragment in (
        "private_call_static_unknown_import.elisa",
        "Stage0 rejected the definite root generic winner",
        "Stage1 reported an imported private overload that loses to the root generic")):
    raise SystemExit("named-constant static import fixture must preserve the direct root generic winner")

static_true_import_control_text = STATIC_TRUE_IMPORT_CONTROL.read_text()
static_true_import_control_smoke_text = STATIC_TRUE_IMPORT_CONTROL_SMOKE.read_text()
if not all(fragment in static_true_import_control_text for fragment in (
        "static if true:",
        "const USE_PUBLIC_IMPORT: bool = true",
        "const USE_PUBLIC_IMPORT: bool = false",
        "def pick(value: bool) -> i64:",
        "from PublicProvider import pick",
        "static else:",
        "from PrivateProvider import pick",
        "return pick(true)")) or not all(fragment in static_true_import_control_smoke_text for fragment in (
        "private_call_static_true_import_control.elisa",
        "Stage0 rejected the active public import",
        "Stage1 reported the inactive private import")):
    raise SystemExit("named-constant static-true control must prove that an inactive private import does not trigger PMA")

if not all(fragment in root_overloads_text for fragment in (
        "def choose(value: i64)",
        "def choose_selective(value: bool)",
        "from SelectiveProvider import choose_selective",
        "def prefer[T](value: T)",
        "def choose[T](value: T)",
        "def choose_selective[T](value: T)",
        "def prefer(value: bool)",
        "return choose(value)",
        "return choose_selective(value)",
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
    POSITIVE, NEGATIVE, UNKNOWN_STATIC_IMPORT, UNKNOWN_STATIC_IMPORT_SMOKE, *source_closure,
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
