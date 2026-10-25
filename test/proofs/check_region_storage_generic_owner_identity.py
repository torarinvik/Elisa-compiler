"""Bind region storage ownership inference to each declaration's source offset."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
STORAGE = ROOT / "src/semantic/check_region_storage_owned_types.elisa"
REGION = ROOT / "src/semantic/check_local_region_annotation.elisa"
FIXTURE = ROOT / "test/fixtures/diagnostics/storage_dependency_generic_owner_line_zero.neg.elisa"
SMOKE = ROOT / "test/parity/owned_overload_storage_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


storage = STORAGE.read_text()
region = REGION.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()

owner_test = function_source(storage, "storage_owner_is_generic")
collect_types = function_source(storage, "storage_owned_collect")
collect_scopes = function_source(storage, "storage_owned_scope_collect")
collect_functions = function_source(storage, "storage_owned_fn_collect")
return_region = function_source(region, "function_return_region")

if not all(fragment in owner_test for fragment in (
    "generic_lines.count != generic_names.count",
    "generic_lines.count != generic_offsets.count",
    "generic_lines[generic_index] == line",
    "generic_offsets[generic_index] == owner_offset",
)):
    raise SystemExit("generic classification must join line and owner offset across aligned metadata")
if "storage_owner_is_generic(generic_lines, generic_names, generic_offsets, pos.line, pos.offset)" not in collect_types:
    raise SystemExit("struct and enum ownership classification must use exact declaration identity")
if "storage_owner_is_generic(generic_lines, generic_names, generic_offsets, pos.line, pos.offset)" not in collect_scopes or \
        "storage_owner_is_generic(generic_lines, generic_names, generic_offsets, pos.line, pos.offset)" not in collect_functions:
    raise SystemExit("function freshness must use exact generic declaration identity")
if "annotation.owner_offset == function_offset" not in return_region or \
        "function_return_region(file.local_region_annotations, pos.line, pos.offset)" not in storage:
    raise SystemExit("return-region classification must use the owning function offset")
if len([line for line in fixture.splitlines() if line.startswith("#line 0 ")]) < 3 or \
        not all(fragment in fixture for fragment in ("def phantom[T]", "struct Kind:", "def infer(", "-> darray[Kind]")):
    raise SystemExit("regression fixture must collide generic, plain-type, and fresh-function owners on line zero")
if "check_region_storage_generic_owner_identity.py" not in smoke or \
        "storage_dependency_generic_owner_line_zero.neg" not in smoke:
    raise SystemExit("owned-overload smoke must gate the source proof and line-zero regression")
