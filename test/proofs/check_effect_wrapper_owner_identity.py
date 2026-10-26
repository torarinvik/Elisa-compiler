"""Effect wrapper markers must belong to the exact function declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text()


def function_text(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        text,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


params = source("src/parser/parser_func_params.elisa")
function_parser = source("src/parser/parser_types_function.elisa")
permission_scan = source("src/parser/parser_types_entry.elisa")
grants = source("src/semantic/check_ungranted_panic_grants.elisa")
coverage = source("src/semantic/check_ungranted_panic_coverage.elisa")
fixture = source("test/repro/effect_wrapper_same_line_zero_identity.elisa")

if not all(fragment in params for fragment in (
    "effect_parameter_owner_offset: u32 = function_offset if has_function_owner else 4294967295",
    'owner: "__effect_param"',
    "offset: effect_parameter_owner_offset",
)):
    raise SystemExit("effect-parameter rows must carry their owning function offset or the unknown sentinel")

permission_owner = function_text(function_parser, "capture_function_generic_params")
if not all(fragment in permission_owner for fragment in (
    "is_permission_kw:",
    "permission_name_token: Token",
    'owner: "__permission_param_decl"',
    "line: function_line, offset: function_offset",
)):
    raise SystemExit("generic permission markers must retain their owning function position")
permission_global = function_text(permission_scan, "scan_permission_param_members")
if "offset: parser.scan_token_pos(index + 1).offset" not in permission_global:
    raise SystemExit("the global permission-name scan must not leave an offset-zero pseudo-owner")

position_helper = function_text(grants, "wrapper_index_has_position")
if "lines[row] == line and offsets[row] == offset" not in position_helper:
    raise SystemExit("wrapper marker indexes must compare both logical line and source offset")
wrapper_builder = function_text(grants, "build_concrete_effect_wrapper_index")
if not all(fragment in wrapper_builder for fragment in (
    "annotation.offset != 4294967295",
    "index.effect_parameter_offsets",
    "index.permission_parameter_offsets",
    "symbol.line, symbol.offset",
    "function_all_wrappers[name_row] <- false if not is_wrapper",
    "function_has_wrappers[name_row] and function_all_wrappers[name_row]",
)):
    raise SystemExit("wrapper construction must use exact owners and reject mixed same-leaf declarations")

effect_owner = function_text(grants, "effect_param_on_line")
if "annotation.line == function_line and annotation.offset == function_offset" not in effect_owner:
    raise SystemExit("effect-parameter calls must be matched to their enclosing function position")
for helper_name in ("check_ungranted_call_expression", "check_ungranted_expression_deep", "check_ungranted_panic_statements"):
    body = function_text(grants, helper_name)
    if "function_offset: u32" not in body or "function_offset" not in body:
        raise SystemExit(f"{helper_name} must thread the owning function offset through the call walk")
if "wrapper_index, line.line, line.offset, current_module, signature_grant" not in coverage:
    raise SystemExit("the Decl.Func walk must seed ungranted-call analysis with the declaration offset")

if fixture.count("#line 0 effect-wrapper-owner.elisa") != 3:
    raise SystemExit("wrapper fixture must give the concrete, generic, and plain declarations the same #line 0")
for fragment in (
    "def concrete_wrapper(callback: fn() -> void can[Console.Write])",
    "def permission_wrapper[permission P](callback: fn() -> void can[P])",
    "def plain_callback(callback: fn() -> void)",
    "module First:",
    "def mixed_name(callback: fn() -> void can[Console.Write])",
    "module Second:",
    "def mixed_name(value: i64)",
):
    if fragment not in fixture:
        raise SystemExit(f"same-line wrapper fixture is missing scenario: {fragment}")
