"""Admit proofs for unsupported frontend-IR declaration refusal paths."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POLICY = ROOT / "src/driver/frontend_ir_decl_policy.elisa"
DECL_WRITER = ROOT / "src/driver/frontend_ir_decl.elisa"
POSITIVE = HERE / "frontend_ir_decl_refusal.elisa"
NEGATIVE = HERE / "frontend_ir_decl_refusal_rejected.elisa"
TIMEOUT_SECONDS = 60
AST_DECL = ROOT / "src/parser/ast_nodes.elisa"


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def variants_in_enum(source: str, name: str, indent: int) -> list[str]:
    header = re.search(rf"(?m)^{indent_space(indent)}enum {re.escape(name)}(?: is Node)?:\s*$", source)
    if header is None:
        raise SystemExit(f"missing enum {name}")
    following = re.search(r"(?m)^\s*enum [A-Za-z_][A-Za-z0-9_]*(?: is Node)?:\s*$", source[header.end():])
    body = source[header.end():header.end() + following.start()] if following else source[header.end():]
    return re.findall(rf"(?m)^{indent_space(indent + 4)}([A-Za-z_][A-Za-z0-9_]*)(?:\s*\(|\s*$)", body)


def indent_space(count: int) -> str:
    return " " * count


policy_text = POLICY.read_text()
expected_policy = {
    "function_requires_refusal": "return body_needs_stage0_auto_region",
    "struct_requires_refusal": "return has_named_states or has_derive",
    "scoped_declaration_requires_refusal": "return true",
}
for name, expected in expected_policy.items():
    normalized = compact(function_section(policy_text, name))
    if "->bool:" not in normalized or normalized.split("->bool:", 1)[1] != compact(expected):
        raise SystemExit(f"{name} changed from the predicate modeled by this proof")

constructor_names = ["Invalid", "Func", "Struct", "Enum", "Alias", "Law", "Import", "Scoped", "Extern", "Const", "Module"]
ast_decl_variants = variants_in_enum(AST_DECL.read_text(), "Decl", 4)
proof_decl_variants = variants_in_enum(POSITIVE.read_text(), "FrontendIrDeclConstructor", 0)
if ast_decl_variants != constructor_names:
    raise SystemExit(f"Ast::Decl constructor inventory changed: {ast_decl_variants}")
if proof_decl_variants != constructor_names:
    raise SystemExit("proof constructor model no longer matches the complete Ast::Decl inventory")
route_names = ["ConditionalRefusal", "DirectEncoding", "DelegatedEncoding", "UnconditionalRefusal", "FallbackRefusal"]
if variants_in_enum(POSITIVE.read_text(), "FrontendIrDeclRoute", 0) != route_names:
    raise SystemExit("proof declaration-route inventory changed")

routes = {
    "Invalid": "FallbackRefusal",
    "Func": "ConditionalRefusal",
    "Struct": "ConditionalRefusal",
    "Enum": "DirectEncoding",
    "Alias": "DirectEncoding",
    "Law": "FallbackRefusal",
    "Import": "DirectEncoding",
    "Scoped": "UnconditionalRefusal",
    "Extern": "DelegatedEncoding",
    "Const": "DirectEncoding",
    "Module": "DirectEncoding",
}
route_match = compact(function_section(POSITIVE.read_text(), "declaration_constructor_route"))
expected_route_match = compact("return match kind: " + " ".join(
    f"FrontendIrDeclConstructor.{kind}: FrontendIrDeclRoute.{route}"
    for kind, route in routes.items()
))
if expected_route_match not in route_match:
    raise SystemExit("declaration constructor route model no longer covers every AST constructor")

decl_source = DECL_WRITER.read_text()
if 'include "./frontend_ir_decl_policy.elisa"' not in decl_source:
    raise SystemExit("declaration writer no longer imports the proved refusal predicates")
decl_body = function_section(decl_source, "ir_decl_node")
arms = list(re.finditer(r"(?m)^[ \t]*Ast::Decl\.([A-Za-z_][A-Za-z0-9_]*)\(", decl_body))
arm_bodies: dict[str, str] = {}
for index, match in enumerate(arms):
    end = arms[index + 1].start() if index + 1 < len(arms) else len(decl_body)
    arm_bodies[match.group(1)] = decl_body[match.start():end]
if set(arm_bodies) != set(constructor_names) - {"Invalid", "Law"}:
    raise SystemExit("ir_decl_node explicit arms no longer cover the expected constructors")
fallback_match = re.search(r"(?m)^[ \t]*_:\s*$", decl_body)
if fallback_match is None or compact(decl_body[fallback_match.start():]).find(
    compact('_: ir_refuse(refusal, "declaration") return 0')
) != 0:
    raise SystemExit("unhandled declaration constructors no longer fail closed before returning node ID zero")
for constructor, route in routes.items():
    if route == "DirectEncoding" and "ir_emit_node(" not in compact(arm_bodies[constructor]):
        raise SystemExit(f"{constructor} is classified as directly encoded but no longer emits a declaration node")
if "ir_extern_decl_node(" not in compact(arm_bodies["Extern"]):
    raise SystemExit("Extern is classified as delegated but no longer delegates to the extern writer")

refusal_paths = {
    "Func": (
        "if FrontendIrDeclPolicy::function_requires_refusal(ir_body_allocates_regionlessly(body)):",
        'ir_refuse(refusal, "function body needing stage0\'s synthesized auto-region") return 0',
        "ir_param_out(",
    ),
    "Struct": (
        "if FrontendIrDeclPolicy::struct_requires_refusal(has_named_states, has_derive):",
        'ir_refuse(refusal, "typestate struct") return 0',
        "ir_field_decl_out(",
    ),
    "Scoped": (
        "if FrontendIrDeclPolicy::scoped_declaration_requires_refusal():",
        'ir_refuse(refusal, "impl / static-if scope (one node in stage1)") return 0',
        None,
    ),
}
for arm, (guard, refusal, later_writer) in refusal_paths.items():
    source = arm_bodies.get(arm, "")
    body = compact(source)
    guard_at = body.find(compact(guard))
    refusal_at = body.find(compact(refusal), guard_at + 1)
    if guard_at < 0 or refusal_at < guard_at:
        raise SystemExit(f"{arm} declaration no longer guards the proved refusal path")
    if later_writer is not None:
        writer_at = body.find(compact(later_writer), guard_at + 1)
        if writer_at < 0 or not guard_at < refusal_at < writer_at:
            raise SystemExit(f"{arm} refusal no longer precedes nested or field encoding")
    for operation in ("ir_put_", "ir_emit_node(", "ir_param_out(", "ir_field_decl_out(", "ir_stmt_node("):
        operation_at = body.find(compact(operation))
        if operation_at >= 0 and operation_at < guard_at:
            raise SystemExit(f"{arm} declaration writes output before its refusal guard")
    if body.count(compact(guard)) != 1 or body.count(compact(refusal)) != 1:
        raise SystemExit(f"{arm} declaration refusal path is duplicated or ambiguous")

scoped_prefix = compact(
    'Ast::Decl.Scoped(_, _): '
    'if FrontendIrDeclPolicy::scoped_declaration_requires_refusal(): '
    'ir_refuse(refusal, "impl / static-if scope (one node in stage1)") '
    'return 0'
)
if not compact(arm_bodies.get("Scoped", "")).startswith(scoped_prefix):
    raise SystemExit("Scoped declarations no longer begin with the proved unconditional refusal path")

positive_names = {
    "declaration_constructor_route",
    "regionless_function_body_is_refused",
    "ordinary_function_body_is_not_refused",
    "typestate_struct_is_refused",
    "ordinary_struct_is_not_refused",
    "scoped_declaration_is_always_refused",
}
negative_names = {
    "false_claim_plain_function_needs_refusal",
    "false_claim_ordinary_struct_needs_refusal",
    "false_claim_typestate_struct_is_admitted",
    "false_claim_scoped_declaration_is_admitted",
    "false_claim_law_has_direct_encoder",
    "false_claim_invalid_has_direct_encoder",
}
if declarations(POSITIVE) != positive_names:
    raise SystemExit("positive declaration-refusal proof inventory changed")
if declarations(NEGATIVE) != negative_names:
    raise SystemExit("rejected declaration-refusal proof inventory changed")
if 'include "../../src/driver/frontend_ir_decl_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer includes the production refusal policy")
if 'include "./frontend_ir_decl_refusal.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative proof no longer reuses the positive source-linked lemmas")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("declaration-refusal proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_include_closure([POSITIVE, NEGATIVE, DECL_WRITER, AST_DECL]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=TIMEOUT_SECONDS)
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
assert positive == run(POSITIVE)[1], "declaration-refusal proof report changed across replay"
assert positive_names <= {
    row["name"] for row in positive["declaration_details"] if row.get("verified")
}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(row["status"] == "disproved" and row["counterexample_found"]
           for row in negative["findings"])
assert product == require_current_product(BIN, PROVER)
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "declaration-refusal proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "function, struct, and scoped-declaration refusal guards in the frontend IR writer",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
