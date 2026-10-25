"""Keep effect clone/defer generic lookup scoped to its declaration at line zero."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src/parser/parser_core.elisa"
CORE_INIT = ROOT / "src/parser/parser_core_member_tables.elisa"
DEFERRED = ROOT / "src/parser/parser_effect_deferred.elisa"
REWRITE = ROOT / "src/parser/parser_effect_handler_rewrite.elisa"
SPECIALIZATION = ROOT / "src/parser/parser_effect_specialization.elisa"
FIXTURE = ROOT / "test/fixtures/effects/helper_generic_effect_line_zero.elisa"
SMOKE = ROOT / "test/parity/effect_handler_stage1_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing effect clone/defer helper {name}")
    return match.group(0)


core = CORE.read_text()
core_init = CORE_INIT.read_text()
deferred = DEFERRED.read_text()
rewrite = REWRITE.read_text()
specialization = SPECIALIZATION.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()

if not all(fragment in core for fragment in (
    "effect_clone_source_active: mutable bool",
    "effect_clone_source_line: mutable u32",
    "effect_clone_source_offset: mutable u32",
)) or not all(fragment in core_init for fragment in (
    "effect_clone_source_active: false",
    "effect_clone_source_line: 0",
    "effect_clone_source_offset: 0",
)):
    raise SystemExit("Parser must initialize a separate active-clone marker and exact owner identity")

depends = function_source(deferred, "effect_type_depends_on_generic")
if not all(fragment in depends for fragment in (
    "source_line: u32",
    "source_offset: u32",
    "parser.generic_param_lines.count != parser.generic_param_names.count",
    "parser.generic_param_lines.count != parser.generic_param_owner_offsets.count",
    "parser.generic_param_lines[index] == source_line",
    "parser.generic_param_owner_offsets[index] == source_offset",
    "parser.generic_param_names[index] == name",
)) or "source_line == 0" in depends:
    raise SystemExit("effect generic dependency checks must treat line zero as an exact owner, not a wildcard")
for fragment in (
    "effect_type_depends_on_generic(head, source_line, source_offset)",
    "effect_type_depends_on_generic(argument, source_line, source_offset)",
    "effect_type_depends_on_generic(target, source_line, source_offset)",
):
    if fragment not in depends:
        raise SystemExit("recursive generic-type walks must preserve both owner coordinates")

any_generic = function_source(deferred, "effect_type_mentions_any_generic")
if "parser.generic_param_lines[index] < GENERIC_PARAM_BOUND_FLAG and parser.generic_param_names[index] == name" not in any_generic or \
        "effect_type_mentions_any_generic(candidate_type)" not in deferred:
    raise SystemExit("candidate closedness must use a distinct any-owner generic query")
environment = function_source(deferred, "effect_environment_may_cover")
defer = function_source(deferred, "defer_generic_effect_call")
if "source_offset: u32" not in environment or \
        "effect_type_depends_on_generic(requested, source_line, source_offset)" not in environment or \
        "source_offset: u32 = parser.effect_clone_source_offset" not in defer or \
        "effect_type_depends_on_generic(head, source_line, source_offset)" not in defer:
    raise SystemExit("template and clone callers must pass the exact generic owner to deferred selection")

build_clone = function_source(specialization, "effect_build_clone")
if not all(fragment in build_clone for fragment in (
    "parser.effect_clone_source_active <- true",
    "parser.effect_clone_source_line <- source_line.line",
    "parser.effect_clone_source_offset <- source_line.offset",
    "parser.effect_clone_source_active <- false",
    "parser.effect_clone_source_offset <- 0",
)):
    raise SystemExit("clone construction must bracket rewriting with a line-independent active marker and owner offset")
rewrite_expression = function_source(rewrite, "rewrite_handler_expression")
if "if parser.effect_clone_source_active:" not in rewrite_expression or \
        "effect_clone_source_line != 0" in rewrite_expression:
    raise SystemExit("handler rewrite must allow deferred operations in line-zero clones")

if fixture.count("#line 0 ") != 2 or not all(fragment in fixture for fragment in (
    "#line 0 generic-effect-helper.elisa\ndef apply[T](value: T) -> T can[Identity[T]]:",
    "return Identity[T].transform(value)",
    "#line 0 generic-effect-helper.elisa\ndef apply[T](value: T, again: bool) -> T can[Identity[T]]:",
    "handler static Increment() for Identity[i64]",
    "return apply(41) + apply(40, true)",
)):
    raise SystemExit("regression must specialize same-name generic effect overloads at logical line zero")
for source, fragments, label in (
    (specialization, (
        "offset: line.offset",
        "marker.offset == source_line.offset",
        "line.offset == source_offset",
        "source_line.offset, handler_name, effect_ref",
        "effect_clone_source_offsets <- parser.effect_clone_source_offsets.push(source_offset)",
        'append_handler_name_text(name_bytes, "__src_")',
    ), "effect-template registration"),
    (core, ("effect_clone_source_offsets: mutable darray[u32]",), "clone identity storage"),
    (core_init, ("effect_clone_source_offsets: []",), "clone identity initialization"),
):
    for fragment in fragments:
        if fragment not in source:
            raise SystemExit(f"{label} must preserve exact source declaration offsets: {fragment}")
backend = (ROOT / "src/backend/codegen_template_registry.elisa").read_text()
semantic_handlers = (ROOT / "src/semantic/check_effect_handlers.elisa").read_text()
semantic_effects = (ROOT / "src/semantic/check_abstract_effects.elisa").read_text()
if "annotation.offset == line.offset" not in backend or \
        "annotation.offset == line.offset" not in semantic_handlers or \
        "declaration_pos.line, declaration_pos.offset" not in semantic_effects:
    raise SystemExit("backend template selection must match the exact declaration offset")
if "check_effect_generic_owner_line_zero.py" not in smoke or \
        smoke.count('run_positive "helper_generic_effect_line_zero.elisa"') != 1 or \
        smoke.count('run_native_result "helper_generic_effect_line_zero.elisa" 83') != 1 or \
        smoke.count('run_zero_overhead_ir "helper_generic_effect_line_zero.elisa"') != 1:
    raise SystemExit("effect handler smoke must compile, execute, and inspect the line-zero specialization")
print("effect generic owner line-zero source proof OK")
