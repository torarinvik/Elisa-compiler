"""Admit source-linked proofs for the AST-spacing and doc-operator token sets."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "driver_token_classification.elisa"
NEGATIVE = HERE / "driver_token_classification_rejected.elisa"
PROJECTION = HERE / "parser_token_kind_projection.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
CLASSIFIER = ROOT / "src/driver/driver_token_classification.elisa"
AST = ROOT / "src/driver/elisac_emit_ast.elisa"
DOC = ROOT / "src/driver/elisac_emit_doc.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


classifier = compact(CLASSIFIER.read_text())
positive = compact(POSITIVE.read_text())
negative = compact(NEGATIVE.read_text())
ast = compact(AST.read_text())
doc = compact(DOC.read_text())
driver_source = DRIVER.read_text()

expected_spacing_contract = compact(
    "ensure result == (kind == Lexer::TokenKind.Heap or kind == Lexer::TokenKind.Stack "
    "or kind == Lexer::TokenKind.Static or kind == Lexer::TokenKind.Mutable "
    "or kind == Lexer::TokenKind.Tail)"
)
expected_operator_contract = compact(
    "ensure result == (kind == Lexer::TokenKind.EqEq or kind == Lexer::TokenKind.BangEq "
    "or kind == Lexer::TokenKind.Lt or kind == Lexer::TokenKind.Gt "
    "or kind == Lexer::TokenKind.LtEq or kind == Lexer::TokenKind.GtEq "
    "or kind == Lexer::TokenKind.And or kind == Lexer::TokenKind.Or "
    "or kind == Lexer::TokenKind.Plus or kind == Lexer::TokenKind.Minus "
    "or kind == Lexer::TokenKind.Star or kind == Lexer::TokenKind.Slash)"
)
if expected_spacing_contract not in classifier or expected_spacing_contract not in positive:
    raise SystemExit("AST spacing proof no longer states the exact finite token contract")
if expected_operator_contract not in classifier or expected_operator_contract not in positive:
    raise SystemExit("doc operator proof no longer states the exact finite token contract")
expected_spacing_arm = compact(
    "Lexer::TokenKind.Heap | Lexer::TokenKind.Stack | Lexer::TokenKind.Static | "
    "Lexer::TokenKind.Mutable | Lexer::TokenKind.Tail -> true"
)
expected_operator_arm = compact(
    "Lexer::TokenKind.EqEq | Lexer::TokenKind.BangEq | Lexer::TokenKind.Lt | "
    "Lexer::TokenKind.Gt | Lexer::TokenKind.LtEq | Lexer::TokenKind.GtEq | "
    "Lexer::TokenKind.And | Lexer::TokenKind.Or | Lexer::TokenKind.Plus | "
    "Lexer::TokenKind.Minus | Lexer::TokenKind.Star | Lexer::TokenKind.Slash -> true"
)
if f"returnwhenkind:{expected_spacing_arm}_->false" not in classifier:
    raise SystemExit("production AST spacing classifier lost its exhaustive pattern match")
if f"returnwhenkind:{expected_operator_arm}_->false" not in classifier:
    raise SystemExit("production doc operator classifier lost its exhaustive pattern match")


def enum_variants(text: str) -> list[str]:
    enum = re.search(
        r"(?ms)^\s*const enum TokenKind of u8:\n(.*?)(?=^\s*(?:struct|const enum|def) |\Z)",
        text,
    )
    if not enum:
        raise SystemExit("complete production TokenKind enum is missing")
    return [line.strip() for line in enum.group(1).splitlines()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.strip())]


if enum_variants(TOKENS.read_text()) != enum_variants(PROJECTION.read_text()):
    raise SystemExit("proof TokenKind projection differs from the production enum order")
if 'include"./parser_token_kind_projection.elisa"' not in positive:
    raise SystemExit("positive proof no longer imports the complete token projection")
if 'include"../../src/driver/driver_token_classification.elisa"' not in positive:
    raise SystemExit("positive proof no longer imports production token classifiers")
if 'include"./parser_token_kind_projection.elisa"' not in negative:
    raise SystemExit("negative proof no longer imports the complete token projection")
if 'include"../../src/driver/driver_token_classification.elisa"' not in negative:
    raise SystemExit("false claims no longer import the source-linked proof classifiers")

for declaration in (
    "source_ast_spacing_token_match_is_exact",
    "all_ast_spacing_tokens_are_recognized",
    "nearby_ast_tokens_need_no_extra_space",
    "source_doc_operator_token_match_is_exact",
    "every_binary_operator_is_recognized",
    "nearby_doc_tokens_are_not_binary_operators",
):
    if f"def{declaration}(" not in positive:
        raise SystemExit(f"positive proof lost {declaration}")

if "DriverTokenClassification::needs_ast_token_space(kind)" not in ast:
    raise SystemExit("AST renderer no longer delegates to its proved token classifier")
if "DriverTokenClassification::is_doc_binary_operator(kind)" not in doc:
    raise SystemExit("doc renderer no longer delegates to its proved token classifier")
if 'include "./driver_token_classification.elisa"' not in driver_source:
    raise SystemExit("compiler driver no longer includes the proved classifiers")
if driver_source.index('include "./driver_token_classification.elisa"') > driver_source.index('include "./elisac_emit_ast.elisa"'):
    raise SystemExit("compiler driver includes token classifiers after the AST consumer")
if driver_source.index('include "./driver_token_classification.elisa"') > driver_source.index('include "./elisac_emit_doc.elisa"'):
    raise SystemExit("compiler driver includes token classifiers after the doc consumer")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("driver token-classification proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, AST, DOC, DRIVER])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    TOKENS, PROJECTION, CLASSIFIER, AST, DOC, DRIVER, *source_closure,
]
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


code, proved = run(POSITIVE)
assert code == 0 and proved["status"] == proved["verification_state"] == "proved"
assert proved["summary"]["proven"] == proved["summary"]["obligations"]
assert not proved["findings"]
assert proved == run(POSITIVE)[1], "driver token-classification proof changed across repeated runs"
verified = {row["name"] for row in proved["declaration_details"] if row.get("verified")}
assert {
    "needs_ast_token_space",
    "is_doc_binary_operator",
    "source_ast_spacing_token_match_is_exact",
    "all_ast_spacing_tokens_are_recognized",
    "nearby_ast_tokens_need_no_extra_space",
    "source_doc_operator_token_match_is_exact",
    "every_binary_operator_is_recognized",
    "nearby_doc_tokens_are_not_binary_operators",
} <= verified

code, rejected = run(NEGATIVE)
negative_names = {
    "identifier_must_not_need_ast_spacing",
    "assignment_must_not_be_a_doc_binary_operator",
}
assert code == 1 and rejected["status"] == rejected["verification_state"] == "failed"
assert {row["name"] for row in rejected["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in rejected["findings"])
assert require_current_product(BIN, PROVER) == manifest
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed TokenKind sets used by AST spacing and doc binary-operator rendering",
    "positive_obligations": proved["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
