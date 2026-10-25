"""Keep semantic allocation consumers joined to exact token/source-span metadata."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCAL = (ROOT / "src/semantic/check_local_region_annotation.elisa").read_text()
LOCAL_ENTRY = (ROOT / "src/semantic/check_local_region_annotation_entry.elisa").read_text()
TRANSFER = (ROOT / "src/semantic/check_thread_transfer_provenance.elisa").read_text()
PACKED = (ROOT / "src/semantic/check_packed_move_store.elisa").read_text()
DESTROYED = (ROOT / "src/semantic/check_destroyed_region/lambda_dependencies.elisa").read_text()
SMOKE = (ROOT / "test/parity/allocation_region_offset_smoke.sh").read_text()
FIXTURE = (ROOT / "test/repro/allocation_region_offset_line0.elisa").read_text()
STRUCT_FIELD_FIXTURE = (ROOT / "test/repro/region_new_struct_field_auto_read.elisa").read_text()
REFERENCE_FIELD_FIXTURE = (ROOT / "test/repro/allocation_region_struct_field_escape.elisa").read_text()


def function_source(source: str, name: str) -> str:
    marker = f"def {name}("
    start = source.find(marker)
    if start < 0:
        raise SystemExit(f"missing allocation-consumer helper {name}")
    end = source.find("\n        def ", start + len(marker))
    if end < 0:
        end = source.find("\n    public:", start + len(marker))
    return source[start:end if end >= 0 else len(source)]


call_span = function_source(LOCAL, "allocation_regions_in_call_span")
expression = function_source(LOCAL, "allocation_regions_in_expression")
expression_end = function_source(LOCAL, "allocation_expression_end_offset")
local_dependencies = function_source(LOCAL, "walk_local_region_dependencies")
local_assignments = function_source(LOCAL, "check_region_assignment_statements")
statement_allocation = function_source(LOCAL, "region_expression_or_statement_has_recorded_allocation")
recorded_allocations = function_source(LOCAL, "region_expression_recorded_allocations")
thread_allocations = function_source(TRANSFER, "transfer_allocation_regions")
thread_walk = function_source(TRANSFER, "walk_transfer_statements")
packed_call = function_source(PACKED, "packed_call_enclosing_allocation")
packed_check = function_source(PACKED, "check_frozen_packed_allocation")
destroyed_walk = function_source(DESTROYED, "walk_destroyed_region_statements")
destroyed_lambda_body = function_source(DESTROYED, "destroyed_validate_lambda_body")

for fragment in (
    'annotation.owner == "__call_source_span" and annotation.offset == call_pos.offset',
    "allocation_offset >= span.offset and allocation_offset < span.end_offset",
    "allocation_region_is_inline_effect_row(regions, offsets, row_index)",
):
    if fragment not in call_span:
        raise SystemExit(f"call allocation lookup is missing exact-span filtering: {fragment}")

if "allocation_regions_in_call_span(call_pos" not in expression or "Ast::expr_pos(expression)" not in expression:
    raise SystemExit("allocation traversal must use the call's recorded source span")
if "Expr.Lambda(_, _, _):\n                        pass" not in expression or "Expr.Lambda(_, _, _):\n                        pass" not in expression_end:
    raise SystemExit("allocation source walks must leave deferred lambda bodies to their own statement analysis")
if "walk_destroyed_region_statements(lambda_body, scoped_annotations, allocation_regions, allocation_lines, allocation_offsets, call_spans" not in destroyed_lambda_body:
    raise SystemExit("destroyed-region lambda validation must analyze deferred statements with their own source offsets")
if "allocation_region_at(allocation_regions, allocation_lines" in local_dependencies or "allocation_region_at(allocation_regions, allocation_lines" in local_assignments:
    raise SystemExit("local-region consumers still join allocations by logical line")
if not all(fragment in local_dependencies for fragment in (
    "region_expression_is_direct_allocation(value, region)",
    "region_expression_or_statement_has_recorded_allocation(value, region, line.offset, value_end_offset, allocation_regions, allocation_lines, allocation_offsets, call_spans)",
    "region_expression_or_statement_has_recorded_allocation(returned, region, line.offset, return_end_offset, allocation_regions, allocation_lines, allocation_offsets, call_spans)",
)):
    raise SystemExit("local-region binding taint must distinguish direct and source-recorded allocations")
if "allocation_source_interval_has_region(statement_start, statement_end" not in statement_allocation or "allocation_expression_end_offset(value, call_spans)" not in local_dependencies or "allocation_expression_end_offset(return_value, call_spans)" not in local_assignments:
    raise SystemExit("local-region binding taint must retain allocation rows hidden by struct-literal lowering")
if "Expr.Construct(type_expression, fields, _) | Expr.RecordUpdate(type_expression, fields, _)" not in expression_end or "allocation_expression_end_offset(field.value, call_spans)" not in expression_end:
    raise SystemExit("initializer end calculation must include hidden allocations in record fields")
if "region_expression_recorded_allocations(return_value, line.offset, return_end_offset" not in local_assignments or "for temporary_region in return_allocations" not in local_assignments or "allocation_regions_in_source_interval(statement_start, statement_end" not in recorded_allocations:
    raise SystemExit("return escape checks must consider every allocation in the bounded return interval")
if "allocation_region_offsets" not in LOCAL_ENTRY or "file.enum_annotations" not in LOCAL_ENTRY:
    raise SystemExit("local-region entry must pass both the offset column and call-span annotations")

if "allocation_regions_in_expression(value, allocation_names, allocation_lines, allocation_offsets, call_spans, out)" not in thread_allocations or "allocation_regions_in_source_interval(statement_start, statement_end" not in thread_allocations:
    raise SystemExit("thread transfer must query allocation offsets from the value expression")
if "allocation_expression_end_offset(value, call_spans)" not in thread_walk or "transfer_allocation_regions(value, line.offset, value_end_offset, allocation_names, allocation_lines, allocation_offsets, call_spans, allocations)" not in thread_walk:
    raise SystemExit("thread transfer declarations must use source-aware allocation lookup")
if "file.allocation_region_offsets" not in TRANSFER or "file.enum_annotations" not in TRANSFER:
    raise SystemExit("thread transfer entry must pass allocation offsets and call-span annotations")

if "allocation_offset >= span.offset and allocation_offset < span.end_offset" not in packed_call or "allocation_offset < span.offset" not in packed_call or "allocation_expression_end_offset(value, call_spans)" not in PACKED:
    raise SystemExit("packed constructor allocation lookup must use a bounded source span")
if "allocation_offset >= argument_pos.offset and allocation_offset < argument_end" not in packed_call or "allocation_offset >= span.offset and allocation_offset < argument_pos.offset" not in packed_call or "allocation_expression_end_offset(argument, call_spans)" not in packed_call:
    raise SystemExit("packed constructor lookup must exclude allocations inside argument expressions")
if "allocation_region_at(allocation_regions, allocation_lines, line.line)" in packed_check:
    raise SystemExit("packed move/store still joins allocations by logical line")
if "allocation_offsets" not in PACKED or "file.enum_annotations" not in PACKED:
    raise SystemExit("packed move/store entry must pass allocation offsets and call-span annotations")

if "region_expression_recorded_allocations(value, line.offset, allocation_expression_end_offset(value, call_spans), allocation_regions, allocation_lines, allocation_offsets, call_spans, recorded_regions)" not in destroyed_walk:
    raise SystemExit("destroyed-region lambda dependencies still join allocations by logical line")
if "file.allocation_region_offsets, file.enum_annotations" not in DESTROYED:
    raise SystemExit("destroyed-region traversal must thread allocation offsets and call-span annotations")

if "check_allocation_region_consumers.py" not in SMOKE or "allocation_region_offset_line0.elisa" not in SMOKE or "allocation_region_struct_field_escape.elisa" not in SMOKE:
    raise SystemExit("allocation-offset smoke must include the semantic proof and line-zero regression")
if "#line 0" not in FIXTURE or "new[first]" not in FIXTURE or "new[second]" not in FIXTURE:
    raise SystemExit("line-zero fixture must cover two source-distinct named allocations")
if "Box{value: new[scratch] 23}" not in STRUCT_FIELD_FIXTURE:
    raise SystemExit("the existing struct-field scalar control must remain bound to this proof")
if "AllocationRegionHolder{value: new[scratch] 1}" not in REFERENCE_FIELD_FIXTURE or "return alias" not in REFERENCE_FIELD_FIXTURE:
    raise SystemExit("a reference-carrying struct-field allocation escape must remain covered")

print("allocation region consumer source checks passed")
