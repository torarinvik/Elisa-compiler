"""Signature-contract exclusions must be owned by the exact function offset."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
LAWS = ROOT / "src/semantic/check_refinement_arg_laws.elisa"
BOUNDS = ROOT / "src/semantic/check_refinement_arg_bounds.elisa"
IDENTITY = ROOT / "src/semantic/semantic_signature_contract_identity.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


laws = LAWS.read_text()
bounds = BOUNDS.read_text()
identity = IDENTITY.read_text()
semantic = SEMANTIC.read_text()

helper = function_source(identity, "signature_contract_owner_offset_at")
if 'include "./semantic_signature_contract_identity.elisa"' not in semantic:
    raise SystemExit("semantic module must include the signature-contract identity helper")
if not all(fragment in helper for fragment in (
    "lines.count != kinds.count",
    "lines.count != predicates.count",
    "annotation.owner != \"__signature_contract\"",
    "selected_line == lines[index]",
    "selected_kind == kinds[index]",
    "selected_offset",
)):
    raise SystemExit("owner helper must fail closed on misaligned side tables and validate line/kind markers")

law_walk = function_source(laws, "unproven_arg_walk")
if not all(fragment in law_walk for fragment in (
    "signature_contract_kinds: darray[sview]&",
    "signature_contract_annotations: darray[Ast::EnumAnnotation]&",
    "signature_contract_lines[sig_index] == line.line",
    "signature_contract_owner_offset_at(sig_index, signature_contract_lines, signature_contract_kinds, signature_contract_exprs, signature_contract_annotations) == line.offset",
    "module_body, signature_contract_exprs, signature_contract_lines, signature_contract_kinds, signature_contract_annotations",
    "scoped_body, signature_contract_exprs, signature_contract_lines, signature_contract_kinds, signature_contract_annotations",
)):
    raise SystemExit("refinement-law exclusions must be limited to contracts owned by this function")

guard_walk = function_source(bounds, "guard_interval_walk")
if not all(fragment in guard_walk for fragment in (
    "signature_contract_kinds: darray[sview]&",
    "signature_contract_annotations: darray[Ast::EnumAnnotation]&",
    "signature_contract_lines[sig_index] == line.line",
    "signature_contract_owner_offset_at(sig_index, signature_contract_lines, signature_contract_kinds, signature_contract_exprs, signature_contract_annotations) == line.offset",
    "module_body, signature_contract_exprs, signature_contract_lines, signature_contract_kinds, signature_contract_annotations",
    "scoped_body, signature_contract_exprs, signature_contract_lines, signature_contract_kinds, signature_contract_annotations",
)):
    raise SystemExit("guard-interval exclusions must be limited to contracts owned by this function")

if "file.signature_contract_kinds, file.enum_annotations" not in laws:
    raise SystemExit("entrypoints must supply parser signature-contract identity metadata")
if "file.signature_contract_kinds, file.enum_annotations" not in bounds:
    raise SystemExit("guard-interval entrypoints must supply parser signature-contract identity metadata")
