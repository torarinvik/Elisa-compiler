"""Admit source-linked proofs of unary binding capability propagation."""
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
POLICY = ROOT / "src/semantic/binding_capability_unary_policy.elisa"
RESOLVER = ROOT / "src/semantic/resolve_binding_capabilities.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "binding_capability_unary_policy.elisa"
NEGATIVE = HERE / "binding_capability_unary_policy_rejected.elisa"
PROOF_REPLAY_TIMEOUT_SECONDS = 60

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


policy_text = POLICY.read_text()
derive = compact(function_section(policy_text, "derive"))
expected_policy = compact("""
    ensure result.borrowed == (original_borrowed or is_ampersand or is_lmut)
    ensure result.writable == (original_writable or is_lmut or (is_mutable and (original_borrowed or is_ampersand or is_lmut)) or (is_ampersand and inner_type_is_mutable))
    ensure result.linear_mutable == (original_linear_mutable or is_lmut)
    return Flags{
        borrowed: original_borrowed or is_ampersand or is_lmut,
        writable: original_writable or is_lmut or (is_mutable and (original_borrowed or is_ampersand or is_lmut)) or (is_ampersand and inner_type_is_mutable),
        linear_mutable: original_linear_mutable or is_lmut
    }
""")
if expected_policy not in derive:
    raise SystemExit("production unary policy no longer implements its exact flag formulas")

resolver_text = RESOLVER.read_text()
if 'include "./binding_capability_unary_policy.elisa"' not in resolver_text:
    raise SystemExit("binding-capability resolver no longer imports the proved policy")
if 'include "./resolve_binding_capabilities.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic compilation no longer imports the resolver")
require_resolver = compact(function_section(resolver_text, "resolve_binding_capabilities"))
for fragment in (
    "return unknown_binding_capabilities() if depth >= BINDING_CAPABILITY_MAX_RESOLUTION_DEPTH",
    "BindingCapabilityUnaryPolicy::derive(result.borrowed, result.writable, result.linear_mutable, operator == TokenKind.Ampersand, operator == TokenKind.Lmut, operator == TokenKind.Mutable, type_is_mutable(inner))",
    "BindingCapabilities{known: result.known, borrowed: flags.borrowed, writable: flags.writable, linear_mutable: flags.linear_mutable, declaration_id: result.declaration_id}",
):
    if compact(fragment) not in require_resolver:
        raise SystemExit("unary resolver no longer applies the proved policy to the resolved operand")
resolver_without_named_sentinels = compact(resolver_text).replace(
    compact("const BINDING_MODULE_ALIAS_ROW_AMBIGUOUS: u32 = 4294967294"), "")
if "4294967295" in resolver_without_named_sentinels or "4294967294" in resolver_without_named_sentinels or "depth>=128" in require_resolver:
    raise SystemExit("binding-capability resolver reintroduced an unnamed sentinel or recursion bound")
if compact("const BINDING_CAPABILITY_MAX_RESOLUTION_DEPTH: u32 = 128") not in compact(resolver_text):
    raise SystemExit("binding-capability resolver lost its named recursion limit")
if compact("const BINDING_MODULE_ALIAS_ROW_AMBIGUOUS: u32 = 4294967294") not in compact(resolver_text):
    raise SystemExit("binding-capability resolver lost its named ambiguous-alias sentinel")
if compact("declaration_id: DeclId{value: INVALID_DECL_ID_VALUE}") not in compact(function_section(resolver_text, "unknown_binding_capabilities")):
    raise SystemExit("unknown capability sentinel is no longer named")

positive_names = {
    "exact_flags_for_every_unary_input",
    "mutable_preserves_an_unborrowed_nonwritable_value",
    "lmut_always_adds_borrow_write_and_linear_flags",
    "ampersand_write_permission_tracks_inner_mutability",
}
negative_names = {
    "mutable_alone_creates_a_borrow",
    "immutable_ampersand_grants_writability",
    "ordinary_mutable_wrapper_is_linear_mutable",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/semantic/binding_capability_unary_policy.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer includes the production policy")

positive_shapes = {
    "exact_flags_for_every_unary_input": "flags.borrowed == (original_borrowed or is_ampersand or is_lmut) and flags.writable == (original_writable or is_lmut or (is_mutable and (original_borrowed or is_ampersand or is_lmut)) or (is_ampersand and inner_type_is_mutable)) and flags.linear_mutable == (original_linear_mutable or is_lmut)",
    "mutable_preserves_an_unborrowed_nonwritable_value": "return not flags.borrowed and flags.writable == writable",
    "lmut_always_adds_borrow_write_and_linear_flags": "return flags.borrowed and flags.writable and flags.linear_mutable",
    "ampersand_write_permission_tracks_inner_mutability": "return flags.borrowed and flags.writable == (writable or inner_type_is_mutable)",
}
negative_shapes = {
    "mutable_alone_creates_a_borrow": "return flags.borrowed",
    "immutable_ampersand_grants_writability": "return flags.writable",
    "ordinary_mutable_wrapper_is_linear_mutable": "return flags.linear_mutable",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(text, name)):
            raise SystemExit(f"{name} no longer states the intended unary flag claim")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("binding capability proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_include_closure([POSITIVE, NEGATIVE, SEMANTIC]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_REPLAY_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names) + 1
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "unary capability proof report changed across repeated runs"
assert positive_names | {"derive"} <= {
    row["name"] for row in positive["declaration_details"] if row.get("verified")
}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert negative["summary"]["declarations"] == len(negative_names) + 1
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(row["status"] == "disproved" and row["counterexample_found"]
           for row in negative["findings"])
assert "derive" in {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert product == require_current_product(BIN, PROVER)
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "binding capability proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "borrow, writability, and linear-mutable flags propagated through unary binding expressions",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
