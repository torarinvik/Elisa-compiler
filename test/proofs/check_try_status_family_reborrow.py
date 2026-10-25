"""Prevent error-family views from escaping across deferred-action lowering."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/backend/codegen_try_lowering_propagation.elisa"
text = SOURCE.read_text(encoding="utf-8")


def function_body(name: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"\s*def {re.escape(name)}\b", line):
            indent = len(line) - len(line.lstrip())
            body = [line]
            for following in lines[index + 1 :]:
                if following.strip() and len(following) - len(following.lstrip()) <= indent:
                    break
                body.append(following)
            return "\n".join(body)
    raise AssertionError(f"function {name} not found")


call_struct = text.split("struct PropagatingTryCall:", 1)[1].split("\n\n", 1)[0]
assert "error_family:" not in call_struct
assert "return_family:" not in call_struct
assert "prepared.error_family" not in text and "prepared.return_family" not in text

no_recovery = function_body("emit_propagating_try_value_no_recovery")
deferred = no_recovery.index("emit_deferred_actions(")
reborrow = no_recovery.index("remap_propagating_try_status_after_deferred(")
assert deferred < reborrow
assert "prepared.status" in no_recovery[reborrow:]

remap = function_body("remap_propagating_try_status_after_deferred")
assert "infer_generic_error_family" in remap
assert "current_error_return_family(runtime, structs)" in remap
assert "remap_error_status(status, source_family, target_family" in remap

print("try status-family reborrow: deferred lowering cannot invalidate retained family views")
