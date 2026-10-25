"""Bind contract side-table rows to their exact declaration offsets."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
IDENTITY = ROOT / "src/semantic/semantic_signature_contract_identity.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARSER = ROOT / "src/parser/parser_types_function.elisa"
PRECONDITION = ROOT / "src/semantic/check_precondition_violated.elisa"
MULTIPARAM = ROOT / "src/semantic/check_precondition_multiparam.elisa"
CALL_PRECONDITION = ROOT / "src/semantic/check_call_precondition_unproven.elisa"
ENSURES_STRUCTURAL = ROOT / "src/semantic/check_ensures_structural.elisa"
REFINEMENT_IS_LAW = ROOT / "src/semantic/check_refinement_is_law.elisa"
GATE = ROOT / "test/parity/diagnostics_smoke.sh"
ENSURES_ASSIGN = ROOT / "src/semantic/check_ensures_assign_violated.elisa"
REFINEMENT_FACT = ROOT / "src/semantic/check_refinement_fact_invalidated.elisa"
RECURSIVE_ENSURE = ROOT / "src/semantic/check_recursive_affine_ensure.elisa"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


identity = IDENTITY.read_text()
semantic = SEMANTIC.read_text()
parser = PARSER.read_text()
precondition = PRECONDITION.read_text()
multiparam = MULTIPARAM.read_text()
call_precondition = CALL_PRECONDITION.read_text()
ensures_structural = ENSURES_STRUCTURAL.read_text()
refinement_is_law = REFINEMENT_IS_LAW.read_text()
gate = GATE.read_text()
ensures_assign = ENSURES_ASSIGN.read_text()
refinement_fact = REFINEMENT_FACT.read_text()
recursive_ensure = RECURSIVE_ENSURE.read_text()
if 'include "./semantic_signature_contract_identity.elisa"' not in semantic:
    raise SystemExit("semantic module must include the signature-contract identity helper")

lookup = function_source(identity, "signature_contract_owner_offset_at")
if not all(fragment in lookup for fragment in (
    "lines.count != kinds.count",
    "lines.count != predicates.count",
    'annotation.owner != "__signature_contract"',
    "marker_count == index",
    "marker_count != lines.count",
    "selected_line == lines[index]",
    "selected_kind == kinds[index]",
)):
    raise SystemExit("contract-owner lookup must validate aligned rows and the exact marker position")

drain = function_source(parser, "drain_signature_contracts")
if not all(fragment in drain for fragment in (
    "parser.signature_contract_lines <- parser.signature_contract_lines.push(function_line)",
    "parser.signature_contract_kinds <- parser.signature_contract_kinds.push(parser.captured_contract_kinds[parser.position])",
    "parser.signature_contract_exprs <- parser.signature_contract_exprs.push(parser.captured_contract_exprs[parser.position])",
    'owner: "__signature_contract"',
    "offset: function_offset",
)) or "drain_signature_contracts(token.line, token.start)" not in parser:
    raise SystemExit("parser must emit one owner marker in lockstep with each contract row")
function_parser = function_source(parser, "function_declaration")
if "Ast::Decl.Func(function_name, threaded_params, return_type, resolved_body, effects, decorators, Ast::pos_of_token(token))" not in function_parser:
    raise SystemExit("function AST positions must use the same `def` token offset as contract owner markers")

if 'python3 "$REPO_ROOT/test/proofs/check_signature_contract_owner_identity.py"' not in gate:
    raise SystemExit("diagnostics gate must run the signature-contract owner proof")

ensures_check = function_source(ensures_assign, "ensures_assign_check_function")
ensures_walk = function_source(ensures_assign, "ensures_assign_violated_walk")
ensures_entry = function_source(ensures_assign, "check_ensures_assign_violated")
if not all(fragment in ensures_check for fragment in (
    "function_offset: u32",
    "contract_annotations: darray[Ast::EnumAnnotation]&",
    "signature_contract_owner_offset_at(fact_index, contract_lines, contract_kinds, contract_exprs, contract_annotations)",
    "contract_lines[fact_index] == function_line and owner_offset != SIGNATURE_CONTRACT_OFFSET_NONE and owner_offset == function_offset",
    "signature_contract_owner_offset_at(contract_index, contract_lines, contract_kinds, contract_exprs, contract_annotations)",
    "contract_lines[contract_index] == function_line and owner_offset != SIGNATURE_CONTRACT_OFFSET_NONE and owner_offset == function_offset",
)) or not all(fragment in ensures_walk for fragment in (
    "line.line, line.offset, body",
    "contract_annotations",
)) or not all(fragment in ensures_entry for fragment in (
    "file.signature_contract_lines",
    "file.signature_contract_kinds",
    "file.signature_contract_exprs",
    "file.enum_annotations",
)):
    raise SystemExit("ensures assignment consumer must join signature rows to the exact function owner")

refinement_collect = function_source(refinement_fact, "rfi_collect_ensures_positions")
refinement_entry = function_source(refinement_fact, "check_refinement_fact_invalidated")
if not all(fragment in refinement_collect for fragment in (
    "contract_annotations: darray[Ast::EnumAnnotation]&",
    "signature_contract_owner_offset_at(probe, contract_lines, contract_kinds, contract_exprs, contract_annotations)",
    "contract_lines[probe] == line.line and owner_offset != SIGNATURE_CONTRACT_OFFSET_NONE and owner_offset == line.offset",
    "contract_annotations, ensures_functions, ensures_positions",
)) or not all(fragment in refinement_entry for fragment in (
    "file.signature_contract_lines",
    "file.signature_contract_kinds",
    "file.signature_contract_exprs",
    "file.enum_annotations",
)):
    raise SystemExit("refinement invalidation consumer must select ensure rows by exact function owner")

recursive_walk = function_source(recursive_ensure, "check_recursive_affine_ensure_walk")
recursive_entry = function_source(recursive_ensure, "check_recursive_affine_ensure")
if not all(fragment in recursive_walk for fragment in (
    "sig_annotations: darray[Ast::EnumAnnotation]&",
    "signature_contract_owner_offset_at(sig_index, sig_lines, sig_kinds, sig_exprs, sig_annotations)",
    "sig_lines[sig_index] == line.line and owner_offset != SIGNATURE_CONTRACT_OFFSET_NONE and owner_offset == line.offset",
    "check_recursive_affine_ensure_walk(module_body, sig_exprs, sig_kinds, sig_lines, sig_annotations, table)",
    "check_recursive_affine_ensure_walk(scoped_body, sig_exprs, sig_kinds, sig_lines, sig_annotations, table)",
)) or not all(fragment in recursive_entry for fragment in (
    "file.signature_contract_exprs",
    "file.signature_contract_kinds",
    "file.signature_contract_lines",
    "file.enum_annotations",
)):
    raise SystemExit("recursive affine consumer must select ensure rows by exact function owner")

# Function signature-contract consumers must join on the parser's exact owner marker,
# because #line can give multiple function declarations the same displayed line.
fallback_walk = function_source(precondition, "precondition_unproven_walk")
if not all(fragment in fallback_walk for fragment in (
    "signature_contract_kinds: darray[sview]",
    "signature_contract_annotations: darray[Ast::EnumAnnotation]",
    "line.offset",
    "signature_contract_owner_offset_at(sig_index, signature_contract_lines, signature_contract_kinds, signature_contract_exprs, signature_contract_annotations)",
)) or "file.signature_contract_kinds, file.enum_annotations" not in precondition:
    raise SystemExit("coarse function-precondition facts must join contracts to the exact function owner")
# Extern signature rows also use the declaration offset, which stays distinct from the function
# owner checks above even when `#line` maps sibling externs onto one displayed line.
extern_join = function_source(precondition, "collect_preconditions")
if not all(fragment in extern_join for fragment in (
    'signature_contract_kinds[sig_index] == "requires"',
    "signature_contract_owner_offset_at(sig_index, signature_contract_lines, signature_contract_kinds, signature_contract_exprs, signature_contract_annotations) == line.offset",
)):
    raise SystemExit("extern precondition collection must bind requires rows to the exact declaration offset")

signature_lookup = function_source(multiparam, "signature_requires_of")
if not all(fragment in signature_lookup for fragment in (
    "function_offset: u32",
    "contract_annotations: darray[Ast::EnumAnnotation]&",
    "signature_contract_owner_offset_at(probe, contract_lines, contract_kinds, contract_exprs, contract_annotations)",
)):
    raise SystemExit("multi-parameter requires lookup must match the exact function owner")
requires_collection = function_source(multiparam, "collect_requires_signatures")
if not all(fragment in requires_collection for fragment in (
    "contract_annotations: darray[Ast::EnumAnnotation]&",
    "signature_requires_of(line.line, line.offset, contract_lines, contract_kinds, contract_exprs, contract_annotations)",
    "module_body, contract_lines, contract_kinds, contract_exprs, contract_annotations",
    "scoped_body, contract_lines, contract_kinds, contract_exprs, contract_annotations",
)) or "file.signature_contract_exprs, file.enum_annotations" not in multiparam:
    raise SystemExit("multi-parameter traversal must preserve owner markers through nested declarations")

goal_collection = function_source(call_precondition, "cpu_collect")
if not all(fragment in goal_collection for fragment in (
    "sig_annotations: darray[Ast::EnumAnnotation]&",
    "signature_contract_owner_offset_at(sig_probe, sig_lines, sig_kinds, sig_exprs, sig_annotations)",
    "func_line.offset",
    "module_body, sig_lines, sig_kinds, sig_exprs, sig_annotations",
    "scoped_body, sig_lines, sig_kinds, sig_exprs, sig_annotations",
)) or "file.signature_contract_exprs, file.enum_annotations" not in call_precondition:
    raise SystemExit("call-precondition goals must join and propagate exact function owner markers")

# Structural ensures checks use some contract facts to inspect the owning function's parameters;
# those joins need the marker offset. The law-name check below validates each row in isolation.
subject_lookup = function_source(ensures_structural, "ens_subject_is_param")
if not all(fragment in subject_lookup for fragment in (
    "func_offset: u32",
    "line.line == func_line and line.offset == func_offset",
    "ens_subject_is_param(module_body, func_line, func_offset, subject)",
    "ens_subject_is_param(scoped_body, func_line, func_offset, subject)",
)):
    raise SystemExit("structural ensures subject lookup must use the exact declaring function offset")
function_name_lookup = function_source(ensures_structural, "ens_func_name_at")
if not all(fragment in function_name_lookup for fragment in (
    "func_offset: u32 = SIGNATURE_CONTRACT_OFFSET_NONE",
    "line.line == func_line and (func_offset == SIGNATURE_CONTRACT_OFFSET_NONE or line.offset == func_offset)",
)):
    raise SystemExit("structural ensures diagnostics must support exact function-owner names while preserving typestate line lookups")
structural_scan = function_source(ensures_structural, "check_ensures_structural")
if not all(fragment in structural_scan for fragment in (
    "signature_contract_owner_offset_at(index, file.signature_contract_lines, file.signature_contract_kinds, file.signature_contract_exprs, file.enum_annotations)",
    "contract_owner_offset != SIGNATURE_CONTRACT_OFFSET_NONE",
    "ens_subject_is_param(file.top_decls, contract_line, contract_owner_offset, subject)",
    "ens_func_name_at(file.top_decls, contract_line, contract_owner_offset)",
)):
    raise SystemExit("structural ensures rows must resolve their exact function before checking parameter subjects")

row_checker = function_source(refinement_is_law, "check_ensures_refinement")
if not all(fragment in row_checker for fragment in (
    "while index < file.signature_contract_exprs.count",
    "file.signature_contract_kinds[index]",
    "file.signature_contract_exprs[index]",
    "file.signature_contract_lines[index]",
)) or "ens_subject_is_param" in row_checker or "Decl.Func" in row_checker:
    raise SystemExit("refinement law checks must continue validating each contract predicate row independently")
