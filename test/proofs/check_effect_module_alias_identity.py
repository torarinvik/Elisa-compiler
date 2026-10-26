"""Guard chained module-alias resolution for effect declaration identities."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER_ID = (ROOT / "src/parser/parser_effect_identity.elisa").read_text(encoding="utf-8")
PARSER_EXPR = (ROOT / "src/parser/parser_expr_postfix.elisa").read_text(encoding="utf-8")
PARSER_INSTALL = (ROOT / "src/parser/parser_stmt_control_blocks.elisa").read_text(encoding="utf-8")
PARSER_HANDLER = (ROOT / "src/parser/parser_decl_handler.elisa").read_text(encoding="utf-8")
PARSER_CORE = (ROOT / "src/parser/parser_core.elisa").read_text(encoding="utf-8")
PARSER_CTOR = (ROOT / "src/parser/parser_core_member_tables.elisa").read_text(encoding="utf-8")
PARSER_ENTRY = (ROOT / "src/parser/parser_types_entry.elisa").read_text(encoding="utf-8")
PARSER_SPECIALIZATION = (ROOT / "src/parser/parser_effect_specialization.elisa").read_text(encoding="utf-8")
SEMANTIC_REF = (ROOT / "src/semantic/check_effect_declarations.elisa").read_text(encoding="utf-8")
SEMANTIC_INDEX = (ROOT / "src/semantic/check_abstract_effects.elisa").read_text(encoding="utf-8")
SMOKE = (ROOT / "test/parity/effect_handler_stage1_smoke.sh").read_text(encoding="utf-8")
FIXTURE = (ROOT / "test/fixtures/effects/chained_module_alias_effect_identity.elisa").read_text(encoding="utf-8")


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing effect alias identity helper {name}")
    return match.group(0)


alias_row = function_source(PARSER_ID, "effect_alias_target_at")
alias_path = function_source(PARSER_ID, "effect_alias_path_matches_owner")
identity = function_source(PARSER_ID, "effect_identity_for_reference")
install_identity = function_source(PARSER_SPECIALIZATION, "effect_install_effect_identity_at")
lexical_rank = function_source(PARSER_ID, "effect_lexical_module_rank")
if not all(fragment in alias_row for fragment in (
    'alias.name != "__using_alias"',
    "effect_alias_precedes_requester",
    "continue if not before_requester.known or not before_requester.precedes",
    'marker.owner == "__static_if_branch"',
    'marker.name == "__using_alias_static_branch"',
    'target_row.name == "__using_alias_target"',
)):
    raise SystemExit("parser alias selection must honor the use-site cutoff and fail closed for uncertain or unpaired aliases")
if not all(fragment in alias_path for fragment in (
    "alias_name: sview = path[0:separator]",
    "suffix: sview = path[separator + separator_width:path.len]",
    "owner_prefix <- module_owner[0:tail_start]",
    "alias.target_module",
    "alias.target_offset",
)):
    raise SystemExit("parser alias identity must expand the first alias path component and preserve nested module suffixes")
if identity.find("effect_lexical_module_rank(") > identity.find("effect_alias_path_matches_owner(") or \
        identity.find("effect_alias_path_matches_owner(") > identity.find("parser.effect_identity_owners[index] == namespace"):
    raise SystemExit("qualified effect identity must prefer complete lexical candidates, then visible aliases, then root raw paths")
if "lexical_ambiguous" not in identity or "alias_ambiguous" not in identity or \
        "return 0 if not path_match.known" not in identity:
    raise SystemExit("parser effect alias resolution must fail closed when a visible alias is ambiguous")
if "effect_declarations_complete: mutable bool" not in PARSER_CORE or \
        "effect_declarations_complete: false" not in PARSER_CTOR or \
        identity.find("return 0 if not parser.effect_declarations_complete") < 0 or \
        identity.find("return 0 if not parser.effect_declarations_complete") > identity.find("if namespace != \"\"") or \
        "parser.effect_declarations_complete <- true" not in PARSER_ENTRY or \
        PARSER_ENTRY.find("parser <- parser.lower_protocol_parameters(&top_items)") > PARSER_ENTRY.find("parser.effect_declarations_complete <- true") or \
        PARSER_ENTRY.find("parser.effect_declarations_complete <- true") > PARSER_ENTRY.find("parser.materialize_effect_type_references()"):
    raise SystemExit("bare and qualified parser effect identities must wait until the complete declaration scan")
if not all(fragment in install_identity for fragment in (
    "parser.effect_declarations_complete",
    'annotation.owner == "__effect_install_effect"',
    "annotation.line == install_line",
    "annotation.offset == install_offset",
    "annotation.module",
    "annotation.occurrence_offset",
    "parser.effect_identity_for_reference",
)):
    raise SystemExit("post-parse installation consumers must lazily resolve deferred IDs at the original module and source offset")
if "prefix_length + 2.usize() + namespace.len" not in lexical_rank:
    raise SystemExit("lexical effect lookup must test the complete namespace path at each ancestor")

operation_record = function_source(PARSER_EXPR, "record_effect_operation_ref")
if "effect_identity_for_reference(head_text, lexical_owner, token.start)" not in operation_record:
    raise SystemExit("operation heads must resolve aliases using their exact source-use offset")
if 'effect_identity_for_reference(effect_ref, parser.current_module, effect_start_token.start)' not in PARSER_INSTALL or \
        'occurrence_offset: effect_start_token.start' not in PARSER_INSTALL:
    raise SystemExit("effect installation metadata must keep its join offset and the exact alias lookup offset")
if not all(fragment in PARSER_HANDLER for fragment in (
    "effect_identity_for_reference(effect_ref, parser.current_module, effect_start_token.start)",
    "detail_line: effect_start_token.line",
    "offset: effect_start_token.start",
)):
    raise SystemExit("handler targets must retain exact source line/offset for alias resolution")

semantic_identity = function_source(SEMANTIC_REF, "ae_effect_identity_for_ref")
if semantic_identity.find("ae_effect_index_relative_module_identity(") > semantic_identity.find("binding_module_alias_row_before(") or \
        semantic_identity.find("binding_module_alias_row_before(") > semantic_identity.find("ae_effect_index_module_identity(index, namespace, family)"):
    raise SystemExit("semantic effect identity must use lexical, visible-alias, and root-raw precedence")
if "binding_resolve_module_alias_target(namespace, requester, table)" not in semantic_identity or \
        "BINDING_MODULE_ALIAS_ROW_AMBIGUOUS" not in semantic_identity or \
        "ae_effect_index_module_identity(index, canonical_namespace, family)" not in semantic_identity:
    raise SystemExit("semantic effect lookup must reuse the position-aware alias resolver and preserve ambiguity")
if "ae_effect_identity_for_ref(index, effect_ref, requester.module, source_requester, table)" not in SEMANTIC_INDEX or \
        "requester.occurrence_offset" not in SEMANTIC_INDEX:
    raise SystemExit("semantic operation/install/handler indexing must pass the exact request position to alias resolution")

if not all(fragment in FIXTURE for fragment in (
    "module Backend:",
    "module Effects:",
    "using Backend as BackendRoot",
    "using BackendRoot as First",
    "using First as Fx",
    "handler Noop() for Fx::Effects::Tick:",
    "can Fx::Effects::Tick with Noop:",
    "return Fx::Effects::Tick.ping()",
    "return 42",
)):
    raise SystemExit("fixture must exercise a chained alias with a nested path for target, install, and operation lookup")
late_duplicate = (ROOT / "test/fixtures/effects/late_duplicate_bare_operation_identity.neg.elisa").read_text(encoding="utf-8")
if not all(fragment in late_duplicate for fragment in (
    "module A:",
    "effect Tick:",
    "module Client:",
    "can A::Tick with H:",
    "return Tick.ping()",
    "module B:",
    "effect Tick:",
)):
    raise SystemExit("order regression must leave a bare operation reference before a later same-leaf effect declaration")
if not (late_duplicate.find("module A:") < late_duplicate.find("module Client:") < late_duplicate.find("module B:")):
    raise SystemExit("the duplicate effect declaration must follow the bare reference in the parser regression")
late_nested = (ROOT / "test/fixtures/effects/late_nested_effect_identity.neg.elisa").read_text(encoding="utf-8")
if not all(fragment in late_nested for fragment in (
    "module A:",
    "effect Tick:",
    "def ping() -> i64",
    "module Client:",
    "handler H() for A::Tick:",
    "can A::Tick with H:",
    "return A::Tick.ping()",
    "module A:",
    "def ping() -> bool",
)):
    raise SystemExit("qualified effect regression must place an incompatible nested lexical shadow after the earlier root-qualified use")
if not (late_nested.find("module A:") < late_nested.find("module Client:") < late_nested.rfind("module A:")):
    raise SystemExit("the nested effect declaration must follow the qualified reference in its lexical parent")
if 'check_effect_module_alias_identity.py' not in SMOKE or \
        'run_positive "chained_module_alias_effect_identity.elisa"' not in SMOKE or \
        'run_negative "late_duplicate_bare_operation_identity.neg.elisa"' not in SMOKE or \
        'run_negative "late_nested_effect_identity.neg.elisa"' not in SMOKE or \
        'run_zero_overhead_ir "chained_module_alias_effect_identity.elisa"' not in SMOKE or \
        'run_native_result "chained_module_alias_effect_identity.elisa" 42' not in SMOKE:
    raise SystemExit("effect smoke must compile, check zero-overhead lowering, and execute the chained alias fixture")

print("effect module alias identity source proof OK")
