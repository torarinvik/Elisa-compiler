"""Keep backend alias metadata limited to proven formal-parameter disjointness."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
METADATA = ROOT / "src/backend/codegen_alias_metadata.elisa"
CONVERT = ROOT / "src/backend/codegen_convert.elisa"
MODULE = ROOT / "src/backend/codegen_module.elisa"


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


metadata = METADATA.read_text()
convert = CONVERT.read_text()
module = MODULE.read_text()
for forbidden in ("darray_element_and_header_scopes", "tag_darray_header_access",
                  '"elisa.darray.aa"', '"hdr"', '"elt"'):
    if forbidden in metadata or forbidden in convert:
        raise SystemExit(f"unsound generic DArray scope marker remains: {forbidden}")

body = function_section(metadata, "tag_disjoint_darray_access")
required = (
    "alias_metadata: mutable darray[LLVMMetadataRef] = [runtime.disjoint_scope_refs[own_scope_slot.usize()]]",
    "noalias_metadata: mutable darray[LLVMMetadataRef] = []",
    "noalias_metadata.push(runtime.disjoint_scope_refs[scope_slot]) if scope_slot != own_scope_slot.usize()",
    'set_metadata_list(inst, "alias.scope", 11, alias_metadata, ctx)',
    'set_metadata_list(inst, "noalias", 7, noalias_metadata, ctx)',
)
for fragment in required:
    if fragment not in body:
        raise SystemExit(f"proven formal-scope metadata behavior missing: {fragment}")
if "element_scope" in body or "header_scope" in body:
    raise SystemExit("formal scope lists still include a generic DArray category")

cleanup = function_section(metadata, "remove_external_disjoint_scope_metadata")
required_cleanup = (
    'alias_scope_kind: u32 = LLVMGetMDKindIDInContext(ctx, "alias.scope", 11)',
    'noalias_kind: u32 = LLVMGetMDKindIDInContext(ctx, "noalias", 7)',
    "linkage != 8 and linkage != 9",
    "LLVMSetMetadata(instruction, alias_scope_kind, zeroed)",
    "LLVMSetMetadata(instruction, noalias_kind, zeroed)",
)
for fragment in required_cleanup:
    if fragment not in cleanup:
        raise SystemExit(f"external function alias metadata cleanup missing: {fragment}")
core = function_section(module, "emit_module_core")
cleanup_call = "remove_external_disjoint_scope_metadata(m, ctx) if structs.target.noalias_mutable_refs"
if core.count(cleanup_call) != 1 or core.find(cleanup_call) < core.rfind("emit_export_wrapper"):
    raise SystemExit("external alias metadata must be stripped after final function linkage")
print("backend alias metadata policy is soundly restricted to proven formal scopes")
