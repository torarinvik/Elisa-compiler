"""Bind explicit-generic zeroed checking to exact function identity, including #line 0."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_struct_field_construct_unproven.elisa"
FIXTURE = ROOT / "test/repro/struct_field_refinement_zeroed_generic_call_line_zero.elisa"
SHADOW_FIXTURE = ROOT / "test/repro/struct_field_refinement_zeroed_shadowed_function_value.elisa"
SMOKE = ROOT / "test/parity/struct_field_refinement_shadow_smoke.sh"


def function_source(name: str) -> str:
    source = SOURCE.read_text()
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


helper = function_source("sfcu_generic_call_parameter_type")
walker = function_source("sfcu_walk_expr")
for fragment in (
    "function_found: mutable bool = false",
    "function_offset <- symbol.offset",
    "function_module <- symbol.module_owner",
    "return \"\" if not function_found",
    'identity.name != "__generic_param_identity"',
    "identity.detail_line != function_line",
    "identity.offset != function_offset",
    "identity.module != function_module",
    "selected_generic_index <- generic_index",
    "generic_index <- generic_index + 1.usize()",
    "selected_generic_index < generic_arguments.count",
):
    if fragment not in helper:
        raise SystemExit(f"generic zeroed call lookup lost exact owner binding: {fragment}")
if "return \"\" if function_line == 0" in helper or "table.generic_param_lines[generic_row] == function_line" in helper:
    raise SystemExit("generic zeroed call lookup must not use logical line as declaration identity")
if not all(fragment in walker for fragment in (
    "sfcu_generic_call_parameter_type(table, callee_name, parameter_row, generic_arguments)",
    "sfcu_check_zeroed_struct(parameter_type, call_line",
    "if parameter_type != \"\"",
    "not any local_name in param_names where local_name == callee_name",
)):
    raise SystemExit("zeroed direct-call checks must use exact generic identities and skip shadowed function values")

fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
fixture_lines = fixture.splitlines()
line_zero_rows = [index for index, line in enumerate(fixture_lines) if line == "#line 0 zeroed-generic-call-line-zero.elisa"]
if len(line_zero_rows) != 2 or \
        fixture_lines[line_zero_rows[0] + 1] != "def prior[U](value: U) -> U:" or \
        fixture_lines[line_zero_rows[1] + 1] != "def identity[T](value: T) -> T:" or \
        "identity[Positive](zeroed)" not in fixture:
    raise SystemExit("line-zero generic fixture must collide by display line while selecting its own generic parameter")
if not all(fragment in smoke for fragment in (
    'BAD_ZEROED_GENERIC_CALL_LINE_ZERO="$ROOT/test/repro/struct_field_refinement_zeroed_generic_call_line_zero.elisa"',
    'reject_stage1 "$BAD_ZEROED_GENERIC_CALL_LINE_ZERO" "bad-zeroed-generic-call-line-zero"',
)):
    raise SystemExit("struct refinement smoke must reject zeroed calls through a line-zero generic wrapper")
shadow_fixture = SHADOW_FIXTURE.read_text()
if not all(fragment in shadow_fixture for fragment in (
    "def take(value: Positive) -> void:",
    "def invoke(take: fn(i64) -> void) -> i64:",
    "take(zeroed)",
)) or not all(fragment in smoke for fragment in (
    'GOOD_ZEROED_SHADOWED_FUNCTION_VALUE="$ROOT/test/repro/struct_field_refinement_zeroed_shadowed_function_value.elisa"',
    '"$GOOD_ZEROED_SHADOWED_FUNCTION_VALUE" >"$WORK/good-zeroed-shadowed-function-value.log"',
)):
    raise SystemExit("same-named function values must not inherit the global direct-call parameter type")
