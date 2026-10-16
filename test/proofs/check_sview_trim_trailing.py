"""Bind maximal-prefix trim proofs to the runtime loop and its slice contracts."""
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
RUNTIME = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
POSITIVE = HERE / "sview_trim_trailing.elisa"
NEGATIVE = HERE / "sview_trim_trailing_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
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
    following = re.search(
        rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(",
        source[match.end():],
    )
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


runtime_text = RUNTIME.read_text()
trim = compact(function_section(runtime_text, "sview_trim_trailing"))
required_trim_contracts = (
    "ensure result.len >= 0 and result.len <= (view.len if view.len > 0 and view.len.usize().i64() == view.len else 0)",
    "ensure result.len > 0 implies (string_view_index(view, result.len - 1) != byte.i64() and result.data == view.data)",
    "ensure forall suffix_index in result.len..<(view.len if view.len > 0 and view.len.usize().i64() == view.len else 0): string_view_index(view, suffix_index) == byte.i64()",
)
if any(compact(contract) not in trim for contract in required_trim_contracts):
    raise SystemExit("trailing trim lost its bounded maximal-prefix postcondition")
required_loop_steps = (
    'return sview("", 0, 0) if view.len < 0',
    "view_len: usize = view.len.usize()",
    'return sview("", 0, 0) if view_len.i64() != view.len',
    "assert view.len >= 0 and view_len.i64() == view.len",
    "hi: mutable i64 = view.len",
    "assert hi == view.len",
    "assert forall suffix_index in hi..<view.len: string_view_index(view, suffix_index) == byte.i64()",
    "while hi > 0 and string_view_index(view, hi - 1) == byte.i64():",
    "decreases hi",
    "invariant 0 <= hi and hi <= view.len and hi.usize().i64() == hi",
    "invariant forall suffix_index in hi..<view.len: string_view_index(view, suffix_index) == byte.i64()",
    "hi <- hi - 1",
    "return string_view_prefix(view, hi)",
)
loop_positions = [trim.find(compact(step)) for step in required_loop_steps]
if any(position < 0 for position in loop_positions) or loop_positions != sorted(loop_positions):
    raise SystemExit("trailing trim loop lost its range, progress, suffix, or return invariant")

slice_body = compact(function_section(runtime_text, "string_view_slice"))
prefix_body = compact(function_section(runtime_text, "string_view_prefix"))
suffix_body = compact(function_section(runtime_text, "string_view_suffix"))
required_slice_contracts = (
    "ensure result.len >= 0 and result.len <= (view.len if view.len > 0 and view.len.usize().i64() == view.len else 0)",
    "ensure (view.len >= 0 and view.len.usize().i64() == view.len) implies result.len == ((view.len if end < 0 else (start if start > 0 and start <= view.len else view.len if start > view.len else 0) if end < (start if start > 0 and start <= view.len else view.len if start > view.len else 0) else end if end <= view.len else view.len) - (start if start > 0 and start <= view.len else view.len if start > view.len else 0))",
    "ensure (view.len >= 0 and view.len.usize().i64() == view.len and result.len > 0) implies result.data == view.data + (start if start > 0 and start <= view.len else view.len if start > view.len else 0).usize()",
)
required_prefix_contracts = (
    "ensure (view.len >= 0 and view.len.usize().i64() == view.len) implies result.len == (view.len if end < 0 else end if end <= view.len else view.len)",
    "ensure (view.len >= 0 and view.len.usize().i64() == view.len and end >= 0 and end <= view.len) implies result.len == end",
    "ensure (view.len >= 0 and view.len.usize().i64() == view.len and result.len > 0) implies result.data == view.data",
)
if any(compact(contract) not in slice_body for contract in required_slice_contracts) \
        or any(compact(contract) not in prefix_body for contract in required_prefix_contracts):
    raise SystemExit("trim proof dependencies lost their bounded prefix length or backing-address contract")
suffix_contracts = (
    "ensure result.len >= 0 and result.len <= (view.len if view.len > 0 and view.len.usize().i64() == view.len else 0)",
    "ensure (view.len >= 0 and view.len.usize().i64() == view.len) implies result.len == view.len - (start if start > 0 and start <= view.len else view.len if start > view.len else 0)",
    "ensure (view.len >= 0 and view.len.usize().i64() == view.len and result.len > 0) implies result.data == view.data + (start if start > 0 and start <= view.len else view.len if start > view.len else 0).usize()",
)
if any(compact(contract) not in suffix_body for contract in suffix_contracts):
    raise SystemExit("StringView suffix lost its clamped extent or backing-address contract")

positive_names = {"a_trimmed_view_keeps_the_maximal_prefix"}
negative_names = {
    "trimming_can_leave_the_selected_byte_at_the_prefix_end",
    "trimming_can_drop_a_nonmatching_byte",
}
claims = {
    "a_trimmed_view_keeps_the_maximal_prefix": "trimmed.len >= 0 and trimmed.len <= view.len and (trimmed.len == 0 or string_view_index(view, trimmed.len - 1) != byte.i64()) and (forall suffix_index in trimmed.len..<view.len: string_view_index(view, suffix_index) == byte.i64()) and (trimmed.len == 0 or trimmed.data == view.data)",
    "trimming_can_leave_the_selected_byte_at_the_prefix_end":
        "trimmed.len > 0 and string_view_index(view, trimmed.len - 1) == byte.i64()",
    "trimming_can_drop_a_nonmatching_byte":
        "trimmed.len < view.len and string_view_index(view, trimmed.len) != byte.i64()",
}
precondition = "requires view.len >= 0 and view.len.usize().i64() == view.len"
for source_text, names, label in (
    (POSITIVE.read_text(), positive_names, "positive"),
    (NEGATIVE.read_text(), negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} trailing-trim theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source_text \
            or 'include "../../elisacore_std/elisacore_runtime_strings.elisa"' not in source_text:
        raise SystemExit(f"{label} trailing-trim theorem no longer includes the production runtime")
    for name in names:
        section = compact(function_section(source_text, name))
        if compact("ensure result == true") not in section or compact(precondition) not in section \
                or compact(claims[name]) not in section \
                or compact("sview_trim_trailing(view, byte)") not in section:
            raise SystemExit(f"{label} trailing-trim theorem {name} lost its claim or precondition")

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
    raise SystemExit("StringView trailing-trim proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", RUNTIME, POSITIVE, NEGATIVE, *source_closure,
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
    "scope": "sview_trim_trailing returns a maximal prefix with a nonmatching boundary and an all-matching removed suffix",
    "positive_claims_proved": sorted(positive_names),
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
