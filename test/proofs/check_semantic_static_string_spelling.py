"""Admit the source-linked static-string spelling classifier and refuse false claims."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "semantic_static_string_spelling.elisa"
NEGATIVE = HERE / "semantic_static_string_spelling_rejected.elisa"
SOURCE = ROOT / "src/semantic/static_string_spelling.elisa"
USES = ROOT / "src/semantic/check_static_string_binding.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

SPELLINGS = ("lit", "mixed", "static u8&")
source_text = SOURCE.read_text()
use_text = USES.read_text()
proof_text = POSITIVE.read_text()


def match_arms(text: str, description: str) -> None:
    arms = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        arm = re.fullmatch(r'("[^"\\]+"(?:\s*\|\s*"[^"\\]+")*|_)\s*->\s*(true|false)', stripped)
        if not arm:
            raise SystemExit(f"{description} contains a malformed pattern arm")
        patterns, value = arm.groups()
        names = re.findall(r'"([^"\\]+)"', patterns)
        arms.append((patterns, value, names))
    if not arms or arms[-1][:2] != ("_", "false"):
        raise SystemExit(f"{description} lost its false fallback")
    flattened = [name for _, value, names in arms[:-1] if value == "true" for name in names]
    if any(value != "true" for _, value, _ in arms[:-1]) or flattened != list(SPELLINGS):
        raise SystemExit(f"{description} differs from the exact closed spelling set")


def require_exact_set(text: str, description: str) -> None:
    contract = re.search(r"(?m)^\s*ensure result == \(when spelling:\s*\n(.*?)^\s*\)", text, re.DOTALL)
    if not contract:
        raise SystemExit(f"{description} must specify the closed set in its contract")
    match_arms(contract.group(1), description + " contract")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(text: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", text))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one production function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


require_exact_set(source_text, "production classifier")
require_exact_set(proof_text, "proof contract")
implementation = re.search(
    r"(?m)^\s*return when spelling:\s*\n(.*?)(?=^\s*def |\Z)",
    source_text,
    re.DOTALL,
)
if not implementation:
    raise SystemExit("production classifier lost its pattern-matching implementation")
match_arms(implementation.group(1), "production classifier implementation")
if 'include "./static_string_spelling.elisa"' not in use_text:
    raise SystemExit("static-string checker no longer imports the proved classifier")
static_join = compact(function_section(use_text, "static_join"))
if "left_static:bool=StaticStringSpelling::participates_in_static_join(left)" not in static_join or \
        "right_static:bool=StaticStringSpelling::participates_in_static_join(right)" not in static_join:
    raise SystemExit("both static_join operands must use the proved spelling classifier")
binding_flow = compact(function_section(use_text, "record_static_binding"))
if "bound_static:bool=StaticStringSpelling::participates_in_static_join(accumulator_spelling)" not in binding_flow or \
        "bound_static:bool=StaticStringSpelling::participates_in_static_join(value_spelling)" not in binding_flow:
    raise SystemExit("both static binding paths must use the proved spelling classifier")
if "def participates_in_static_join(spelling: sview) -> bool:" not in source_text:
    raise SystemExit("production spelling classifier declaration changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("static-string spelling proof requires a strict proof build")

compiler_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
compiler_provenance = Path(str(compiler_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    compiler_product, compiler_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE]), SOURCE, USES,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
expected = {
    "participates_in_static_join",
    "source_predicate_has_exact_spelling_set",
    "every_join_spelling_is_recognized",
    "nearby_spellings_do_not_join",
}
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == {
    "unknown_spelling_must_join", "mutable_spelling_must_join"
}
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == product
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "static-string join spelling classifier",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(row["name"] for row in negative["findings"]),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
