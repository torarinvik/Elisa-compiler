"""Admit source-linked proofs of sealed permission alias-family names."""
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
HELPER = ROOT / "src/semantic/permission_reserved_names.elisa"
CALLER = ROOT / "src/semantic/check_permission_reserved.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "permission_reserved_names.elisa"
NEGATIVE = HERE / "permission_reserved_names_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

SEALED_FAMILIES = (
    "Segment", "Unsafe", "Memory", "Abort", "Sync", "Atomics", "Console", "Blocking", "Global",
)
POSITIVE_NAMES = {
    "sealed_alias_family_set_is_exact",
    "reserved_top_permission_declaration_is_exact",
    "abstract_effect_family_remains_aliasable",
    "only_the_permission_declaration_marker_reserves_any",
}
NEGATIVE_NAMES = {
    "io_is_a_sealed_alias_family",
    "global_is_not_sealed_for_aliases",
    "an_alias_marker_reserves_the_top_permission",
}


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_proof_expression(path: Path, name: str, expression: str) -> None:
    text = path.read_text()
    definition = re.search(
        rf"(?m)^def {re.escape(name)}\([^\n]*\n(.*?)(?=^def |\Z)",
        text,
        re.DOTALL,
    )
    if not definition or compact(expression) not in compact(definition.group(1)):
        raise SystemExit(f"{name} no longer states its source-linked permission-name law")


def function_body(text: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^        def {re.escape(name)}\(", text))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one production function named {name}")
    start = matches[0].start()
    next_function = re.search(r"(?m)^        def [A-Za-z_][A-Za-z0-9_]*\(", text[matches[0].end():])
    end = matches[0].end() + next_function.start() if next_function else len(text)
    return text[start:end]


helper_text = HELPER.read_text()
family_body = function_body(helper_text, "is_sealed_alias_family")
match = re.search(r"return match name:\s*(.*?)\n\s*_:\s*false", family_body, re.DOTALL)
if not match:
    raise SystemExit("production family classifier lost its false fallback")
found = tuple(re.findall(r'"([^"\\]+)"', match.group(1)))
if found != SEALED_FAMILIES:
    raise SystemExit("production sealed alias-family match differs from the exact ordered set")
reserved_body = function_body(helper_text, "is_reserved_top_permission_declaration")
if compact('return owner == "__permission_decl" and name == "any"') not in compact(reserved_body):
    raise SystemExit("production reserved top-permission classifier changed its exact marker/name rule")

caller_text = CALLER.read_text()
if "PermissionReservedNames::is_sealed_alias_family(alias_name)" not in caller_text:
    raise SystemExit("alias conflict check no longer uses the proved sealed-family classifier")
if "PermissionReservedNames::is_reserved_top_permission_declaration(annotation.owner, annotation.name)" not in caller_text:
    raise SystemExit("reserved permission check no longer uses the proved marker classifier")
semantic_text = SEMANTIC.read_text()
if not (
    semantic_text.index('include "./permission_reserved_names.elisa"')
    < semantic_text.index('include "./check_permission_reserved.elisa"')
):
    raise SystemExit("semantic facade must include the policy before its callers")

for path in (POSITIVE, NEGATIVE):
    proof_text = path.read_text()
    if 'include "../../src/semantic/permission_reserved_names.elisa"' not in proof_text:
        raise SystemExit(f"{path.name} no longer includes the production policy")
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("permission-name proof inventory changed")
for name, expression in {
    "sealed_alias_family_set_is_exact": 'return PermissionReservedNames::is_sealed_alias_family(name) == (when name: "Segment" | "Unsafe" | "Memory" | "Abort" | "Sync" | "Atomics" | "Console" | "Blocking" | "Global" -> true _ -> false)',
    "reserved_top_permission_declaration_is_exact": 'return PermissionReservedNames::is_reserved_top_permission_declaration(owner, name) == (owner == "__permission_decl" and name == "any")',
    "abstract_effect_family_remains_aliasable": 'return not PermissionReservedNames::is_sealed_alias_family("IO")',
    "only_the_permission_declaration_marker_reserves_any": 'return not PermissionReservedNames::is_reserved_top_permission_declaration("__permission_alias", "any")',
}.items():
    require_proof_expression(POSITIVE, name, expression)
for name, expression in {
    "io_is_a_sealed_alias_family": 'return PermissionReservedNames::is_sealed_alias_family("IO")',
    "global_is_not_sealed_for_aliases": 'return not PermissionReservedNames::is_sealed_alias_family("Global")',
    "an_alias_marker_reserves_the_top_permission": 'return PermissionReservedNames::is_reserved_top_permission_declaration("__permission_alias", "any")',
}.items():
    require_proof_expression(NEGATIVE, name, expression)

source_files = source_include_closure([POSITIVE, NEGATIVE, SEMANTIC, CALLER])
try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("permission-name proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    HELPER, CALLER, SEMANTIC, POSITIVE, NEGATIVE, *source_files,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == replay(POSITIVE)[1], "permission-name proof changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "the exact sealed permission-alias family set and reserved top permission declaration marker",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
