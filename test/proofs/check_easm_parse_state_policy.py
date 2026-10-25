"""Bind EASM declaration-index policy proofs to the line parser loop invariants."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
ENV = ROOT / "src/backend/codegen_env.elisa"
MODEL = ROOT / "src/backend/easm_model.elisa"
POLICY = ROOT / "src/backend/easm_parse_state_policy.elisa"
PARSER_SOURCE = ROOT / "src/backend/easm_parse.elisa"
RUNTIME_STRINGS = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
POSITIVE = HERE / "easm_parse_state_policy.elisa"
NEGATIVE = HERE / "easm_parse_state_policy_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


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
model_text = MODEL.read_text()
policy_text = POLICY.read_text()
parser_text = PARSER_SOURCE.read_text()
runtime_strings_text = RUNTIME_STRINGS.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

include_line = 'include "easm_parse_state_policy.elisa"'
if env_text.count(include_line) != 1:
    raise SystemExit("backend must import the parser-state policy exactly once")
if not (env_text.index('include "easm_model.elisa"') < env_text.index(include_line)
        < env_text.index('include "easm_parse.elisa"')):
    raise SystemExit("parser-state tags and policy must load after the EASM model and before parsing")
if "const enum EasmBodyMode" not in policy_text or "const enum EasmDeclarationKind" not in policy_text:
    raise SystemExit("parser-state enums are missing from their shared policy module")
if "const enum EasmBodyMode" in parser_text or "const enum EasmDeclarationKind" in parser_text:
    raise SystemExit("parser-state enums are still duplicated in the line parser")

policy_body = compact(function_section(policy_text, "easm_declaration_index_valid"))
required_policy_fragments = (
    "ensure (kind == EasmDeclarationKind.Function) implies result == (index >= 0 and index.usize() < function_count)",
    "ensure (kind == EasmDeclarationKind.Fragment) implies result == (index >= 0 and index.usize() < fragment_count)",
    "ensure (kind == EasmDeclarationKind.Protocol) implies result == (index >= 0 and index.usize() < protocol_count)",
    "ensure (kind == EasmDeclarationKind.Template) implies result == (index >= 0 and index.usize() < template_count)",
    "ensure (kind == EasmDeclarationKind.None or kind == EasmDeclarationKind.Layout) implies result",
    "EasmDeclarationKind.Function: return index >= 0 and index.usize() < function_count",
    "EasmDeclarationKind.Fragment: return index >= 0 and index.usize() < fragment_count",
    "EasmDeclarationKind.Protocol: return index >= 0 and index.usize() < protocol_count",
    "EasmDeclarationKind.Template: return index >= 0 and index.usize() < template_count",
    "_: return true",
)
if any(compact(fragment) not in policy_body for fragment in required_policy_fragments):
    raise SystemExit("declaration-index policy lost a collection-bound contract or matching implementation")
route_body = compact(function_section(policy_text, "easm_body_routing_valid"))
route_contract = (
    "ensure result == ((mode != EasmBodyMode.Target or (active_target >= 0 and kind == EasmDeclarationKind.Function)) "
    "and (mode != EasmBodyMode.Reference or kind == EasmDeclarationKind.Function or kind == EasmDeclarationKind.Fragment))"
)
if compact(route_contract) not in route_body:
    raise SystemExit("body-mode routing policy lost its target/reference ownership contract")
span_body = compact(function_section(policy_text, "easm_source_span_valid"))
span_contract = "requires source_length <= buffer_count ensure result == (start <= end and end <= source_length and end <= buffer_count)"
if compact(span_contract) not in span_body or compact("return start <= end and end <= source_length and end <= buffer_count") not in span_body:
    raise SystemExit("source-span policy lost its ordered, logical-length, and backing-buffer contract")
range_view_body = compact(function_section(runtime_strings_text, "bytes_view_range_ref"))
range_view_request = compact(function_section(runtime_strings_text, "bytes_view_range_ref_request_valid"))
if "start<=buf.countandcount<=buf.count-start" not in range_view_request:
    raise SystemExit("bounded-view request predicate lost its non-overflowing buffer extent condition")
range_view_contracts = (
    "ensure result.len >= 0",
    "ensure result.len == 0 or result.len == count.i64()",
    "ensure (count == 0) implies result.len == 0",
    "ensure (start > buf.count) implies result.len == 0",
    "ensure (start <= buf.count and count > buf.count - start) implies result.len == 0",
    "ensure (buf.count == 0 or buf.items == null or buf.count > buf.capacity) implies result.len == 0",
    "ensure (buf.count.i64() < 0 or buf.count.i64().usize() != buf.count) implies result.len == 0",
    "ensure (start.i64() < 0 or start.i64().usize() != start) implies result.len == 0",
    "ensure (count.i64() < 0 or count.i64().usize() != count) implies result.len == 0",
    "ensure (buf.count > 0 and buf.items != null and buf.count <= buf.capacity and buf.count.i64() >= 0 and buf.count.i64().usize() == buf.count and start <= buf.count and count <= buf.count - start and start.i64() >= 0 and start.i64().usize() == start and count.i64() >= 0 and count.i64().usize() == count and count > 0 and start < buf.count) implies result.len == count.i64()",
    "ensure (buf.count > 0 and buf.items != null and buf.count <= buf.capacity and buf.count.i64() >= 0 and buf.count.i64().usize() == buf.count and start <= buf.count and count <= buf.count - start and start.i64() >= 0 and start.i64().usize() == start and count.i64() >= 0 and count.i64().usize() == count and count > 0 and start < buf.count) implies result.data == &buf[start]",
    "ensure not (buf.count > 0 and buf.items != null and buf.count <= buf.capacity and buf.count.i64() >= 0 and buf.count.i64().usize() == buf.count and start <= buf.count and count <= buf.count - start and start.i64() >= 0 and start.i64().usize() == start and count.i64() >= 0 and count.i64().usize() == count and count > 0 and start < buf.count) implies result.len == 0",
)
if any(compact(contract) not in range_view_body for contract in range_view_contracts):
    raise SystemExit("bounded view helper lost its output-length, extent, representation, or alias postcondition")
range_view_body_impl = range_view_body.split("canUnsafe{PointerArithmetic,RawExtern}:", 1)[-1]
range_view_guard = compact(
    "if (buf.count > 0 and buf.items != null and buf.count <= buf.capacity "
    "and buf.count.i64() >= 0 and buf.count.i64().usize() == buf.count "
    "and start <= buf.count and count <= buf.count - start "
    "and start.i64() >= 0 and start.i64().usize() == start "
    "and count.i64() >= 0 and count.i64().usize() == count "
    "and count > 0 and start < buf.count):"
)
range_view_return = "trustedUnsafe.UncheckedIndex:trustedUnsafe.PointerCast:returnStringView{data:&buf[start],len:count.i64()}"
if range_view_guard not in range_view_body_impl or range_view_return not in range_view_body_impl \
        or "returnempty" not in range_view_body_impl:
    raise SystemExit("bounded view helper lost a count, capacity, range, representation, or guarded pointer check")
range_view_guard_position = range_view_body_impl.find(range_view_guard)
range_view_pointer_cast = range_view_body_impl.find("trustedUnsafe.PointerCast")
range_view_empty_return = range_view_body_impl.find("returnempty", range_view_pointer_cast)
if range_view_guard_position < 0 or range_view_pointer_cast < range_view_guard_position \
        or range_view_empty_return < range_view_pointer_cast:
    raise SystemExit("the full bounded-view guard must dominate pointer construction and fail closed")
if not range_view_request.startswith("ghostdefbytes_view_range_ref_request_valid("):
    raise SystemExit("bounded view request predicate must remain a proof-only description")

parse_body = compact(function_section(parser_text, "parse_layout_module"))
if "defparse_layout_module(source:darray[u8]&,length:usize,path:sview)->Module:requireslength<=source.count" not in parse_body:
    raise SystemExit("layout parser must bind its logical length to the backing darray extent")
compose_body = compact(function_section(parser_text, "easm_expand_compositions"))
required_compose_effect_grants = (
    "canUnsafe.PointerArithmetic,Unsafe.RawExtern:substituted_text<-bytes_view_range_ref(substituted_bytes,0.usize(),substituted_bytes.count)",
    "canUnsafe.PointerArithmetic,Unsafe.RawExtern:variant.name<-bytes_view_range_ref(name_bytes,0.usize(),name_bytes.count)",
)
if any(grant not in compose_body for grant in required_compose_effect_grants):
    raise SystemExit("composition expansion must locally grant only the bounded-view effects it uses")
required_parser_effect_grants = (
    "canUnsafe.PointerArithmetic,Unsafe.RawExtern:line_view<-bytes_view_range_ref(source,line_start,cursor-line_start)",
    "canUnsafe.PointerArithmetic,Unsafe.RawExtern:easm_expand_compositions(out)",
    "canAbort.Panic:forissueinverify_module(out):out.issues.push(issue)",
)
if any(grant not in parse_body for grant in required_parser_effect_grants):
    raise SystemExit("line parser lost an explicit local effect grant for its bounded view, expansion, or verification")
module_wrapper = compact(function_section(parser_text, "parse_module"))
if "defparse_module(source:darray[u8]&,length:usize,path:sview)->Module:requireslength<=source.countcanAbort.Panic,Unsafe.PointerArithmetic,Unsafe.RawExtern:returnparse_layout_module(source,length,path)" not in module_wrapper:
    raise SystemExit("public EASM parsing must preserve the bounded darray input contract")
for source_path in [*ROOT.joinpath("src").rglob("*.elisa"), *ROOT.joinpath("test").rglob("*.elisa")]:
    source_text = source_path.read_text()
    if re.search(r"parse_(?:layout_)?module\s*\(\s*\(&", source_text):
        raise SystemExit(f"raw pointer passed to the bounded EASM parser at {source_path.relative_to(ROOT)}")
required_state_guards = (
    "state_valid:bool=easm_declaration_index_valid(current_kind,current_index,out.functions.count,out.fragments.count,out.protocols.count,out.templates.count)",
    "andactive_layout>=-1",
    "(current_kind==EasmDeclarationKind.Layout)==(active_layout>=0)",
    "active_layout<0oractive_layout.usize()<out.layouts.count",
    "active_target.usize()<out.functions[current_index.usize()].targets.count",
    "andeasm_body_routing_valid(body_mode,current_kind,active_target)",
    "ifnotstate_valid:",
    "current_kind<-EasmDeclarationKind.None",
    "current_index<--1",
    "active_layout<--1",
    "active_target<--1",
    "body_mode<-EasmBodyMode.None",
    "section<-\"\"",
    "assert(easm_declaration_index_valid(current_kind,current_index,out.functions.count,out.fragments.count,out.protocols.count,out.templates.count))",
    "assert(active_layout>=-1)",
    "assert(active_target==-1or",
    "assert(easm_body_routing_valid(body_mode,current_kind,active_target))",
)
if "invariantcursor<=length" not in parse_body or any(
        compact(fragment) not in parse_body for fragment in required_state_guards):
    raise SystemExit("line-parser routing state lost its fail-closed index-domain guards")
declaration_guard = parse_body.find("state_valid:bool=easm_declaration_index_valid(")
state_reset = parse_body.find("ifnotstate_valid:")
target_assert = parse_body.find("assert(active_target==-1or", state_reset)
line_scan = parse_body.find("line_start:usize=cursor")
if declaration_guard < 0 or state_reset <= declaration_guard or target_assert <= state_reset \
        or line_scan <= target_assert:
    raise SystemExit("state reset and index guards must dominate source-line parsing")
project_body = compact(function_section(parser_text, "parse_project"))
if not all(fragment in project_body for fragment in (
        "bytes:darray[u8]&=&source.bytes",
        "assert(length<=bytes.count)",
        "canAbort.Panic,Unsafe.PointerArithmetic,Unsafe.RawExtern:source:ProjectSource&=&sources[source_index]",
        "parsed:Module=parse_module(bytes,length,source.path)",
)):
    raise SystemExit("project parser must restate the bounded source extent after trimming the logical length")
scanner = parse_body.find("whilecursor<lengthandsource[cursor]!=10|cursor,length,source|:")
scanner_increment = parse_body.find("cursor<-cursor+1", scanner)
scanner_obligations = (
    "decreaseslength-cursor",
    "invariantline_start<=cursor",
    "invariantcursor<=length",
)
if scanner < line_scan or scanner_increment <= scanner \
        or any(parse_body.find(obligation, scanner) < scanner
               or parse_body.find(obligation, scanner) >= scanner_increment
               for obligation in scanner_obligations):
    raise SystemExit("line scanner lost its bounded, decreasing cursor invariant before source indexing")
span_guard = parse_body.find("ifeasm_source_span_valid(line_start,cursor,length,source.count):")
span_view = parse_body.find("line_view<-bytes_view_range_ref(source,line_start,cursor-line_start)", span_guard)
span_branch_end = parse_body.find("line_number<-line_number+1", span_guard)
if span_guard < scanner_increment or span_view < span_guard \
        or span_branch_end <= span_view or "trustedUnsafe.PointerCast" in parse_body:
    raise SystemExit("line views must use bounded darray slicing behind the proved source-span policy")
for access in (
    "out.functions[current_index.usize()]",
    "out.fragments[current_index.usize()]",
    "out.protocols[current_index.usize()]",
    "out.templates[current_index.usize()]",
    "out.layouts[active_layout.usize()]",
    "out.functions[current_index.usize()].targets[active_target.usize()]",
):
    if access not in parse_body:
        raise SystemExit(f"parser index invariant audit no longer covers {access}")
    if parse_body.find(compact(access), line_scan) < line_scan:
        raise SystemExit(f"parser index invariant audit no longer guards operational access {access}")

positive_names = {
    "declaration_index_policy_matches_its_collection_domain",
    "first_and_last_function_slots_are_valid",
    "stale_none_and_layout_indices_are_ignored",
    "empty_collection_has_no_valid_declaration_slot",
    "target_mode_requires_a_function_with_active_target",
    "reference_mode_requires_a_function_or_fragment",
    "empty_body_mode_allows_no_active_target",
    "valid_source_spans_have_ordered_bounded_endpoints",
    "empty_source_span_at_end_is_valid",
}
negative_names = {
    "function_index_equal_to_count_is_accepted",
    "fragment_negative_index_is_accepted",
    "protocol_index_equal_to_count_is_accepted",
    "template_index_in_empty_collection_is_accepted",
    "target_mode_without_active_target_is_valid",
    "reference_mode_with_protocol_owner_is_valid",
    "target_mode_with_fragment_owner_is_valid",
    "reversed_source_span_is_valid",
    "source_span_past_end_is_valid",
}
negative_claims = {
    "function_index_equal_to_count_is_accepted": "Easm::easm_declaration_index_valid(Easm::EasmDeclarationKind.Function, 2, 2, 0, 0, 0)",
    "fragment_negative_index_is_accepted": "Easm::easm_declaration_index_valid(Easm::EasmDeclarationKind.Fragment, -1, 0, 2, 0, 0)",
    "protocol_index_equal_to_count_is_accepted": "Easm::easm_declaration_index_valid(Easm::EasmDeclarationKind.Protocol, 1, 0, 0, 1, 0)",
    "template_index_in_empty_collection_is_accepted": "Easm::easm_declaration_index_valid(Easm::EasmDeclarationKind.Template, 0, 0, 0, 0, 0)",
    "target_mode_without_active_target_is_valid": "Easm::easm_body_routing_valid(Easm::EasmBodyMode.Target, Easm::EasmDeclarationKind.Function, -1)",
    "reference_mode_with_protocol_owner_is_valid": "Easm::easm_body_routing_valid(Easm::EasmBodyMode.Reference, Easm::EasmDeclarationKind.Protocol, -1)",
    "target_mode_with_fragment_owner_is_valid": "Easm::easm_body_routing_valid(Easm::EasmBodyMode.Target, Easm::EasmDeclarationKind.Fragment, 0)",
    "reversed_source_span_is_valid": "Easm::easm_source_span_valid(2.usize(), 1.usize(), 2.usize(), 2.usize())",
    "source_span_past_end_is_valid": "Easm::easm_source_span_valid(0.usize(), 3.usize(), 2.usize(), 3.usize())",
}
for source_text, names, label in (
    (positive_text, positive_names, "positive"),
    (negative_text, negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} parser-index theorem inventory changed")
    if 'include "../../src/backend/easm_model.elisa"' not in source_text \
            or 'include "../../src/backend/easm_parse_state_policy.elisa"' not in source_text:
        raise SystemExit(f"{label} parser-index proofs no longer include the production policy")
for name in positive_names:
    if compact("ensure result == true") not in compact(function_section(positive_text, name)):
        raise SystemExit(f"positive parser-index theorem {name} lost its checked proposition")
for name, args in negative_claims.items():
    section = compact(function_section(negative_text, name))
    if compact("ensure result == true") not in section or compact(args) not in section:
        raise SystemExit(f"false parser-index control {name} lost its rejected claim")

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
    raise SystemExit("EASM parser-state policy proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", ENV, MODEL, POLICY, PARSER_SOURCE, RUNTIME_STRINGS,
    POSITIVE, NEGATIVE, *source_closure,
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
    "scope": "EASM declaration tags select indices valid for their owning collections",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
