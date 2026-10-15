"""Bind global-authority binder-origin and permission policies to the semantic pass."""
from __future__ import annotations

import argparse
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
POLICY = ROOT / "src/semantic/global_authority_origin_policy.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
AUTHORITY = ROOT / "src/semantic/check_global_authority.elisa"
AUTHORITY_TYPES = ROOT / "src/semantic/check_global_authority_types.elisa"
POSITIVE = HERE / "global_authority_origin_policy.elisa"
NEGATIVE = HERE / "global_authority_origin_policy_rejected.elisa"
SMOKE = ROOT / "test/parity/mutable_global_grants_smoke.py"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check production and proof bindings without running Elisa-Proof")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


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


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


policy_text = POLICY.read_text()
semantic_text = SEMANTIC.read_text()
authority_text = AUTHORITY.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

for fragment in (
    "const NO_ORIGIN: usize = 4294967295",
    "const UNKNOWN_ALIAS: usize = 4294967294",
    "const LOCAL_ALIAS: usize = 4294967293",
):
    if compact(fragment) not in compact(policy_text):
        raise SystemExit(f"global-authority origin sentinel changed: {fragment}")
authority_origin_constants = (
    "const GLOBAL_AUTHORITY_NONE: usize = 4294967295",
    "const GLOBAL_AUTHORITY_UNKNOWN_ALIAS: usize = 4294967294",
    "const GLOBAL_AUTHORITY_LOCAL_ALIAS: usize = 4294967293",
)
if any(compact(fragment) not in compact(authority_text) for fragment in authority_origin_constants):
    raise SystemExit("origin policy sentinels no longer match the semantic pass")

policy_body = compact(function_section(policy_text, "pattern_binding_origin"))
expected_policy = compact("""
def pattern_binding_origin(contains_reference: bool, source_origin: usize) -> usize:
    ensure result == (
        NO_ORIGIN if not contains_reference else
        (source_origin if source_origin != NO_ORIGIN else UNKNOWN_ALIAS)
    )
    return NO_ORIGIN if not contains_reference
    return source_origin if source_origin != NO_ORIGIN
    return UNKNOWN_ALIAS
""")
if policy_body != expected_policy:
    raise SystemExit("production binder-origin policy changed from its exact origin-preservation rule")
join_body = compact(function_section(policy_text, "join_reference_origins"))
expected_join = compact("""
def join_reference_origins(left: usize, right: usize) -> usize:
    ensure result == (
        right if left == NO_ORIGIN else
        (left if right == NO_ORIGIN else
            (left if left == right else UNKNOWN_ALIAS))
    )
    return right if left == NO_ORIGIN
    return left if:
        right == NO_ORIGIN
        left == right
    return UNKNOWN_ALIAS
""")
if join_body != expected_join:
    raise SystemExit("production reference-origin join changed from its exact conservative lattice rule")
opaque_body = compact(function_section(policy_text, "opaque_expression_origin"))
expected_opaque = compact("""
def opaque_expression_origin(type_known: bool, contains_reference: bool) -> usize:
    ensure result == (UNKNOWN_ALIAS if not type_known or contains_reference else NO_ORIGIN)
    return UNKNOWN_ALIAS if:
        not type_known
        contains_reference
    return NO_ORIGIN
""")
if opaque_body != expected_opaque:
    raise SystemExit("opaque-expression origin policy must preserve unknown or reference-bearing values")
constructor_body = compact(function_section(policy_text, "constructor_origin"))
expected_constructor = compact("""
def constructor_origin(summary: usize, reference_fields_complete: bool) -> usize:
    ensure result == (summary if reference_fields_complete else UNKNOWN_ALIAS)
    return summary if reference_fields_complete
    return UNKNOWN_ALIAS
""")
if constructor_body != expected_constructor:
    raise SystemExit("incomplete reference-bearing constructors must discard partial origin summaries")
permission_body = compact(function_section(policy_text, "unknown_alias_permission"))
expected_permission = compact('''
def unknown_alias_permission(write: bool) -> sview:
    ensure result == ("Global.Write" if write else "Global.Read")
    return "Global.Write" if write
    return "Global.Read"
''')
if permission_body != expected_permission:
    raise SystemExit("production unknown-alias permission mapping changed from its exact read/write rule")
conservative_origin_body = compact(function_section(policy_text, "requires_unknown_alias_permission"))
expected_conservative_origin = compact('''
def requires_unknown_alias_permission(origin: usize) -> bool:
    ensure result == (origin == NO_ORIGIN or origin == UNKNOWN_ALIAS or origin == LOCAL_ALIAS)
    return origin == NO_ORIGIN or origin == UNKNOWN_ALIAS or origin == LOCAL_ALIAS
''')
if conservative_origin_body != expected_conservative_origin:
    raise SystemExit("reserved and unknown origins must use the exact fail-closed access classification")

policy_include = 'include "./global_authority_origin_policy.elisa"'
authority_include = 'include "./check_global_authority.elisa"'
if policy_include not in semantic_text or authority_include not in semantic_text or \
        semantic_text.index(policy_include) > semantic_text.index(authority_include):
    raise SystemExit("semantic facade must load the proved origin policy before global authority")

pattern_metadata = compact(function_section(authority_text, "ga_pattern_binding_metadata"))
metadata_steps = (
    "is_reference: bool = ga_type_id_is_reference(binding_type_id, table) or (binding_type_id == 0 and whole_value and ga_expression_is_reference(subject, state, 0))",
    "contains_reference: mutable bool = ga_type_id_contains_reference(binding_type_id, table) or is_reference",
    "source_origin: usize = ga_reference_origin(subject, state, 0) if contains_reference else GLOBAL_AUTHORITY_NONE",
    "global_origin: usize = SemanticGlobalAuthorityOrigin::pattern_binding_origin(contains_reference, source_origin)",
    "return (type_expression, global_origin, type_scope)",
)
metadata_positions = [pattern_metadata.find(compact(fragment)) for fragment in metadata_steps]
if any(position < 0 for position in metadata_positions) or metadata_positions != sorted(metadata_positions):
    raise SystemExit("match-pattern binding no longer forwards its type and source origin through the proved policy")
if "iftype_expressionisbinding_type_expression:contains_reference<-contains_referenceorga_type_expression_contains_reference(binding_type_expression,state,0)" not in pattern_metadata:
    raise SystemExit("match binders must classify nested references in named aggregate types")
if "return(type_expression,GLOBAL_AUTHORITY_NONE)" in pattern_metadata or \
        "return(type_expression,GLOBAL_AUTHORITY_UNKNOWN_ALIAS)" in pattern_metadata:
    raise SystemExit("match-pattern origin bypasses the proved policy with a local fallback")

expression_walk = compact(function_section(authority_text, "ga_expression_inner"))
statement_walk = compact(function_section(authority_text, "ga_statements_inner"))
for body in (expression_walk, statement_walk):
    if "ga_type_id_contains_reference(binding_type_id,table)" not in body or \
            "iterable_origin:usize=ga_reference_origin(iterable,state,0)" not in body or \
            "SemanticGlobalAuthorityOrigin::pattern_binding_origin(binding_has_references,iterable_origin)" not in body or \
            "ga_iteration_binding_type_expression(iterable,binding_type_id" not in body:
        raise SystemExit("loop and comprehension binders must preserve item type and reference-origin summaries")
arms_body = compact(function_section(authority_text, "ga_arms_inner"))
if "state.local_global_origins.push(metadata.global_origin)" not in arms_body:
    raise SystemExit("match-arm binders no longer retain the proved origin metadata")

access_body = compact(function_section(authority_text, "ga_access"))
if "elifSemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(alias_origin):table<-ga_access_unknown_alias(Ast::expr_pos(expression),write,state,table)canGlobal{Read,Write}" not in access_body:
    raise SystemExit("unknown binder origins no longer route accesses through conservative authority requirements")
if "ifga_expression_is_reference(expression,state,0):ifalias_origin<state.globals.count:" not in access_body:
    raise SystemExit("aggregate origin summaries must not be mistaken for direct global accesses")
rebind_body = compact(function_section(authority_text, "ga_statements_inner"))
if "elifSemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(origin):table<-ga_access_unknown_alias(Ast::expr_pos(value),true,state,table)canGlobal{Read,Write}" not in rebind_body:
    raise SystemExit("unknown reference rebinds no longer route writes through conservative authority requirements")
write_place_body = compact(function_section(authority_text, "ga_write_place_inner"))
if "ifga_expression_is_reference(expression,state,0):table<-ga_access(expression,true,state,table)canGlobal{Read,Write}" not in write_place_body:
    raise SystemExit("writes through typed aggregate reference fields must consult their preserved origin")
origin_walk = compact(function_section(authority_text, "ga_reference_origin"))
for fragment in (
    "Expr.Array(elements,_)|Expr.Tuple(elements,_)|Expr.SetLit(elements,_) ",
    "SemanticGlobalAuthorityOrigin::join_reference_origins(origin,element_origin)",
    "SemanticGlobalAuthorityOrigin::join_reference_origins(origin,key_origin)",
    "SemanticGlobalAuthorityOrigin::join_reference_origins(origin,value_origin)",
):
    if compact(fragment) not in origin_walk:
        raise SystemExit("aggregate reference-origin summaries no longer join all contained value origins")
local_address = compact(function_section(authority_text, "ga_local_address_origin"))
for fragment in (
    "returnga_local_origin(local_index,state)ifnotprojected",
    "returnga_local_origin(local_index,state)ifnotga_reference_type(root_type,state,0)",
):
    if fragment not in local_address:
        raise SystemExit("direct borrows of local storage must preserve the encoded local-root identity")
local_origin = compact(function_section(authority_text, "ga_local_origin"))
local_origin_guard = compact("""
return GLOBAL_AUTHORITY_UNKNOWN_ALIAS if:
    identity >= GLOBAL_AUTHORITY_LOCAL_ALIAS or state.globals.count >= GLOBAL_AUTHORITY_LOCAL_ALIAS
    identity >= GLOBAL_AUTHORITY_LOCAL_ALIAS - state.globals.count
""")
if "identity:usize=state.local_origin_ids[local_index]" not in local_origin or \
        local_origin_guard not in local_origin or \
        "returnstate.globals.count+identity" not in local_origin:
    raise SystemExit("encoded local roots must stay below the reserved alias ceiling and fail closed on overflow")
push_local_origin = compact(function_section(authority_text, "ga_push_local_origin_id"))
if "state.local_origin_ids.push(GLOBAL_AUTHORITY_LOCAL_ALIAS)" not in push_local_origin or \
        "state.next_local_origin_id<GLOBAL_AUTHORITY_LOCAL_ALIAS-state.globals.count" not in push_local_origin:
    raise SystemExit("local-origin allocation must reserve its ceiling for fail-closed overflow")
opaque_origin = compact(function_section(authority_text, "ga_expression_reference_origin"))
if "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true,ga_type_expression_contains_reference(annotation,state,depth+1))" not in opaque_origin or \
        "SemanticGlobalAuthorityOrigin::opaque_expression_origin(false,false)" not in opaque_origin:
    raise SystemExit("opaque expression origins must use the proved fail-closed policy")
if "ga_expression_reference_origin(expression,state,depth+1)" not in origin_walk:
    raise SystemExit("opaque or reference-bearing values must not disappear from aggregate origin summaries")
if "SemanticGlobalAuthorityOrigin::constructor_origin(origin,false)" not in origin_walk or \
        "SemanticGlobalAuthorityOrigin::constructor_origin(origin,true)" not in origin_walk:
    raise SystemExit("struct constructor summaries must pass through the proved field-coverage rule")
constructor_coverage = compact(function_section(authority_text, "ga_construct_omits_reference_field"))
for fragment in (
    "returntrueifowner>=state.struct_names.count",
    "returntrueifstate.field_scopes[field_index]!=state.module_scope",
    'returntrueifinitializer.name==""andnotinitializer.is_copy_base',
    "found<-trueifinitializer.name==state.field_names[field_index]",
    "returntrueifnotfound",
):
    if fragment not in constructor_coverage:
        raise SystemExit("constructor completeness must fail closed on omitted or unresolved reference fields")
collection = compact(function_section(authority_text, "ga_collect"))
for fragment in (
    "Decl.Enum(name,variants,_,_,_):",
    "state.enum_variant_owners.push(name)",
    "state.enum_variant_payload_starts.push(state.enum_variant_payload_types.count)",
    "state.enum_variant_payload_counts.push(variant.fields.count)",
    "state.enum_variant_payload_types.push(variant.fields[field_index])",
    "state.enum_variant_payload_names.push(variant.field_names[field_index]iffield_index<variant.field_names.countelsesview(\"\",0,0))",
):
    if fragment not in collection:
        raise SystemExit("enum constructor origin summaries must bind to declared lexical payload layouts")
variant_slot = compact(function_section(authority_text, "ga_enum_variant_slot"))
if "ga_resolve(ga_type_head(owner_expression),ga_type_scope(owner_expression,state),ga_type_qualified(owner_expression),state.enum_names,state.enum_scopes,state)" not in variant_slot or \
        "state.enum_variant_names[variant_slot]==variant_name" not in variant_slot or \
        "ga_local_slot(owner_name,state)<state.locals.count" not in variant_slot:
    raise SystemExit("enum constructor recognition must require its resolved owner and exact variant")
variant_origin = compact(function_section(authority_text, "ga_enum_constructor_origin"))
for fragment in (
    "arguments.count!=state.enum_variant_payload_counts[variant_slot]",
    "SemanticGlobalAuthorityOrigin::constructor_origin(GLOBAL_AUTHORITY_NONE,false)",
    "state.enum_variant_payload_names[payload_index]==label",
    "ga_reference_origin(argument,state,depth+1)",
    "SemanticGlobalAuthorityOrigin::join_reference_origins(origin,argument_origin)",
    "SemanticGlobalAuthorityOrigin::constructor_origin(origin,true)",
):
    if fragment not in variant_origin:
        raise SystemExit("enum payload origin summaries must join the exact constructor arguments and fail closed")
if "Expr.Call(callee,arguments,labels,_):variant_slot:usize=ga_enum_variant_slot(callee,state)" not in origin_walk or \
        "ga_enum_constructor_origin(variant_slot,arguments,labels,state,depth+1)" not in origin_walk:
    raise SystemExit("only resolved enum constructors may expose their payload origins")
type_expression_classifier = compact(function_section(AUTHORITY_TYPES.read_text(), "ga_type_expression_contains_reference"))
if "returntrueifga_reference_type(resolved,state,depth+1)" not in type_expression_classifier or \
        "owner:usize=ga_known_struct(resolved,state.module_scope,state,depth+1)" not in type_expression_classifier or \
        "returntrueif:state.field_scopes[index]!=state.module_scopega_type_expression_contains_reference(state.field_types[index],state,depth+1)" not in type_expression_classifier or \
        "ga_type_expression_contains_reference(state.enum_variant_payload_types[payload_index],state,depth+1)" not in type_expression_classifier:
    raise SystemExit("reference classification must recurse through named aggregate and enum payload fields")
contains_refs = compact(function_section(authority_text, "ga_type_id_contains_reference"))
if "kind!=SemTypeKind.Optionalandkind!=SemTypeKind.Tupleandkind!=SemTypeKind.Container" not in contains_refs or \
        "ga_type_id_contains_reference(interned_elem(type_id,element_index,table),table,depth+1)" not in contains_refs:
    raise SystemExit("binder reference detection must recurse through tuples and container element types")
tuple_annotation = compact(function_section(AUTHORITY_TYPES.read_text(), "ga_tuple_field_type"))
if 'annotation.owner=="__tuple_label"andannotation.name==field' not in tuple_annotation:
    raise SystemExit("named-tuple field annotations must be available to the global-authority type walk")
smoke_text = SMOKE.read_text()
required_regressions = (
    "local reference items stay local through tuple iteration",
    "local reference items stay local through tuple comprehension",
    "local reference payloads stay local through tuple matching",
    "named tuple reference binder requires Global.Write",
    "named tuple reference binder accepts both grants",
    "local nominal reference items stay local through iteration",
    "nominal reference binder requires Global.Write",
    "nominal reference binder accepts both grants",
    "local nominal reference binder stays local through match",
    "nominal match reference binder requires Global.Write",
    "nominal match reference binder accepts both grants",
    "nominal reference origin does not taint scalar siblings",
    "omitted default reference field keeps aggregate origin unknown",
    "local enum constructor payload keeps local origin",
    "external enum payload binder requires Global.Write",
    "external enum payload binder accepts both grants",
    "mixed enum payload origins require Global.Write",
)
if any(smoke_text.count(f'("{name}",') != 1 for name in required_regressions):
    raise SystemExit("global-authority smoke suite lost a local-origin or named-tuple alias regression")
if "darray[(pointer: mutable i64&, step: usize)]&" not in smoke_text or \
        "set_one(item.pointer)" not in smoke_text:
    raise SystemExit("named-tuple loop regression no longer exercises a reference-bearing field access")
if "darray[GrantOriginHolder]&" not in smoke_text or \
        "GrantOriginHolder{pointer: &seed, step: 0.usize()}" not in smoke_text:
    raise SystemExit("nominal loop regressions must cover both local and external nested-reference origins")
if "pointer: mutable i64& = &hot" not in smoke_text or \
        "GrantOriginDefaultHolder{local: &seed}" not in smoke_text:
    raise SystemExit("constructor regression must cover an omitted reference-bearing default field")
if "GrantOriginMatchHolder{pointer: pointer}" not in smoke_text or \
        "return holder.step" not in smoke_text:
    raise SystemExit("nominal match regressions must preserve payload origins without tainting scalar siblings")
if "GrantOriginCarrier.Wrap(pointer: &seed)" not in smoke_text or \
        "GrantOriginPair.Wrap(left: &seed, right: &hot)" not in smoke_text:
    raise SystemExit("enum constructor regressions must cover named arguments and mixed local/global payload roots")
unknown_access_body = compact(function_section(authority_text, "ga_access_unknown_alias"))
unknown_access_fragments = (
    "required:sview=SemanticGlobalAuthorityOrigin::unknown_alias_permission(write)",
    "returnifga_refs_cover(state.firewalls,state.firewall_scopes,required,0,state)",
    "ifnotstate.report:_=ga_row_add(state.function,required,true,state)canGlobal{Read,Write}",
    "ifwrite:state.writes[state.function]<-trueelse:state.reads[state.function]<-true",
    "elifnotga_granted(required,at,state):table.diagnostics<-table.diagnostics.push(Diagnostic{kind:DiagnosticKind.MutableGlobalPermissionUngranted",
)
if any(fragment not in unknown_access_body for fragment in unknown_access_fragments):
    raise SystemExit("unknown reference aliases no longer require the corresponding Global permission")

positive_names = {
    "pattern_binding_origin_matches_its_exact_spec",
    "values_without_references_have_no_origin",
    "known_global_origins_survive_binding_and_projection",
    "known_local_origins_survive_binding_and_projection",
    "unknown_reference_origins_fail_closed",
    "reference_origin_join_matches_its_exact_spec",
    "no_origin_is_a_left_join_identity",
    "no_origin_is_a_right_join_identity",
    "matching_local_origins_join_to_local",
    "conflicting_local_and_global_origins_join_to_unknown",
    "reference_origin_join_is_commutative",
    "reference_origin_join_is_associative",
    "reference_origin_join_is_idempotent",
    "unknown_origin_absorbs_every_joined_origin",
    "opaque_expression_origin_matches_its_exact_spec",
    "opaque_expression_without_type_fails_closed",
    "opaque_reference_bearing_expression_fails_closed",
    "known_reference_free_opaque_expression_has_no_origin",
    "constructor_origin_matches_reference_field_coverage",
    "incomplete_constructor_reference_fields_fail_closed",
    "complete_constructor_reference_fields_keep_summary",
    "unknown_alias_permission_matches_its_exact_spec",
    "writing_through_an_unknown_alias_requires_global_write",
    "reading_through_an_unknown_alias_requires_global_read",
    "conservative_alias_policy_matches_its_exact_spec",
    "missing_origin_requires_conservative_access",
    "unknown_origin_requires_conservative_access",
    "reserved_local_alias_requires_conservative_access",
    "encoded_local_origins_bypass_unknown_alias_policy",
}
negative_names = {
    "value_without_references_can_be_an_unknown_alias",
    "unknown_reference_can_be_treated_as_origin_free",
    "known_local_reference_can_be_reclassified_as_unknown",
    "conflicting_local_and_global_origins_can_be_called_local",
    "distinct_global_origins_can_keep_the_first_root",
    "unknown_and_local_origins_can_join_to_local",
    "unknown_origin_can_be_erased_by_an_arbitrary_joined_origin",
    "opaque_expression_without_type_can_have_no_origin",
    "opaque_reference_bearing_expression_can_have_no_origin",
    "known_reference_free_expression_must_be_unknown",
    "incomplete_constructor_can_keep_a_known_local_summary",
    "complete_constructor_must_be_unknown",
    "unknown_alias_write_can_require_only_global_read",
    "unknown_alias_read_can_require_global_write",
    "unknown_alias_can_skip_conservative_access",
    "missing_origin_can_skip_conservative_access",
    "reserved_local_alias_can_skip_conservative_access",
    "encoded_local_origin_can_require_unknown_alias_access",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("global-authority origin proof declaration inventory changed")
if 'include "../../src/semantic/global_authority_origin_policy.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production origin policy")
if 'include "./global_authority_origin_policy.elisa"' not in negative_text:
    raise SystemExit("false controls no longer inherit the production-linked positive proof")

positive_claims = {
    "pattern_binding_origin_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(contains_reference, source_origin) == (SemanticGlobalAuthorityOrigin::NO_ORIGIN if not contains_reference else (source_origin if source_origin != SemanticGlobalAuthorityOrigin::NO_ORIGIN else SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS))",
    "values_without_references_have_no_origin": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(false, 17.usize()) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "known_global_origins_survive_binding_and_projection": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, 17.usize()) == 17.usize()",
    "known_local_origins_survive_binding_and_projection": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, SemanticGlobalAuthorityOrigin::LOCAL_ALIAS) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "unknown_reference_origins_fail_closed": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, SemanticGlobalAuthorityOrigin::NO_ORIGIN) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "reference_origin_join_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::join_reference_origins(left, right) == (right if left == SemanticGlobalAuthorityOrigin::NO_ORIGIN else (left if right == SemanticGlobalAuthorityOrigin::NO_ORIGIN else (left if left == right else SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)))",
    "no_origin_is_a_left_join_identity": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::NO_ORIGIN, 17.usize()) == 17.usize()",
    "no_origin_is_a_right_join_identity": "SemanticGlobalAuthorityOrigin::join_reference_origins(17.usize(), SemanticGlobalAuthorityOrigin::NO_ORIGIN) == 17.usize()",
    "matching_local_origins_join_to_local": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, SemanticGlobalAuthorityOrigin::LOCAL_ALIAS) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "conflicting_local_and_global_origins_join_to_unknown": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, 17.usize()) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "reference_origin_join_is_commutative": "SemanticGlobalAuthorityOrigin::join_reference_origins(left, right) == SemanticGlobalAuthorityOrigin::join_reference_origins(right, left)",
    "reference_origin_join_is_associative": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::join_reference_origins(first, second), third) == SemanticGlobalAuthorityOrigin::join_reference_origins(first, SemanticGlobalAuthorityOrigin::join_reference_origins(second, third))",
    "reference_origin_join_is_idempotent": "SemanticGlobalAuthorityOrigin::join_reference_origins(origin, origin) == origin",
    "unknown_origin_absorbs_every_joined_origin": "(SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS, origin) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS and SemanticGlobalAuthorityOrigin::join_reference_origins(origin, SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)",
    "opaque_expression_origin_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(type_known, contains_reference) == (SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS if not type_known or contains_reference else SemanticGlobalAuthorityOrigin::NO_ORIGIN)",
    "opaque_expression_without_type_fails_closed": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(false, false) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "opaque_reference_bearing_expression_fails_closed": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true, true) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "known_reference_free_opaque_expression_has_no_origin": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true, false) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "constructor_origin_matches_reference_field_coverage": "SemanticGlobalAuthorityOrigin::constructor_origin(summary, reference_fields_complete) == (summary if reference_fields_complete else SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)",
    "incomplete_constructor_reference_fields_fail_closed": "SemanticGlobalAuthorityOrigin::constructor_origin(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, false) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "complete_constructor_reference_fields_keep_summary": "SemanticGlobalAuthorityOrigin::constructor_origin(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, true) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "unknown_alias_permission_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::unknown_alias_permission(write) == (\"Global.Write\" if write else \"Global.Read\")",
    "writing_through_an_unknown_alias_requires_global_write": 'SemanticGlobalAuthorityOrigin::unknown_alias_permission(true) == "Global.Write"',
    "reading_through_an_unknown_alias_requires_global_read": 'SemanticGlobalAuthorityOrigin::unknown_alias_permission(false) == "Global.Read"',
    "conservative_alias_policy_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(origin) == (origin == SemanticGlobalAuthorityOrigin::NO_ORIGIN or origin == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS or origin == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS)",
    "missing_origin_requires_conservative_access": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::NO_ORIGIN)",
    "unknown_origin_requires_conservative_access": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)",
    "reserved_local_alias_requires_conservative_access": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS)",
    "encoded_local_origins_bypass_unknown_alias_policy": "not SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(global_count + identity)",
}
negative_claims = {
    "value_without_references_can_be_an_unknown_alias": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(false, 17.usize()) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "unknown_reference_can_be_treated_as_origin_free": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, SemanticGlobalAuthorityOrigin::NO_ORIGIN) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "known_local_reference_can_be_reclassified_as_unknown": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, SemanticGlobalAuthorityOrigin::LOCAL_ALIAS) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "conflicting_local_and_global_origins_can_be_called_local": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, 17.usize()) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "distinct_global_origins_can_keep_the_first_root": "SemanticGlobalAuthorityOrigin::join_reference_origins(17.usize(), 19.usize()) == 17.usize()",
    "unknown_and_local_origins_can_join_to_local": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS, SemanticGlobalAuthorityOrigin::LOCAL_ALIAS) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "unknown_origin_can_be_erased_by_an_arbitrary_joined_origin": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS, origin) == origin",
    "opaque_expression_without_type_can_have_no_origin": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(false, false) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "opaque_reference_bearing_expression_can_have_no_origin": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true, true) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "known_reference_free_expression_must_be_unknown": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true, false) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "incomplete_constructor_can_keep_a_known_local_summary": "SemanticGlobalAuthorityOrigin::constructor_origin(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, false) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "complete_constructor_must_be_unknown": "SemanticGlobalAuthorityOrigin::constructor_origin(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, true) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "unknown_alias_write_can_require_only_global_read": 'SemanticGlobalAuthorityOrigin::unknown_alias_permission(true) == "Global.Read"',
    "unknown_alias_read_can_require_global_write": 'SemanticGlobalAuthorityOrigin::unknown_alias_permission(false) == "Global.Write"',
    "unknown_alias_can_skip_conservative_access": "not SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)",
    "missing_origin_can_skip_conservative_access": "not SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::NO_ORIGIN)",
    "reserved_local_alias_can_skip_conservative_access": "not SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS)",
    "encoded_local_origin_can_require_unknown_alias_access": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(global_count + identity)",
}
for source_text, claims, label in (
    (positive_text, positive_claims, "positive"),
    (negative_text, negative_claims, "negative"),
):
    for name, claim in claims.items():
        section = compact(function_section(source_text, name))
        if "ensureresult==true" not in section or f"return{compact(claim)}" not in section:
            raise SystemExit(f"{label} origin theorem changed its exact claim: {name}")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_declarations": len(positive_names),
        "false_control_declarations": len(negative_names),
        "source_closure_files": len(source_closure),
    }, sort_keys=True))
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("global-authority origin proof requires a strict proof build")

stage1 = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POLICY, SEMANTIC, AUTHORITY, AUTHORITY_TYPES, SMOKE, POSITIVE, NEGATIVE, *source_closure,
]
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == manifest
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "whole-value reference binders retain known global roots; other references fail closed as unknown aliases",
    "positive_theorems": sorted(positive_names),
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
}, sort_keys=True))
