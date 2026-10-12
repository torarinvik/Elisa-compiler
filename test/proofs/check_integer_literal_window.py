"""Replay the signed integer type-window proof against the production helper."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "integer_literal_window.elisa"
NEGATIVE = HERE / "integer_literal_window_rejected.elisa"
HELPER = ROOT / "src/semantic/integer_literal_window.elisa"
CHECKER = ROOT / "src/semantic/check_literal_type_overflow.elisa"
CONST_ENUM_CHECKER = ROOT / "src/semantic/check_const_enum_value_fits.elisa"
CAST_CHECKER = ROOT / "src/semantic/check_cast_constant_truncated.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARALLEL_PASSES = ROOT / "src/semantic/semantic_parallel_passes.elisa"
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def ordered_fragments(text: str, fragments: tuple[str, ...]) -> bool:
    normalized = compact(text)
    positions = [normalized.find(fragment) for fragment in fragments]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def inclusive_window_contract_matches(text: str) -> bool:
    normalized = compact(text)
    return (
        normalized.count(compact("ensure result == (value >= low and value <= high)")) == 1
        and normalized.count(compact("return value >= low and value <= high")) == 1
    )


def known_value_decision_matches(text: str) -> bool:
    normalized = compact(text)
    contract = compact(
        "ensure result == (window_found and value_found and not "
        "value_fits_signed_window(value, low, high))"
    )
    implementation = compact(
        "return window_found and value_found and not "
        "value_fits_signed_window(value, low, high)"
    )
    return normalized.count(contract) == 1 and normalized.count(implementation) == 1


helper_text = HELPER.read_text()
checker_text = CHECKER.read_text()
if 'include "../../src/semantic/integer_literal_window.elisa"' not in POSITIVE.read_text():
    raise AssertionError("positive proof no longer includes the production helper")
if 'include "../../src/semantic/integer_literal_window.elisa"' not in NEGATIVE.read_text():
    raise AssertionError("negative proof no longer includes the production helper")
if not inclusive_window_contract_matches(helper_text):
    raise AssertionError("inclusive-window helper must return and specify the exact inclusive predicate")
mutated_window_helper = helper_text.replace(
    "return value >= low and value <= high", "return value > low and value <= high", 1
)
if mutated_window_helper == helper_text or inclusive_window_contract_matches(mutated_window_helper):
    raise AssertionError("source checker failed to catch exclusion of the lower endpoint")
if not known_value_decision_matches(helper_text):
    raise AssertionError("known-value predicate must report overflow only when both range and value are known")
mutated_known_decision = helper_text.replace(
    "return window_found and value_found and not value_fits_signed_window(value, low, high)",
    "return value_found and not value_fits_signed_window(value, low, high)",
    1,
)
if mutated_known_decision == helper_text or known_value_decision_matches(mutated_known_decision):
    raise AssertionError("source checker failed to catch a missing-window overflow bypass")
if 'include "./integer_literal_window.elisa"' not in checker_text:
    raise AssertionError("semantic overflow checker no longer imports the proved helper")
literal_decision = "SemanticIntegerLiteral::value_is_outside_window_if_known(window.found, value_literal.found, value_literal.value, window.low, window.high)"
if checker_text.count(literal_decision) != 1:
    raise AssertionError("typed-literal overflow decision no longer uses the proved known-window predicate")
if 'include "./check_literal_type_overflow.elisa"' not in SEMANTIC.read_text():
    raise AssertionError("semantic pass no longer includes the overflow checker")
const_enum_text = CONST_ENUM_CHECKER.read_text()
if 'include "./integer_literal_window.elisa"' not in const_enum_text:
    raise AssertionError("const-enum overflow checker no longer imports the proved window predicate")
const_enum_compact = compact(const_enum_text)
const_enum_path = (
    "window:(found:bool,low:i64,high:i64)=bit_int_window(storage_name)"
    "ifenum_is_constelse(false,0,0)",
    "ifwindow.found:",
    "value_literal:(found:bool,value:i64)=where_signed_literal(variant.value_expr)",
    "out_of_range:bool=SemanticIntegerLiteral::value_is_outside_window_if_known(window.found,value_literal.found,value_literal.value,window.low,window.high)",
    "member_line:u32=enum_line.lineifAst::expr_pos(variant.value_expr).line==0elseAst::expr_pos(variant.value_expr).line",
)
if not ordered_fragments(const_enum_text, const_enum_path):
    raise AssertionError("const-enum checker must gate literal range checking on a const bit-int window and report at the member line")
if const_enum_compact.count(const_enum_path[3]) != 1:
    raise AssertionError("const-enum overflow decision must use the proved known-window predicate exactly once")
const_enum_diagnostic = compact(
    "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.ConstEnumValueOverflow, "
    "name: variant.name, line: member_line, expected: enum_name, actual: storage_name"
)
if const_enum_compact.count(const_enum_diagnostic) != 1 or "ifout_of_range" not in const_enum_compact:
    raise AssertionError("const-enum overflow decision no longer routes to the member-line diagnostic")
mutated_const_enum = const_enum_text.replace(
    "SemanticIntegerLiteral::value_is_outside_window_if_known(window.found, value_literal.found, value_literal.value, window.low, window.high)",
    "value_literal.value < window.low or value_literal.value > window.high",
    1,
)
if mutated_const_enum == const_enum_text or ordered_fragments(mutated_const_enum, const_enum_path):
    raise AssertionError("source checker failed to catch a const-enum range-check bypass")
for recursion in (
    "table<-check_const_enum_value_fits(module_body,table)",
    "table<-check_const_enum_value_fits(scoped_body,table)",
):
    if recursion not in const_enum_compact:
        raise AssertionError("const-enum overflow checker no longer visits nested declarations")
if 'include "./check_const_enum_value_fits.elisa"' not in SEMANTIC.read_text():
    raise AssertionError("semantic pass no longer includes the const-enum overflow checker")
if "check_const_enum_value_fits(loop_view.top_decls, table)" not in PARALLEL_PASSES.read_text():
    raise AssertionError("const-enum overflow checker is no longer scheduled in the semantic pass")
cast_text = CAST_CHECKER.read_text()
if 'include "./integer_literal_window.elisa"' not in cast_text:
    raise AssertionError("constant-cast overflow checker no longer imports the proved window predicate")
cast_compact = compact(cast_text)
cast_path = (
    "postfix_window:(found:bool,low:i64,high:i64)=bit_int_window(method_name)",
    "ifpostfix_window.found:",
    "base_value:(found:bool,value:i64)=fold_const_int(base)",
    "(true,base_value.value,method_name)returnifSemanticIntegerLiteral::value_is_outside_window_if_known(postfix_window.found,base_value.found,base_value.value,postfix_window.low,postfix_window.high)",
    "prefix_window:(found:bool,low:i64,high:i64)=bit_int_window(callee_name)",
    "ifprefix_window.foundandarguments.count==1:",
    "argument_value:(found:bool,value:i64)=fold_const_int(arguments[0])",
    "(true,argument_value.value,callee_name)returnifSemanticIntegerLiteral::value_is_outside_window_if_known(prefix_window.found,argument_value.found,argument_value.value,prefix_window.low,prefix_window.high)",
)
if not ordered_fragments(cast_text, cast_path):
    raise AssertionError("postfix and one-argument prefix casts must use the proved range predicate only for folded constants")
mutated_cast = cast_text.replace(
    "SemanticIntegerLiteral::value_is_outside_window_if_known(postfix_window.found, base_value.found, base_value.value, postfix_window.low, postfix_window.high)",
    "base_value.value < postfix_window.low or base_value.value > postfix_window.high",
    1,
)
if mutated_cast == cast_text or ordered_fragments(mutated_cast, cast_path):
    raise AssertionError("source checker failed to catch a constant-cast range-check bypass")
if "DiagnosticKind.CastConstantTruncated" not in cast_compact or "ifoverflow.found" not in cast_compact:
    raise AssertionError("proved constant-cast overflow result no longer controls its truncation diagnostic")
if 'include "./check_cast_constant_truncated.elisa"' not in SEMANTIC.read_text():
    raise AssertionError("semantic pass no longer includes the constant-cast overflow checker")
if "check_cast_constant_truncated(loop_view, table)" not in PARALLEL_PASSES.read_text():
    raise AssertionError("constant-cast overflow checker is no longer scheduled in the semantic pass")

positive_names = {
    "signed_value_fits_exactly_the_inclusive_window",
    "lower_endpoint_is_included",
    "upper_endpoint_is_included",
    "every_interior_value_is_included",
    "every_value_below_the_window_is_rejected",
    "every_value_above_the_window_is_rejected",
    "a_missing_window_never_reports_overflow",
    "a_missing_literal_never_reports_overflow",
    "a_known_value_below_the_window_reports_overflow",
    "a_known_lower_endpoint_does_not_report_overflow",
    "every_known_interior_value_does_not_report_overflow",
    "a_known_upper_endpoint_does_not_report_overflow",
    "a_known_value_above_the_window_reports_overflow",
}
negative_names = {
    "lower_endpoint_is_excluded",
    "upper_endpoint_is_excluded",
    "a_value_below_the_window_fits",
    "a_value_above_the_window_fits",
    "false_missing_window_reports_overflow",
    "false_missing_literal_reports_overflow",
    "false_below_value_is_ignored",
    "false_lower_endpoint_reports_overflow",
    "false_interior_value_reports_overflow",
    "false_upper_endpoint_reports_overflow",
    "false_above_value_is_ignored",
}
declared_positive = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", POSITIVE.read_text()))
declared_negative = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", NEGATIVE.read_text()))
if declared_positive != positive_names:
    raise AssertionError(f"positive proof inventory changed: {sorted(declared_positive)}")
if declared_negative != negative_names:
    raise AssertionError(f"negative proof inventory changed: {sorted(declared_negative)}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("integer-window proof requires a strict proof build")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
INPUTS = [*source_include_closure([POSITIVE, NEGATIVE]), BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          POSITIVE, NEGATIVE, HELPER, CHECKER, CONST_ENUM_CHECKER, CAST_CHECKER, SEMANTIC, PARALLEL_PASSES]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across identical runs"
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] in {"failed", "disproved"}
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {finding["name"] for finding in negative["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" and finding["status"] in {"unknown", "disproved"}
           for finding in negative["findings"])
assert all(not finding["counterexample_found"] or finding["status"] == "disproved"
           for finding in negative["findings"])

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert require_current_product(BIN, PROVER) == product_manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True, "scope": "inclusive signed integer range semantics shared by typed literals, const-enum values, and constant casts",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": [finding["name"] for finding in negative["findings"]],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": product_manifest["proof"].get("head"),
                  "compiler_revision": product_manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
