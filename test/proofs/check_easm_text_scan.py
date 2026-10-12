"""Admit the source-linked EASM first-whitespace scan proof."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/backend/easm_text_scan.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
PARSER = ROOT / "src/backend/easm_verify_function.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
EASM_PARSE = ROOT / "src/backend/easm_parse.elisa"
POSITIVE = HERE / "easm_text_scan.elisa"
NEGATIVE = HERE / "easm_text_scan_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


source_text = SOURCE.read_text()
source_compact = compact(source_text)
if 'include "easm_text_scan.elisa"' not in ENV.read_text():
    raise SystemExit("backend environment does not import the verified EASM text scanner")
if "returnEasmTextScan::first_space(text).usize()" not in compact(function_section(PARSER.read_text(), "easm_first_space")):
    raise SystemExit("production EASM whitespace helper no longer delegates to the verified scanner")
for caller in (PARSER.read_text(), PROVENANCE.read_text(), EASM_PARSE.read_text()):
    if "easm_first_space(" not in caller:
        raise SystemExit("an EASM parser source lost its use of the verified whitespace helper")
required_source = (
    "ensureresult>=0",
    "ensuretext.length<0impliesresult==0",
    "ensuretext.length>=0impliesresult<=text.length",
    "text.length<0orresult==text.lengthor(result<text.lengthand(text[result]==32ortext[result]==9))",
    "ensure(forallprefix_indexin0..<result:text.length<0orprefix_index>=text.lengthor(text[prefix_index]!=32andtext[prefix_index]!=9))",
    "whileindex<text.length|index,text|",
    "decreasestext.length-index",
    "invariantindex>=0",
    "invarianttext.length<0impliesindex==0",
    "invarianttext.length>=0impliesindex<=text.length",
    "invariantforallprefix_indexin0..<index:text.length<0orprefix_index>=text.lengthor(text[prefix_index]!=32andtext[prefix_index]!=9)",
    "returnindexiftext[index]==32ortext[index]==9",
    "index<-index+1",
)
if not all(fragment in source_compact for fragment in required_source):
    raise SystemExit("production EASM scanner lost its first-match contract or loop invariant")
if 'include "../../src/backend/easm_text_scan.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer includes the production EASM scanner")
positive_compact = compact(POSITIVE.read_text())
required_positive_claims = (
    "deffirst_space_contract_holds(text:sview)->bool:",
    "ensureresult==true",
    "position:i64=EasmTextScan::first_space(text)",
    "position>=0",
    "text.length<0orposition==0",
    "text.length<0orposition<=text.length",
    "text.length<0orposition==text.lengthor(",
    "forallprefix_indexin0..<position:text.length<0orprefix_index>=text.lengthor(text[prefix_index]!=32andtext[prefix_index]!=9)",
)
if not all(fragment in positive_compact for fragment in required_positive_claims):
    raise SystemExit("positive proof no longer states the production scanner's complete postcondition")
if 'include "./easm_text_scan.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer includes the positive EASM scanner proof")
if "EasmTextScan::first_space(\"a b\")" not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer challenges first-separator behavior")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("EASM scanner proof requires a strict proof build")

inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    SOURCE,
    ENV,
    PARSER,
    PROVENANCE,
    EASM_PARSE,
]
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs.extend((stage1_product, stage1_provenance))
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
assert positive == run(POSITIVE)[1], "EASM scanner proof report changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["semantic_errors"] == 0
assert negative["summary"]["proven"] + 1 == negative["summary"]["obligations"]
assert [finding["name"] for finding in negative["findings"]] == ["false_claim_scanner_skips_the_first_separator"]
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert not any(row.get("verified") and row.get("name") == "false_claim_scanner_skips_the_first_separator"
               for row in negative["declaration_details"])

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof-product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "production EASM scanner returns the first ASCII space or tab and proves all prior bytes are not separators",
    "positive_obligations": positive["summary"]["proven"],
    "false_claim_rejected": negative["findings"][0]["name"],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
