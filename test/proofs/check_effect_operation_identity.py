"""Guard operation call/value validation against same-leaf effect joins."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = ROOT / "src/parser/parser_expr_postfix.elisa"
HANDLER_REWRITE = ROOT / "src/parser/parser_effect_handler_rewrite.elisa"
HEADS = ROOT / "src/semantic/check_effect_operation_heads.elisa"
SEMANTIC = ROOT / "src/semantic/check_abstract_effects.elisa"
SIGNATURES = ROOT / "src/semantic/check_effect_signatures.elisa"
SIGNATURE_FIXTURE = ROOT / "test/fixtures/effects/operation_identity_same_leaf_signature.elisa"
MISSING_CALL = ROOT / "test/fixtures/effects/operation_identity_same_leaf_missing_call.neg.elisa"
MISSING_VALUE = ROOT / "test/fixtures/effects/operation_identity_same_leaf_missing_value.neg.elisa"
GENERIC_ARITY = ROOT / "test/fixtures/effects/operation_identity_same_leaf_generic_arity.neg.elisa"
AMBIGUOUS_BARE = ROOT / "test/fixtures/effects/operation_identity_ambiguous_bare.neg.elisa"
AMBIGUOUS_HELPER = ROOT / "test/fixtures/effects/helper_ambiguous_bare_operation_identity.neg.elisa"
SMOKE = ROOT / "test/parity/effect_handler_stage1_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing effect operation identity helper {name}")
    return match.group(0)


parser = PARSER.read_text()
handler_rewrite = HANDLER_REWRITE.read_text()
heads = HEADS.read_text()
semantic = SEMANTIC.read_text()
signatures = SIGNATURES.read_text()
signature_fixture = SIGNATURE_FIXTURE.read_text()
missing_call = MISSING_CALL.read_text()
missing_value = MISSING_VALUE.read_text()
generic_arity = GENERIC_ARITY.read_text()
ambiguous_bare = AMBIGUOUS_BARE.read_text()
ambiguous_helper = AMBIGUOUS_HELPER.read_text()
smoke = SMOKE.read_text()

record = function_source(parser, "record_effect_operation_ref")
if not all(fragment in record for fragment in (
    'owner: "__effect_operation_ref"',
    "detail_name: head_text",
    "module: lexical_owner",
    "line: token.line",
    "offset: token.start",
    "lexical_owner: sview = parser.handler_rewrite_owner()",
    "parser.effect_identity_for_reference(head_text, lexical_owner, token.start)",
)):
    raise SystemExit("operation reference metadata must retain spelling, lexical owner, exact offset, and known identity")
for suffix in ("postfix_dot_suffix", "postfix_scope_suffix"):
    if "parser.record_effect_operation_ref(active, member_name, token)" not in function_source(parser, suffix):
        raise SystemExit(f"{suffix} must attach exact operation-reference metadata")

site = function_source(heads, "ae_operation_ref_site")
if not all(fragment in site for fragment in (
    'annotation.owner == "__effect_operation_ref"',
    "annotation.line == position.line",
    "annotation.offset == position.offset",
    "sites.operation_heads.get(key)",
    "sites.operation_effect_ids[row.usize()]",
)):
    raise SystemExit("semantic operation lookup must use the indexed exact source reference")
for helper in ("ae_call_is_operation", "ae_value_is_operation"):
    source = function_source(heads, helper)
    family_is_indexed = "ae_effect_family_indexed(effects, effect_name)" in source or \
        ("resolved_effect_name: sview = ae_operation_head(head)" in source and "ae_effect_family_indexed(effects, resolved_effect_name)" in source)
    if "ae_operation_ref_site(annotations" not in source or not family_is_indexed:
        raise SystemExit(f"{helper} must use exact reference metadata and recognize only effect-family candidates")

if 'annotation.owner == "__effect_operation_ref"' not in function_source(semantic, "ae_expression_annotation"):
    raise SystemExit("abstract-effect expression dependency slice must retain operation-reference metadata")
check_expression = function_source(semantic, "ae_check_expression")
for fragment in (
    "ae_effect_identity_index_declared(effect_index, effect_identity_id)",
    "ae_effect_operation_index_declared(effect_index, effect_identity_id, operation)",
    "ae_effect_generic_names_identity(annotations, effect_identity_id)",
    "ae_specialization_mismatch_at_site(annotations, sites, site_line, site_offset)",
):
    if fragment not in check_expression:
        raise SystemExit(f"ordinary operation checking must use identity/site-aware lookup: {fragment}")
if "ae_operation_declared(annotations, effect_name, operation)" in check_expression or \
        "ae_effect_generic_names(annotations, effect_name)" in check_expression:
    raise SystemExit("ordinary operation checking must not fall back to terminal-name joins")

mismatch_record = function_source(parser, "record_effect_specialization_mismatch")
mismatch_lookup = function_source(heads, "ae_specialization_mismatch_at_site")
if not all(fragment in mismatch_record for fragment in (
    'owner: "__effect_specialization_mismatch"',
    "module: parser.handler_rewrite_owner()",
    "offset: position.offset",
    "identity_id: identity_id",
)) or "annotation.offset == offset" not in mismatch_lookup:
    raise SystemExit("specialization mismatch metadata must be keyed to the exact member site")
rewrite_guard = function_source(parser, "handler_operation_ref_matches_active")
rewrite_identity = function_source(parser, "handler_operation_ref_matches_effect")
identity_at = function_source(parser, "effect_operation_ref_identity_at")
post_parse_rewrite = function_source(handler_rewrite, "rewrite_handler_expression")
if "requested_identity_id != 0 and requested_identity_id == active_identity_id" not in rewrite_identity or \
        "parser.effect_identity_for_reference(annotation.detail_name, annotation.module, annotation.offset)" not in identity_at or \
        "parser.handler_operation_ref_matches_active(operation_name, operation_line)" not in parser:
    raise SystemExit("handler rewriting must not capture an unresolved or ambiguous bare operation head")
if post_parse_rewrite.count("parser.handler_operation_ref_matches_effect(operation, field_pos, effect_name)") != 1 or \
        post_parse_rewrite.count("parser.handler_operation_ref_matches_effect(operation, scope_pos, effect_name)") != 1:
    raise SystemExit("post-parse Field and Scope rewrites must require the exact active effect identity")

for fixture in (missing_call, missing_value, generic_arity, signature_fixture, ambiguous_bare, ambiguous_helper):
    if "module A:" not in fixture or "module B:" not in fixture or "effect Tick" not in fixture:
        raise SystemExit("operation fixtures must define same-leaf effects in distinct modules")
if "B::Tick.ping()" not in missing_call or "def pong()" not in missing_call:
    raise SystemExit("call regression must reject an operation that exists only on A::Tick")
if "B::Tick.ping" not in missing_value or "def pong()" not in missing_value:
    raise SystemExit("value regression must reject an operation that exists only on A::Tick")
if "effect Tick[Left, Right]" not in generic_arity or "effect Tick[Value]" not in generic_arity or \
        "B::Tick[i64, i64].ping" not in generic_arity:
    raise SystemExit("generic regression must distinguish same-leaf effects with different arities")
if "can A::Tick with H" not in ambiguous_bare or "return Tick.ping()" not in ambiguous_bare or \
        "effect Tick:" not in ambiguous_bare:
    raise SystemExit("ambiguous bare regression must not rewrite Tick.ping to A's same-leaf handler")
if "module Util:" not in ambiguous_helper or "can[A::Tick]" not in ambiguous_helper or \
        "return Tick.ping()" not in ambiguous_helper or "can A::Tick with AHandler" not in ambiguous_helper:
    raise SystemExit("helper regression must keep third-module bare Tick ambiguous under A's install")
if "ae_effect_operation_signature_identity(file.enum_annotations, target_identity_id, annotation.name)" not in check_expression and \
        "ae_effect_operation_signature_identity(file.enum_annotations, target_identity_id, annotation.name)" not in semantic:
    raise SystemExit("handler signature validation must remain identity-scoped")
signature_lookup = function_source(signatures, "ae_effect_operation_signature_identity")
if "effect_identity_id == 0" not in signature_lookup or "annotation.identity_id == effect_identity_id" not in signature_lookup:
    raise SystemExit("effect operation signatures must require one exact nonzero effect identity")
if "handler BHandler(value: i64) for Tick[i64]" not in signature_fixture or \
        "B::Tick[i64].ping(41)" not in signature_fixture or \
        "def ping(left: Left, right: Right) -> Left" not in signature_fixture:
    raise SystemExit("signature regression must contrast A and B declarations and call B's qualified operation")

for fragment in (
    "check_effect_operation_identity.py",
    'run_positive "operation_identity_same_leaf_signature.elisa"',
    'run_native_result "operation_identity_same_leaf_signature.elisa" 42',
    'run_negative "operation_identity_same_leaf_missing_call.neg.elisa" \'effect "Tick" has no operation "ping"\'',
    'run_negative "operation_identity_same_leaf_missing_value.neg.elisa" \'effect "Tick" has no operation "ping"\'',
    'run_negative "operation_identity_same_leaf_generic_arity.neg.elisa" \'abstract effect specialization Tick expects 1 type argument(s), got 2\'',
    'run_negative "operation_identity_ambiguous_bare.neg.elisa" \'abstract effect operation Tick.ping requires an installed handler\'',
    'run_negative "helper_ambiguous_bare_operation_identity.neg.elisa" \'abstract effect operation Tick.ping requires an installed handler\'',
):
    if fragment not in smoke:
        raise SystemExit(f"effect smoke is missing operation identity regression: {fragment}")

print("effect operation identity source proof OK")
