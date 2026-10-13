"""Admit proofs for the production bounded borrowed byte-range view."""
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
PRELUDE = ROOT / "elisacore_std/elisacore_runtime_prelude.elisa"
RUNTIME_STRINGS = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
POSITIVE = HERE / "bytes_view_range_ref.elisa"
NEGATIVE = HERE / "bytes_view_range_ref_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check proof/source bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


runtime_text = RUNTIME_STRINGS.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
helper = compact(function_section(runtime_text, "bytes_view_range_ref"))
request_predicate = compact(function_section(runtime_text, "bytes_view_range_ref_request_valid"))
base_view_helper = compact(function_section(runtime_text, "bytes_view"))
required_base_view_steps = (
    "n: usize = buf.count",
    'sview("", 0, 0) return if n == 0',
    'return sview("", 0, 0) if buf.items == null or n > buf.capacity',
    "signed_len: i64 = n.i64()",
    'if signed_len < 0 or signed_len.usize() != n: return sview("", 0, 0)',
    "trusted Unsafe.UncheckedIndex: trusted Unsafe.PointerCast: return StringView{data: &buf[0], len: signed_len}",
)
base_view_positions = [base_view_helper.find(compact(step)) for step in required_base_view_steps]
if any(position < 0 for position in base_view_positions) or base_view_positions != sorted(base_view_positions):
    raise SystemExit("whole-buffer view lost its ordered empty, backing, representation, or guarded-pointer checks")
range_wrapper = compact(function_section(runtime_text, "bytes_view_range"))
required_range_wrapper_steps = (
    "base: sview = bytes_view(buf)",
    "return empty if base.len < 0",
    "base_len: usize = base.len.usize()",
    "return empty if base_len.i64() != base.len or start > base_len or count > base_len - start",
    "start_signed: i64 = start.i64()",
    "count_signed: i64 = count.i64()",
    "return empty if start_signed < 0 or start_signed.usize() != start or count_signed < 0 or count_signed.usize() != count",
    "return string_view_slice(base, start_signed, start_signed + count_signed)",
)
range_wrapper_positions = [range_wrapper.find(compact(step)) for step in required_range_wrapper_steps]
if any(position < 0 for position in range_wrapper_positions) \
        or range_wrapper_positions != sorted(range_wrapper_positions):
    raise SystemExit("by-value bounded view lost its ordered backing, range, conversion, or slice checks")
if compact("ensure result == (buf.count > 0 and buf.items != null and buf.count <= buf.capacity and buf.count.i64() >= 0 and buf.count.i64().usize() == buf.count and start <= buf.count and count <= buf.count - start and start.i64() >= 0 and start.i64().usize() == start and count.i64() >= 0 and count.i64().usize() == count and count > 0 and start < buf.count)") not in request_predicate:
    raise SystemExit("bounded view request predicate lost a backing, extent, or representation condition")
required_contracts = (
    "ensure result.len >= 0",
    "ensure result.len == 0 or result.len == count.i64()",
    "ensure (count == 0) implies result.len == 0",
    "ensure (start > buf.count) implies result.len == 0",
    "ensure (start <= buf.count and count > buf.count - start) implies result.len == 0",
    "ensure (buf.count == 0 or buf.items == null or buf.count > buf.capacity) implies result.len == 0",
    "ensure (buf.count.i64() < 0 or buf.count.i64().usize() != buf.count) implies result.len == 0",
    "ensure (start.i64() < 0 or start.i64().usize() != start) implies result.len == 0",
    "ensure (count.i64() < 0 or count.i64().usize() != count) implies result.len == 0",
    "ensure bytes_view_range_ref_request_valid(buf, start, count) implies result.len == count.i64()",
    "ensure bytes_view_range_ref_request_valid(buf, start, count) implies result.data == &buf[start]",
    "ensure not bytes_view_range_ref_request_valid(buf, start, count) implies result.len == 0",
    "ensure result.len > 0 implies (bytes_view_range_ref_request_valid(buf, start, count) and result.data == &buf[start])",
)
if any(compact(contract) not in helper for contract in required_contracts):
    raise SystemExit("bounded view helper lost a length, fail-closed, extent, or alias contract")

required_guards = (
    "n:usize=buf.count",
    "returnemptyifn==0orbuf.items==nullorn>buf.capacity",
    "returnemptyifsigned_n<0orsigned_n.usize()!=n",
    "returnemptyifstart>norcount>n-start",
    "returnemptyifstart_signed<0orstart_signed.usize()!=startorcount_signed<0orcount_signed.usize()!=count",
    "returnemptyifcount==0",
    "trustedUnsafe.UncheckedIndex:trustedUnsafe.PointerCast:returnStringView{data:&buf[start],len:count_signed}",
)
if any(guard not in helper for guard in required_guards):
    raise SystemExit("bounded view helper lost a backing, range, conversion, or guarded-address check")
if helper.find("returnemptyifstart>norcount>n-start") > helper.find("trustedUnsafe.PointerCast"):
    raise SystemExit("requested byte extent must be checked before the helper constructs its pointer")

sview_at = compact(function_section(runtime_text, "sview_at"))
required_sview_at_contracts = (
    "ensure not string_view_index_request_valid(view, index.i64()) implies result == 0",
    "ensure string_view_index_request_valid(view, index.i64()) implies result == view.data[index]",
    "return string_view_index(view, index.i64()).u8()",
)
if any(compact(contract) not in sview_at for contract in required_sview_at_contracts):
    raise SystemExit("bounded-view composition no longer reaches the guarded production byte reader")

positive_names = {
    "valid_nonempty_range_preserves_length_and_start_address",
    "every_representable_valid_request_returns_its_exact_range",
    "every_invalid_request_fails_closed",
    "zero_width_range_at_end_is_empty",
    "range_crossing_the_buffer_end_fails_closed",
    "empty_buffer_produces_an_empty_view",
    "a_bounded_range_view_reads_only_the_selected_bytes",
    "a_by_value_bounded_range_reads_only_the_selected_bytes",
    "every_valid_nonempty_by_value_range_returns_its_exact_extent",
    "every_well_formed_nonempty_buffer_produces_its_full_view",
}
negative_names = {
    "zero_width_request_can_return_nonempty_view",
    "range_crossing_buffer_end_can_return_nonempty_view",
    "start_past_buffer_end_can_return_nonempty_view",
    "valid_range_can_start_at_the_wrong_byte",
    "valid_request_can_return_the_wrong_length",
    "invalid_request_can_return_nonempty_view",
    "a_bounded_range_view_can_expose_the_byte_after_its_extent",
    "a_by_value_range_can_expose_the_byte_after_its_extent",
    "a_valid_by_value_range_can_return_the_wrong_extent",
    "a_well_formed_nonempty_buffer_can_return_the_wrong_full_view",
}
positive_claims = {
    "valid_nonempty_range_preserves_length_and_start_address": "view.len == 2 and view.data == &bytes[1.usize()]",
    "every_representable_valid_request_returns_its_exact_range": "view.len == count.i64() and view.data == &bytes[start]",
    "every_invalid_request_fails_closed": "view.len == 0",
    "zero_width_range_at_end_is_empty": "view.len == 0",
    "range_crossing_the_buffer_end_fails_closed": "view.len == 0",
    "empty_buffer_produces_an_empty_view": "view.len == 0",
    "a_bounded_range_view_reads_only_the_selected_bytes": "view[0.usize()] == 23 and view[1.usize()] == 37 and view[2.usize()] == 0",
    "a_by_value_bounded_range_reads_only_the_selected_bytes": "view[0.usize()] == 23 and view[1.usize()] == 37 and view[2.usize()] == 0",
    "every_valid_nonempty_by_value_range_returns_its_exact_extent": "view.len == count.i64() and view.data == &bytes[start]",
    "every_well_formed_nonempty_buffer_produces_its_full_view": "view.len == bytes.count.i64() and view.data == &bytes[0.usize()]",
}
positive_preconditions = {
    "every_representable_valid_request_returns_its_exact_range":
        "requires bytes_view_range_ref_request_valid(bytes, start, count)",
    "every_invalid_request_fails_closed":
        "requires not bytes_view_range_ref_request_valid(bytes, start, count)",
    "every_valid_nonempty_by_value_range_returns_its_exact_extent":
        "requires bytes.count > 0 and bytes.items != null and bytes.count <= bytes.capacity requires bytes.count.i64() >= 0 and bytes.count.i64().usize() == bytes.count requires start <= bytes.count and count <= bytes.count - start requires start.i64() >= 0 and start.i64().usize() == start requires count.i64() > 0 and count.i64().usize() == count",
    "every_well_formed_nonempty_buffer_produces_its_full_view":
        "requires bytes.count > 0 and bytes.items != null and bytes.count <= bytes.capacity requires bytes.count.i64() >= 0 and bytes.count.i64().usize() == bytes.count",
}
negative_claims = {
    "zero_width_request_can_return_nonempty_view": "view.len > 0",
    "range_crossing_buffer_end_can_return_nonempty_view": "view.len > 0",
    "start_past_buffer_end_can_return_nonempty_view": "view.len > 0",
    "valid_range_can_start_at_the_wrong_byte": "view.data == &bytes[0.usize()]",
    "valid_request_can_return_the_wrong_length": "view.len != count.i64()",
    "invalid_request_can_return_nonempty_view": "view.len > 0",
    "a_bounded_range_view_can_expose_the_byte_after_its_extent": "view[2.usize()] == 41",
    "a_by_value_range_can_expose_the_byte_after_its_extent": "view[2.usize()] == 41",
    "a_valid_by_value_range_can_return_the_wrong_extent": "view.len != count.i64() or view.data != &bytes[start]",
    "a_well_formed_nonempty_buffer_can_return_the_wrong_full_view": "view.len != bytes.count.i64() or view.data != &bytes[0.usize()]",
}
negative_preconditions = {
    "valid_request_can_return_the_wrong_length":
        "requires bytes_view_range_ref_request_valid(bytes, start, count)",
    "invalid_request_can_return_nonempty_view":
        "requires not bytes_view_range_ref_request_valid(bytes, start, count)",
    "a_valid_by_value_range_can_return_the_wrong_extent":
        "requires bytes.count > 0 and bytes.items != null and bytes.count <= bytes.capacity requires bytes.count.i64() >= 0 and bytes.count.i64().usize() == bytes.count requires start <= bytes.count and count <= bytes.count - start requires start.i64() >= 0 and start.i64().usize() == start requires count.i64() > 0 and count.i64().usize() == count",
    "a_well_formed_nonempty_buffer_can_return_the_wrong_full_view":
        "requires bytes.count > 0 and bytes.items != null and bytes.count <= bytes.capacity requires bytes.count.i64() >= 0 and bytes.count.i64().usize() == bytes.count",
}
if set(positive_claims) != positive_names or set(negative_claims) != negative_names \
        or not set(positive_preconditions) <= positive_names \
        or not set(negative_preconditions) <= negative_names:
    raise SystemExit("bounded-view theorem claims no longer cover their exact inventories")
for source_text, names, label in (
    (positive_text, positive_names, "positive"),
    (negative_text, negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} bounded-view theorem inventory changed")
    if f'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source_text \
            or f'include "../../elisacore_std/elisacore_runtime_strings.elisa"' not in source_text:
        raise SystemExit(f"{label} bounded-view proofs no longer import the production helper")
for name, claim in positive_claims.items():
    section = compact(function_section(positive_text, name))
    if compact("ensure result == true") not in section \
            or ("bytes_view_range_ref(" not in section and "bytes_view_range(" not in section \
                and "bytes_view(" not in section) \
            or compact(claim) not in section:
        raise SystemExit(f"positive bounded-view theorem {name} lost its checked claim")
for name, precondition in positive_preconditions.items():
    if compact(precondition) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"positive bounded-view theorem {name} lost its request precondition")
for name, claim in negative_claims.items():
    section = compact(function_section(negative_text, name))
    if compact("ensure result == true") not in section or compact(claim) not in section \
            or ("bytes_view_range_ref(" not in section and "bytes_view_range(" not in section \
                and "bytes_view(" not in section):
        raise SystemExit(f"false bounded-view control {name} lost its rejected claim")
for name, precondition in negative_preconditions.items():
    if compact(precondition) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"false bounded-view control {name} lost its request precondition")

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
    raise SystemExit("bounded borrowed-view proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", PRELUDE, RUNTIME_STRINGS,
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
    "scope": "bounded borrowed StringView ranges preserve requested extents and fail closed",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
