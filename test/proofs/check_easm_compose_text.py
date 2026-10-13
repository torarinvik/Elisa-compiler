"""Bind EASM argument source-span proofs to the production parser helpers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
ENV = ROOT / "src/backend/codegen_env.elisa"
TEXT = ROOT / "src/backend/easm_compose_text.elisa"
VERIFY = ROOT / "src/backend/easm_verify_function.elisa"
PARSE = ROOT / "src/backend/easm_parse.elisa"
CODEGEN = ROOT / "src/backend/codegen_module.elisa"
POSITIVE = HERE / "easm_compose_text.elisa"
NEGATIVE = HERE / "easm_compose_text_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}(?:\[[^\]\n]*\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?(?:def|struct) [A-Za-z_][A-Za-z0-9_]*", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost[ \t]+)?def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


env_text = ENV.read_text()
text_source = TEXT.read_text()
verify_text = VERIFY.read_text()
parse_text = PARSE.read_text()
codegen_text = CODEGEN.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

include_line = 'include "easm_compose_text.elisa"'
if env_text.count(include_line) != 1:
    raise SystemExit("backend environment must import the EASM compose-text module exactly once")
if not (env_text.index('include "easm_text_scan.elisa"') < env_text.index(include_line)
        < env_text.index('include "easm_verify_function.elisa"')):
    raise SystemExit("compose-text helpers must load after their scanner and before EASM verification")
if len(TEXT.read_text().splitlines()) > 600 or len(VERIFY.read_text().splitlines()) > 600:
    raise SystemExit("EASM text parsing extraction must keep both implementation modules within 600 lines")

helper_names = {
    "easm_parse_params", "easm_split_values", "easm_make_function",
    "easm_parse_instruction", "easm_issue", "easm_parse_compose",
    "easm_compose_argument_count", "easm_compose_span",
    "easm_compose_comma_count_from", "easm_compose_span_argument_count",
    "easm_compose_span_reference_from", "easm_compose_span_reference",
}
if not helper_names <= declarations(text_source):
    raise SystemExit("compose-text module is missing an extracted production helper")
if helper_names & declarations(verify_text):
    raise SystemExit("extracted parser helpers are still duplicated in the verifier module")

span_body = compact(function_section(text_source, "easm_compose_span"))
required_span_fragments = (
    "ensure (wanted >= 0 and wanted < easm_compose_span_argument_count(text)) implies result.valid",
    "ensure result.valid == easm_compose_span_reference(text, wanted).valid",
    "ensure result.start == easm_compose_span_reference(text, wanted).start",
    "ensure result.end == easm_compose_span_reference(text, wanted).end",
    "ensure not result.valid implies result.start == 0 and result.end == 0",
    "ensure result.valid implies result.start <= result.end",
    "ensure result.valid implies result.end <= text.len",
    'open: usize = EasmTextScan::find(text, "(")',
    'close: usize = EasmTextScan::find(text[open:text.len], ")") + open',
    "assert close <= text.len",
    "value_length: usize = values.len",
    "assert value_length == close - base",
    "while cursor <= value_length",
    "decreases value_length - cursor",
    "invariant cursor <= value_length",
    "invariant start <= cursor",
    "invariant current >= 0",
    "invariant easm_compose_span_reference_from(values, base, close, start, cursor, current, wanted).valid == reference_valid",
    "invariant easm_compose_span_reference_from(values, base, close, start, cursor, current, wanted).start == reference_start",
    "invariant easm_compose_span_reference_from(values, base, close, start, cursor, current, wanted).end == reference_end",
    "if cursor == value_length: break",
    "EasmTextScan::trim_bounds(values[start:cursor])",
    "assert span_end <= close",
    "assert reference_at_cursor.valid",
    "assert reference_at_cursor.start == span_start",
    "assert reference_at_cursor.end == span_end",
    "return ComposeSpan{start: span_start, end: span_end, valid: true}",
    "return ComposeSpan{start: 0, end: 0, valid: false}",
)
if any(compact(fragment) not in span_body for fragment in required_span_fragments):
    raise SystemExit("compose-span contract or source-bound loop invariant changed")

count_body = compact(function_section(text_source, "easm_compose_argument_count"))
required_count_fragments = (
    "ensure (EasmTextScan::trim(text)).len == 0 implies result == 0",
    "ensure (EasmTextScan::trim(text)).len > 0 implies result == easm_compose_comma_count_from(EasmTextScan::trim(text), 0.usize()) + 1",
    "invariant count + easm_compose_comma_count_from(trimmed, index) == easm_compose_comma_count_from(trimmed, 0.usize())",
    "count <- count + 1 if trimmed[index] == 44",
    "return count + 1",
)
if any(compact(fragment) not in count_body for fragment in required_count_fragments):
    raise SystemExit("comma-count implementation lost its recursive specification or loop invariant")
comma_model_body = compact(function_section(text_source, "easm_compose_comma_count_from"))
if compact("requires cursor <= text.len") not in comma_model_body \
        or compact("decreases text.len - cursor") not in comma_model_body \
        or compact("ensure result >= 0") not in comma_model_body \
        or compact("return 1 + easm_compose_comma_count_from(text, cursor + 1.usize())") not in comma_model_body:
    raise SystemExit("recursive comma-count model lost its range, termination, or delimiter step")

reference_body = compact(function_section(text_source, "easm_compose_span_reference_from"))
required_reference_fragments = (
    "ghost def easm_compose_span_reference_from(",
    "requires cursor <= values.len and segment_start <= cursor and current >= 0",
    "decreases values.len - cursor",
    "ensure (wanted >= current and wanted - current <= easm_compose_comma_count_from(values, cursor)) implies result.valid",
    "if cursor < values.len and values[cursor] != 44",
    "return easm_compose_span_reference_from(values, base, source_end, segment_start, cursor + 1.usize(), current, wanted)",
    "EasmTextScan::trim_bounds(values[segment_start:cursor])",
    "assert span_end <= source_end",
    "if cursor == values.len: return ComposeSpan{start: 0, end: 0, valid: false}",
    "return easm_compose_span_reference_from(values, base, source_end, cursor + 1.usize(), cursor + 1.usize(), current + 1, wanted)",
)
if any(compact(fragment) not in reference_body for fragment in required_reference_fragments):
    raise SystemExit("recursive compose-span specification changed without updating its refinement proof")

span_count_body = compact(function_section(text_source, "easm_compose_span_argument_count"))
if compact("return easm_compose_argument_count(values)") not in span_count_body:
    raise SystemExit("span-domain count no longer uses the verified comma-count policy")
reference_wrapper_body = compact(function_section(text_source, "easm_compose_span_reference"))
if compact("ensure (wanted >= 0 and wanted < easm_compose_span_argument_count(text)) implies result.valid") not in reference_wrapper_body:
    raise SystemExit("recursive span wrapper lost its in-range index validity contract")
parse_compose_body = compact(function_section(text_source, "easm_parse_compose"))
if compact("ensure result.valid implies result.argument_count == easm_compose_span_argument_count(text)") not in parse_compose_body:
    raise SystemExit("compose parser count is not bound to the span-domain argument count")

for caller_name in ("easm_parse_compose", "easm_compose_argument_count", "easm_compose_span"):
    if caller_name in declarations(verify_text):
        raise SystemExit(f"{caller_name} must have a single definition in the extracted text module")
if "easm_parse_params(" not in parse_text or "easm_make_function(" not in parse_text \
        or "easm_parse_instruction(" not in parse_text or "easm_split_values(" not in parse_text:
    raise SystemExit("EASM module parser lost a call to an extracted source helper")
if "easm_parse_compose(" not in parse_text or "easm_compose_span(" not in parse_text \
        or "easm_compose_argument_count(" not in verify_text:
    raise SystemExit("EASM composition consumers no longer use the extracted source helpers")
if "instruction.text[span.start:span.end]" not in compact(parse_text):
    raise SystemExit("composition expansion no longer slices with the source-linked span")
expansion_body = compact(function_section(parse_text, "easm_expand_compositions"))
span_guard = expansion_body.find("ifspan.valid:")
replacement_slice = expansion_body.find("instruction.text[span.start:span.end]")
failure_path = expansion_body.find("ifinvalid_span:")
arity_guard = expansion_body.find("ifinfo.argument_count!=fragment.params.count.i64():")
parameter_loop = expansion_body.find("forparameter_indexin0..<fragment.params.count")
if span_guard < 0 or replacement_slice < span_guard:
    raise SystemExit("composition replacement slice is no longer guarded by the proved span validity")
if failure_path < replacement_slice \
        or "forparameter_indexin0..<fragment.params.count|parameter_index,fragment,materialized,instruction,invalid_span|" not in expansion_body \
        or "invalid_span<-true" not in expansion_body \
        or '"invalid-fragment-span"' not in expansion_body[failure_path:] \
        or "continue" not in expansion_body[failure_path:]:
    raise SystemExit("an invalid fragment span must report an issue and skip emitting that instruction")
if arity_guard < 0 or parameter_loop < arity_guard \
        or '"fragment-arity"' not in expansion_body[arity_guard:parameter_loop] \
        or "continue" not in expansion_body[arity_guard:parameter_loop]:
    raise SystemExit("parameter spans are no longer scanned only after a rejected arity is skipped")
if "easm_expand_compositions(out)" not in compact(function_section(parse_text, "parse_layout_module")):
    raise SystemExit("EASM parsing no longer records composition-span errors before module verification")
emit_body = compact(function_section(codegen_text, "emit_easm_module"))
if "forissueinmodule.issues:" not in emit_body or \
        "issue.severity==Easm::Severity.Error" not in emit_body or \
        "-1returniferror_count!=0" not in emit_body:
    raise SystemExit("EASM code generation no longer fails closed on composition-span issues")

positive_names = {
    "compose_argument_count_matches_the_recursive_comma_model",
    "compose_parser_count_matches_the_span_argument_count",
    "implementation_matches_the_recursive_span_spec",
    "every_valid_compose_span_is_bounded",
    "every_in_range_argument_index_has_a_valid_span",
    "every_invalid_compose_span_has_the_zero_sentinel",
    "first_argument_span_excludes_outer_spaces",
    "later_argument_span_selects_the_requested_segment",
    "final_argument_span_reaches_the_closing_boundary",
    "absent_argument_span_uses_the_invalid_sentinel",
    "missing_open_paren_uses_the_invalid_sentinel",
}
negative_names = {
    "comma_separated_arguments_can_be_counted_as_empty",
    "in_range_argument_index_can_have_an_invalid_span",
    "valid_span_can_end_past_its_source",
    "valid_span_can_reverse_its_bounds",
    "invalid_span_can_return_nonzero_bounds",
}
negative_claims = {
    "comma_separated_arguments_can_be_counted_as_empty": 'Easm::easm_compose_argument_count("dst, src") == 0',
    "in_range_argument_index_can_have_an_invalid_span": "not span.valid",
    "valid_span_can_end_past_its_source": "span.valid implies span.end > text.len",
    "valid_span_can_reverse_its_bounds": "span.valid implies span.start > span.end",
    "invalid_span_can_return_nonzero_bounds": "not span.valid and (span.start != 0 or span.end != 0)",
}
for source_text, name_set, path_label in (
    (positive_text, positive_names, "positive"),
    (negative_text, negative_names, "negative"),
):
    if declarations(source_text) != name_set:
        raise SystemExit(f"{path_label} EASM compose-span theorem inventory changed")
    for module_path in (
        'include "../../src/backend/easm_model.elisa"',
        'include "../../src/backend/easm_text_scan.elisa"',
        'include "../../src/backend/easm_compose_text.elisa"',
    ):
        if module_path not in source_text:
            raise SystemExit(f"{path_label} proof no longer imports production source: {module_path}")

for name in positive_names:
    if compact("ensure result == true") not in compact(function_section(positive_text, name)):
        raise SystemExit(f"positive source-span theorem {name} lost its checked proposition")
for name in negative_names:
    section = compact(function_section(negative_text, name))
    if compact("ensure result == true") not in section or compact(negative_claims[name]) not in section:
        raise SystemExit(f"false-claim control {name} lost its attempted claim")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names),
                      "source_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("EASM compose-span proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", ENV, TEXT, VERIFY, PARSE, CODEGEN, POSITIVE, NEGATIVE,
    *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "EASM fragment argument spans stay ordered and within their source instruction",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
