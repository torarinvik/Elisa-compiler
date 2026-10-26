"""Guard handler target/signature joins against same-leaf module collisions."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
AST_ANNOTATIONS = ROOT / "src/parser/ast_side_tables.elisa"
PARSER_DECL = ROOT / "src/parser/parser_decl_handler.elisa"
PARSER_EFFECTS = ROOT / "src/parser/parser_decl_named_block.elisa"
PARSER_INSTALL = ROOT / "src/parser/parser_stmt_control_blocks.elisa"
PARSER_SPECIALIZATION = ROOT / "src/parser/parser_effect_specialization.elisa"
SEMANTIC_DECLS = ROOT / "src/semantic/check_effect_declarations.elisa"
SEMANTIC_SIGNATURES = ROOT / "src/semantic/check_effect_signatures.elisa"
SEMANTIC_HANDLERS = ROOT / "src/semantic/check_effect_handlers.elisa"
SEMANTIC_EFFECTS = ROOT / "src/semantic/check_abstract_effects.elisa"
FIXTURE = ROOT / "test/fixtures/effects/handler_same_leaf_effect_identity.elisa"
NEGATIVE = ROOT / "test/fixtures/effects/handler_unresolved_effect_target_identity.neg.elisa"
SMOKE = ROOT / "test/parity/effect_handler_stage1_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing effect identity helper {name}")
    return match.group(0)


parser_decl = PARSER_DECL.read_text()
rewrite_members = function_source(parser_decl, "rewrite_handler_members")
parser_effects = PARSER_EFFECTS.read_text()
parser_install = PARSER_INSTALL.read_text()
parser_specialization = PARSER_SPECIALIZATION.read_text()
semantic_decls = SEMANTIC_DECLS.read_text()
semantic_signatures = SEMANTIC_SIGNATURES.read_text()
semantic_handlers = SEMANTIC_HANDLERS.read_text()
semantic_effects = SEMANTIC_EFFECTS.read_text()
fixture = FIXTURE.read_text()
negative = NEGATIVE.read_text()
smoke = SMOKE.read_text()

if "referenced_identity_id: u32 = 0" not in AST_ANNOTATIONS.read_text():
    raise SystemExit("annotation rows need a separate target-effect identity field")
if 'owner: "__effect_decl", name: effect_name, line: token.line, module: parser.current_module, identity_id: effect_identity_id' not in parser_effects:
    raise SystemExit("effect declaration rows must retain module and stable effect identity")
if 'line: 3900000084, detail_line: effect_start_token.line, module: parser.current_module, identity_id: handler_identity_id, referenced_identity_id: target_effect_identity_id, offset: effect_start_token.start' not in parser_decl:
    raise SystemExit("handler target rows must preserve the effect ID separately from the handler ID")
if "detail_line: effect_start_token.line" not in parser_decl or "offset: effect_start_token.start" not in parser_decl:
    raise SystemExit("handler target rows must retain the exact alias-resolver requester position")
if 'line: 3900000087, module: parser.current_module, identity_id: handler_identity_id, referenced_identity_id: method_effect_identity_id' not in parser_decl:
    raise SystemExit("handler realization rows must retain the identity of each method effect")
if "shadowed_by_operation_arg: bool = any operation_parameter in method_params where operation_parameter.name == capture.name" not in rewrite_members or \
        "duplicate_capture_name: bool = any previous_capture_name in capture_names_seen where previous_capture_name == capture.name" not in rewrite_members or \
        "if shadowed_by_operation_arg and not duplicate_capture_name" not in rewrite_members or \
        "parser.handler_capture_name(handler_name, method_line.line)" not in rewrite_members or \
        "parameters.extend(method_params)" not in rewrite_members:
    raise SystemExit("lowered handler captures must retain a distinct binding owner when an operation parameter shadows them")

resolve = function_source(semantic_decls, "ae_effect_identity_for_ref")
if "EffectDeclarationIdentityIndex&" not in resolve or \
        "ae_effect_index_relative_module_identity(index, lexical_owner, prefix_length, namespace, family)" not in resolve or \
        "binding_module_alias_row_before(alias_head, requester, table)" not in resolve or \
        "binding_resolve_module_alias_target(namespace, requester, table)" not in resolve or \
        "ae_effect_index_module_identity(index, canonical_namespace, family)" not in resolve or \
        "ae_effect_index_module_identity(index, namespace, family)" not in resolve or \
        "ae_effect_identity_from_index(index, effect_ref, lexical_owner)" not in resolve:
    raise SystemExit("forward and alias-qualified effect references must use exact indexed candidates and fail closed on ambiguity")
for helper in ("ae_effect_identity_declared", "ae_operation_declared_identity"):
    source = function_source(semantic_decls, helper)
    if "effect_identity_id == 0" not in source or "annotation.identity_id == effect_identity_id" not in source:
        raise SystemExit(f"effect lookup must require one exact nonzero identity: {helper}")
for helper in ("ae_effect_operation_signature_identity", "ae_effect_generic_names_identity"):
    source = function_source(semantic_signatures, helper)
    if "effect_identity_id == 0" not in source or "annotation.identity_id == effect_identity_id" not in source:
        raise SystemExit(f"signature/generic rows must be scoped to one effect identity: {helper}")

target_index = function_source(semantic_effects, "ae_handler_semantic_index")
if "annotation.referenced_identity_id" not in target_index or \
        "ae_effect_identity_at_request(annotations, effects, annotation.name, annotation.referenced_identity_id, annotation, table)" not in target_index or \
        "index.target_effect_ids[handler_row]" not in target_index:
    raise SystemExit("handler target index must preserve both identities and resolve forward targets")
request_resolution = function_source(semantic_effects, "ae_effect_identity_at_request")
if "ae_effect_identity_for_ref(index, effect_ref, requester.module, source_requester, table)" not in request_resolution or \
        "requester.detail_line" not in request_resolution or \
        "requester.occurrence_offset" not in request_resolution or \
        "ae_effect_identity_index_declared(index, identity_id)" not in request_resolution:
    raise SystemExit("qualified target fallback must use the exact alias requester and a declared effect ID")
qualified_branch = request_resolution.find("if ae_effect_reference_is_qualified(effect_ref):")
alias_resolution = request_resolution.find("ae_effect_identity_for_ref(index, effect_ref, requester.module, source_requester, table)")
raw_index_resolution = request_resolution.find("ae_effect_identity_from_index(index, effect_ref, requester.module)")
if qualified_branch < 0 or not qualified_branch < alias_resolution < raw_index_resolution or \
        "else:\n                        identity_id <- ae_effect_identity_from_index(index, effect_ref, requester.module)" not in request_resolution:
    raise SystemExit("qualified zero-ID references must fail through alias resolution, never revive a raw namespace match")
target_identity = function_source(semantic_effects, "ae_handler_index_target_effect_id")
if "handler_identity_id == 0" not in target_identity or "index.target_effect_ids" not in target_identity:
    raise SystemExit("handler target lookup must fail closed on missing handler identity")
for fragment in (
    "target_identity_known: bool = ae_effect_identity_index_declared(effect_identity_index, target_identity_id)",
    "operation_known: bool = ae_effect_operation_index_declared(effect_identity_index, target_identity_id, annotation.name)",
    "ae_effect_operation_signature_identity(file.enum_annotations, target_identity_id, annotation.name)",
    "ae_effect_generic_names_identity(file.enum_annotations, target_identity_id)",
):
    if fragment not in semantic_effects:
        raise SystemExit(f"handler validation must use the target effect ID: {fragment}")

if "target_matches_install: bool = target_identity_id != 0 and installed_identity_id != 0 and target_identity_id == installed_identity_id and ae_effect_ref_same_specialization(target_ref, installed)" not in semantic_effects:
    raise SystemExit("install authority must require a resolved matching effect identity and specialization")
if "handler_target_identity_id == installed_effect_identity_id and effect_template_row_matches(handler_target_ref, installed_effect_ref)" not in parser_specialization:
    raise SystemExit("clone authority propagation must require the installed target identity too")
if "method_effect_identity_id: u32 = handler_annotation.referenced_identity_id if handler_annotation.referenced_identity_id != 0 else parser.effect_identity_for_reference(handler_annotation.name, handler_annotation.module, handler_annotation.offset)" not in parser_install or \
        "is_abstract: bool = method_effect_identity_id != 0" not in parser_install:
    raise SystemExit("parser realization classification must not match another module's same-leaf effect")
if "method_effect_identity_id: u32 = handler_annotation.referenced_identity_id if handler_annotation.referenced_identity_id != 0 else parser.effect_identity_for_reference(handler_annotation.name, handler_annotation.module, handler_annotation.offset)" not in parser_specialization:
    raise SystemExit("effect clone residual requirements must classify method effects by identity")

if not all(fragment in fixture for fragment in (
    "effect Tick[Left, Right]:",
    "effect Tick[Value]:",
    "handler AHandler(left: i64, right: i64) for Tick[i64, i64] via Console.Write:",
    "handler BHandler(value: i64) for Tick[i64] via Global.Read:",
    "return Tick.ping(41)",
    "can B::Tick[i64], Global.Read:",
    "return B::run()",
)):
    raise SystemExit("same-leaf fixture must separate signature/generic rows and handler via permissions")
if "Missing::Tick" not in negative or "effect Tick:" not in negative:
    raise SystemExit("negative fixture must reject an unresolved qualified effect despite a matching leaf")
if "check_effect_target_identity.py" not in smoke or \
        'run_positive "handler_same_leaf_effect_identity.elisa"' not in smoke or \
        'run_native_result "handler_same_leaf_effect_identity.elisa" 42' not in smoke or \
        'run_zero_overhead_ir "handler_same_leaf_effect_identity.elisa"' not in smoke or \
        'run_negative "handler_unresolved_effect_target_identity.neg.elisa" \'unknown interface "Tick"\'' not in smoke:
    raise SystemExit("effect smoke must exercise exact target signatures, authority isolation, and unresolved targets")

print("effect target identity source proof OK")
