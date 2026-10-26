"""Guard indexed effect-install and operation-site annotation lookup."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SEMANTIC = ROOT / "src/semantic/check_abstract_effects.elisa"
OPERATION_HEADS = ROOT / "src/semantic/check_effect_operation_heads.elisa"
SMOKE = ROOT / "test/parity/effect_handler_stage1_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing indexed effect helper {name}")
    return match.group(0)


semantic = SEMANTIC.read_text()
operation = OPERATION_HEADS.read_text()
smoke = SMOKE.read_text()

for field in (
    "lines: mutable darray[u32]",
    "offsets: mutable darray[u32]",
    "handler_ids: mutable darray[u32]",
    "effect_ids: mutable darray[u32]",
    "capture_counts: mutable darray[u32]",
    "identity_mismatches: mutable darray[bool]",
    "target_effect_ids: mutable darray[u32]",
    "target_annotation_rows: mutable darray[u32]",
    "offsets_ordered: mutable bool = true",
):
    if field not in semantic:
        raise SystemExit(f"install summary index is missing {field}")

position_lookup = function_source(semantic, "ae_install_position_index_at")
if "low: mutable usize" not in position_lookup or \
        "index.offsets[middle] < offset" not in position_lookup or \
        "index.lines[low] == line" not in position_lookup or \
        "index.lines[row] == line and index.offsets[row] == offset" not in position_lookup:
    raise SystemExit("install lookup must lower-bound offsets and confirm the full line/offset key")

summary_builder = function_source(semantic, "ae_effect_install_position_index")
for marker in (
    'annotation.owner != "__effect_install"',
    'annotation.owner == "__effect_install_effect"',
    'annotation.owner == "__effect_install_capture_count"',
    'annotation.owner == "__effect_install_identity_mismatch"',
    "ae_install_position_index_at(index, annotation.line, annotation.offset)",
    "handlers.target_annotation_rows[handler_row]",
):
    if marker not in summary_builder:
        raise SystemExit(f"install summaries must join marker by exact source position: {marker}")

handler_builder = function_source(semantic, "ae_handler_semantic_index")
if "annotation.identity_id" not in handler_builder or \
        "realization_heads" not in handler_builder or \
        "realization_next" not in handler_builder or \
        "target_effect_ids[handler_row]" not in handler_builder:
    raise SystemExit("handler target, capture, and realization rows must be indexed by exact handler ID")

collector = function_source(semantic, "ae_collect_install_statements")
for marker in (
    "ae_install_position_index_at(installs, statement_pos.line, statement_pos.offset)",
    "installs.target_effect_ids[install_row.usize()]",
    "ae_handler_realization_head(handlers, handler_identity_id)",
    "handlers.realization_next[realization_row.usize()]",
):
    if marker not in collector:
        raise SystemExit(f"install collection must use indexed rows: {marker}")
if "for annotation in annotations" in collector:
    raise SystemExit("an install must not scan every annotation for its handler realization rows")

validation = semantic[semantic.index('if annotation.owner == "__effect_install":'):]
if "ae_handler_index_required_captures(handler_index, handler_identity_id)" not in validation or \
        "install_index.capture_counts[install_row.usize()]" not in validation or \
        "install_index.identity_mismatches[install_row.usize()]" not in validation:
    raise SystemExit("install diagnostics must consume the precomputed summary")
if "ae_install_effect_at(" in semantic or "ae_install_capture_count_after(" in semantic:
    raise SystemExit("the old full-table install/capture lookup helpers must be removed")

operation_lookup = function_source(operation, "ae_operation_ref_site")
if "ae_effect_operation_site_hash(member, position.line, position.offset)" not in operation_lookup or \
        "sites.operation_heads.get(key)" not in operation_lookup or \
        "annotation.line == position.line and annotation.offset == position.offset" not in operation_lookup:
    raise SystemExit("operation references must use an exact indexed source position and member")
if "for annotation in annotations" in operation_lookup:
    raise SystemExit("operation-site lookup must not rescan the annotation slice")
mismatch_lookup = function_source(operation, "ae_specialization_mismatch_at_site")
if "sites.mismatch_heads.get(key)" not in mismatch_lookup or \
        "annotation.line == line and annotation.offset == offset" not in mismatch_lookup:
    raise SystemExit("specialization mismatch lookup must use the exact indexed source position")
family_lookup = function_source(semantic, "ae_effect_family_indexed")
if "index.family_heads.get(family_hash)" not in family_lookup or "index.names[row.usize()] == family" not in family_lookup:
    raise SystemExit("operation-family presence must use exact indexed names")
if "ae_effect_family_has_declaration" in operation:
    raise SystemExit("operation checks must not retain the full-table family scan")

for marker in (
    "ae_effect_declaration_identity_index(file.enum_annotations, effect_identity_index)",
    "ae_effect_operation_identity_index(file.enum_annotations, effect_identity_index)",
    "ae_effect_operation_position_index(file.enum_annotations, effect_identity_index, operation_index, table)",
    "ae_effect_install_position_index(file.enum_annotations, effect_identity_index, handler_index, install_index, table)",
    "ae_check_declarations(file.top_decls, expression_annotations, operation_index, effect_identity_index, table)",
):
    if marker not in semantic:
        raise SystemExit(f"semantic entry point must build and thread the indexes once: {marker}")
if "check_effect_install_annotation_index.py" not in smoke:
    raise SystemExit("effect smoke must run the annotation-index source proof")

print("effect install annotation index source proof OK")
