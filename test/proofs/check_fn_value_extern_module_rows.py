"""Function-value effect rows must retain extern module and callback identity."""
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


rows = source("src/semantic/check_fn_value_effect_row.elisa")
signatures = source("src/semantic/check_fn_value_effect_row_signatures.elisa")
fixture = source("test/repro/fn_value_extern_rows_module_identity.elisa")

module_path = function_text(rows, "fver_module_scope_path")
if not all(fragment in module_path for fragment in (
    "context.parents[cursor]",
    "context.module_starts[cursor]",
    "intern_joined_text(bytes, table)",
)):
    raise SystemExit("source-row lookup must reconstruct the exact lexical module path")

call_effects = function_text(rows, "fver_external_call_effects")
if not all(fragment in call_effects for fragment in (
    "gp_namespace_root_is_local(callee, locals)",
    "gp_namespace_root_is_global(callee, context, locals)",
    "typestate_call_qualifier(callee, table)",
    "typestate_resolve_callable_owner(name, current_module, qualifier, call_pos, file, table)",
    "extern_module_owner_is_extern_only(selected.owner, name, table)",
    "extern_effect_index_refs(selected.owner, name, table)",
    "fver_trusted_covers_unsafe(annotations, firewalls, effect_ref)",
    "fver_add_memo(target, effect_ref, table)",
)):
    raise SystemExit("lambda call rows must resolve an exact extern owner and honor callback shadowing")

callback_arguments = function_text(rows, "fver_external_callback_argument_calls")
if "Expr.Lambda(parameters, body" not in callback_arguments or \
        "Expr.Paren(inner" not in callback_arguments or \
        "fver_external_body_calls(file, body" not in callback_arguments:
    raise SystemExit("callback arguments must walk executable lambda bodies with inherited locals")

body_rows = function_text(rows, "fver_body_rows")
if not all(fragment in body_rows for fragment in (
    "fver_external_statement_calls(file, statement",
    "resolved_extern_calls <- resolved_extern_calls - 1",
    "else:\n                                for candidate in 0..<context.functions.count",
)):
    raise SystemExit("only resolved extern calls may consume unknown-call fallbacks")

if "unknown_row <- true if effect_ref == \"Permission\"" not in call_effects or \
        "return not unknown_row" not in call_effects:
    raise SystemExit("incomplete extern effect rows must keep the unknown-call fallback")

canonical_rows = function_text(signatures, "fver_canonical_within")
if not all(fragment in canonical_rows for fragment in (
    "table.effect_canonical_function_name[slot]",
    "fver_module_scope_path(owner_scope, context, table)",
    "table.function_effect_source_owner[source_row] == owner",
    "table.function_effect_source_module[source_row] == owner_module",
    "fver_type_families(source_ref, owner_scope, source_offset",
)):
    raise SystemExit("declared function values must include source rows for the exact canonical module owner")

for required in (
    "module A:",
    "module B:",
    "module Runner:",
    "extern Tick() -> void can[Console.Write]",
    "extern Tick() -> void can[Disk.Read]",
    "from A import Tick",
    "A::Tick()",
    "B::Tick()",
    "lambda_import_wrong",
    "lambda_callback_arg_ok",
    "shadows_import(Tick: fn() -> void)",
):
    if required not in fixture:
        raise SystemExit(f"module identity fixture is missing {required!r}")

print("function-value extern module-row source proof OK")
