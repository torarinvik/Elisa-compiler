"""Admit the exported-global C-name theorem against the production header path."""
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
HEADER = ROOT / "src/backend/c_header.elisa"
MODEL = ROOT / "src/backend/c_header_export_alias.elisa"
POSITIVE = HERE / "c_header_export_alias.elisa"
NEGATIVE = HERE / "c_header_export_alias_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    lines = source[start:end].splitlines()
    while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith(("#", "@"))):
        lines.pop()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


expected_model = compact("""def public_name(owner: sview, detail_name: sview) -> sview:
            ensure result == (detail_name if detail_name != "" else owner)
            return detail_name if detail_name != "" else owner""")
if compact(function_section(MODEL.read_text(), "public_name")) != expected_model:
    raise SystemExit("public-name model no longer states its exact alias/fallback contract")
if 'include "./c_header_export_alias.elisa"' not in HEADER.read_text():
    raise SystemExit("C header generator no longer imports the proved public-name function")

expected_adapter = compact("""def header_export_alias(marker: Ast::EnumAnnotation) -> sview:
            ensure result == (marker.detail_name if marker.detail_name != "" else marker.owner)
            return CHeaderExportAlias::public_name(marker.owner, marker.detail_name)""")
if compact(function_section(HEADER.read_text(), "header_export_alias")) != expected_adapter:
    raise SystemExit("production header alias adapter no longer forwards the proved source fields")

expected_global_emitter = compact("""def header_exported_globals(file: Ast::File&, structs: mutable StructTable&, out: mutable darray[u8]&) -> bool can[Abort.Panic, Memory.Allocate, Unsafe.PointerCast]:
            can Abort.Panic, Memory.Allocate:
                for annotation in file.enum_annotations |file, structs, out|:
                    continue if annotation.name != "__export_global"
                    target: sview = annotation.owner
                    public_name: sview = header_export_alias(annotation)
                    global_type: ValueType = header_global_type(structs, target)
                    false return if global_type.kind == TypeKind.Unmodeled
                    header_push(out, "extern ")
                    global_source: sview = header_global_source_type(file, target)
                    if global_source != "" and header_c_name_for_source_type(global_source, out):
                        out.push(32)
                        header_push(out, public_name)
                        out.push(59)
                    else:
                        false return if not header_decl(file, global_type, public_name, structs, out)
                    alignment: u32 = struct_alignment(global_type, structs)
                    if alignment != 0:
                        _ = out.pop()
                        header_push(out, " __attribute__((aligned(")
                        header_push_int(out, alignment.i64())
                        header_push(out, ")));")
                    out.push(10)
                return true""")
if compact(function_section(HEADER.read_text(), "header_exported_globals")) != expected_global_emitter:
    raise SystemExit("C global declarations no longer emit only the proved selected public name")
if HEADER.read_text().count("header_export_alias(annotation)") != 1:
    raise SystemExit("exported-global emitter changed the alias selection call-site inventory")

positive_shapes = {
    "explicit_alias_takes_precedence": "def explicit_alias_takes_precedence() -> bool: ensure result == true return CHeaderExportAlias::public_name(\"internal_seed\", \"public_seed\") == \"public_seed\"",
    "empty_alias_preserves_target": "def empty_alias_preserves_target() -> bool: ensure result == true return CHeaderExportAlias::public_name(\"internal_seed\", \"\") == \"internal_seed\"",
    "distinct_alias_is_not_replaced_by_target": "def distinct_alias_is_not_replaced_by_target(owner: sview, detail_name: sview) -> bool: requires detail_name != \"\" requires detail_name != owner ensure result == true return CHeaderExportAlias::public_name(owner, detail_name) != owner",
    "public_name_matches_the_alias_or_fallback_equation": "def public_name_matches_the_alias_or_fallback_equation(owner: sview, detail_name: sview) -> bool: ensure result == true return CHeaderExportAlias::public_name(owner, detail_name) == (detail_name if detail_name != \"\" else owner)",
    "empty_alias_and_target_remain_empty": "def empty_alias_and_target_remain_empty() -> bool: ensure result == true return CHeaderExportAlias::public_name(\"\", \"\") == \"\"",
}
negative_shapes = {
    "explicit_alias_must_not_lose_to_target": "def explicit_alias_must_not_lose_to_target() -> bool: ensure result == true return CHeaderExportAlias::public_name(\"internal_seed\", \"public_seed\") == \"internal_seed\"",
    "empty_alias_must_not_replace_target": "def empty_alias_must_not_replace_target() -> bool: ensure result == true return CHeaderExportAlias::public_name(\"internal_seed\", \"\") == \"\"",
    "empty_alias_must_not_invent_a_different_public_name": "def empty_alias_must_not_invent_a_different_public_name() -> bool: ensure result == true return CHeaderExportAlias::public_name(\"internal_seed\", \"\") == \"public_seed\"",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    if declarations(path) != set(shapes):
        raise SystemExit(f"{path.name} theorem inventory changed")
    if 'include "../../src/backend/c_header_export_alias.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer imports the production alias function")
    for name, shape in shapes.items():
        if compact(function_section(path.read_text(), name)) != compact(shape):
            raise SystemExit(f"{name} no longer states the source-bound alias theorem")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("C header alias proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE, HEADER, MODEL,
    *source_include_closure([POSITIVE, NEGATIVE]),
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
assert positive == run(POSITIVE)[1], "C header alias proof report changed across repeated runs"
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert set(positive_shapes) | {"public_name"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert {(item["kind"], item["name"]) for item in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_shapes
}
assert all(item["status"] == "disproved" and item["counterexample_found"]
           for item in negative["findings"])
assert {"public_name"} <= {
    item["name"] for item in negative["declaration_details"] if item.get("verified")
}
assert require_current_product(BIN, PROVER) == product
if hashes_before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
    raise SystemExit("C header alias proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "C exported-global alias precedence and fallback",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_shapes),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
