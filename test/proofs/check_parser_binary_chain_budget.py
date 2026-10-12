"""Admit the arithmetic proof for the parser's bounded binary-expression chain."""
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
POSITIVE = HERE / "parser_binary_chain_budget.elisa"
NEGATIVE = HERE / "parser_binary_chain_budget_rejected.elisa"
SOURCE = ROOT / "src/parser/parser_expr_binary.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^[ \t]*def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^[ \t]*def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate production function {name}")
    return match.group(1)


source = SOURCE.read_text()
if not re.search(r"(?m)^\s*const BINARY_CHAIN_LIMIT: u32 = 2000\s*$", source):
    raise SystemExit("production binary-chain limit changed")
loop = compact(function_body(source, "binary_expression_at_level"))
step_body = compact(function_body(source, "binary_expression_step"))
left_nesting = "active<-(Ast::Expr.Binary(active,operator_kind,right,Ast::pos_of_token(advanced_operator_token)))"
if step_body.find(left_nesting) < 0 or step_body.rfind("returnactive") < step_body.find(left_nesting):
    raise SystemExit("a successful binary continuation no longer extends and returns the left AST spine")
guard = "ifbinary_count>=BINARY_CHAIN_LIMIT:"
error = "parser<-parser.error_at(Ast::ParseErrorKind.UnexpectedToken,parser.cursor())"
step = "parser.binary_expression_step(active,minimum_precedence)"
increment = "binary_count<-binary_count+1"
ordered = [loop.find(fragment) for fragment in ("binary_count:mutableu32=0", guard, error, step, increment)]
if any(position < 0 for position in ordered) or ordered != sorted(ordered):
    raise SystemExit("binary-chain counter, error guard, parser step, or increment changed order")
updated_guard = loop.find("ifnextisupdated:")
active_update = loop.find("active<-updated", updated_guard)
increment_position = loop.find(increment)
if (
    loop.count(increment) != 1
    or updated_guard < ordered[2]
    or active_update < updated_guard
    or increment_position < active_update
):
    raise SystemExit("binary-chain counter must advance exactly once for a parsed continuation")
guard_return = loop.find("returnactive", loop.find(guard))
if not ordered[2] < guard_return < ordered[3]:
    raise SystemExit("binary-chain cap must report and return before parsing another operator")
if loop.find("returnactive", increment_position) < 0:
    raise SystemExit("binary-expression loop must return when no continuation was parsed")

positive_names = {
    "successful_continuation_stays_within_limit",
    "limit_guard_blocks_another_continuation",
}
negative_names = {"parser_can_continue_at_limit"}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != expected:
        raise SystemExit(f"{path.name} declaration inventory changed")

positive_claims = {
    "successful_continuation_stays_within_limit": (
        "requirescount<BINARY_CHAIN_LIMITensureresult==truereturncount+1<=BINARY_CHAIN_LIMITandcount<count+1"
    ),
    "limit_guard_blocks_another_continuation": (
        "requirescount>=BINARY_CHAIN_LIMITensureresult==falsereturncount<BINARY_CHAIN_LIMIT"
    ),
}
for name, expected in positive_claims.items():
    if compact(function_body(POSITIVE.read_text(), name)).replace("\n", "") != expected:
        raise SystemExit(f"{name} no longer proves the intended parser-chain invariant")
if compact(function_body(NEGATIVE.read_text(), "parser_can_continue_at_limit")).replace("\n", "") != (
    "requirescount==BINARY_CHAIN_LIMITensureresult==truereturncount<BINARY_CHAIN_LIMIT"
):
    raise SystemExit("negative control no longer asserts that the parser continues at its limit")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("parser binary-chain proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE, SOURCE,
]
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 4
assert not positive["findings"]
assert {
    row["name"] for row in positive["declaration_details"] if row.get("verified")
} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 2 and negative["summary"]["proven"] == 1
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "parser_can_continue_at_limit")
]

assert require_current_product(BIN, PROVER) == product, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "binary-chain cap bounds successful growth of the parser's left AST spine and rejects at the limit",
    "positive_obligations": positive["summary"]["proven"],
    "false_claim_rejected": "parser_can_continue_at_limit",
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
