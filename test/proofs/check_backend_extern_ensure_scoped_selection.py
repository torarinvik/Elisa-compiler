"""Extern ensure collection must follow selected scopes and retain nested declarations."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
ENSURE = ROOT / "src/backend/codegen_extern_ensure.elisa"
MODULE = ROOT / "src/backend/codegen_module.elisa"
STATIC_IF = ROOT / "src/backend/codegen_static_if.elisa"


def function_text(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        text,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


ensure = ENSURE.read_text()
module = MODULE.read_text()
static_if = STATIC_IF.read_text()

collector = function_text(ensure, "collect_extern_ensures")
if not all(fragment in collector for fragment in (
    "declarations: darray[Decl]",
    "collect_checkable_extern_offsets(declarations, potential_offsets)",
    "collect_checkable_extern_offsets(declarations, checkable_offsets)",
)) or "select_declarations_for_report" in collector or "file.top_decls" in collector:
    raise SystemExit("extern ensures must collect from the already-selected declaration tree")

offset_walk = function_text(ensure, "collect_checkable_extern_offsets")
if not all(fragment in offset_walk for fragment in (
    "Decl.Module(module_name, module_body, module_line)",
    "collect_checkable_extern_offsets(module_body, offsets)",
    "Decl.Scoped(scoped_body, scoped_line)",
    "collect_checkable_extern_offsets(scoped_body, offsets)",
)):
    raise SystemExit("extern ensure offset collection must recurse through module and scoped declarations")

selection = function_text(module, "select_module_declarations")
if not all(fragment in selection for fragment in (
    "selected_static_if_offsets(file, structs)",
    "flatten_static_branches(file.top_decls, static_branch_offsets, round_taken_offsets, round_top)",
)):
    raise SystemExit("the shared selector must flatten only backend-selected static branches")

emit_module = function_text(module, "emit_module_core")
select_call = "top: mutable darray[Decl] = select_module_declarations(file, structs)"
collect_call = "collect_extern_ensures(file, top, structs)"
thread_call = "top <- lower_value_threading(file, top)"
if not all(fragment in emit_module for fragment in (select_call, collect_call, thread_call)) or not (
    emit_module.index(select_call) < emit_module.index(collect_call) < emit_module.index(thread_call)
):
    raise SystemExit("extern ensures must consume the exact target-selected tree before value threading")

flatten = function_text(static_if, "flatten_static_branches")
if not all(fragment in flatten for fragment in (
    "is_branch: bool = static_branch_is_taken(branch_offsets, scoped_line.offset)",
    "keep: bool = static_branch_is_taken(taken_offsets, scoped_line.offset) if is_branch else true",
    "flatten_static_branches(scoped_body, branch_offsets, taken_offsets, out) if keep",
)):
    raise SystemExit("scoped extern collection must inherit the static branch keep/drop policy")
