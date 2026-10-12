"""Admit source-linked integer storage range contracts for const-enum members."""
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
SOURCE = ROOT / "src/semantic/check_const_enum_member_value.elisa"

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
    return source[start:end]


ranges = {
    # The proof syntax spells negative constants as subtraction because the current
    # prover leaves bare negative literals ambiguous in arithmetic goals.
    "u8": ("0", "255", "0", "255"),
    "u16": ("0", "65535", "0", "65535"),
    "u32": ("0", "4294967295", "0", "4294967295"),
    "i8": ("-128", "127", "(0 - 128)", "127"),
    "i16": ("-32768", "32767", "(0 - 32768)", "32767"),
    "i32": ("-2147483648", "2147483647", "(0 - 2147483648)", "2147483647"),
}
source_text = SOURCE.read_text()
source_function = function_section(source_text, "int_fits_storage")
compact_source_function = compact(source_function)
source_branches = re.findall(r'(?m)^\s*"([A-Za-z0-9]+)"\s*->\s*(.*?)\s*$', source_function)
expected_source_branches = {
    name: f"value >= {source_lower} and value <= {source_upper}"
    for name, (source_lower, source_upper, _, _) in ranges.items()
}
if len(source_branches) != len(expected_source_branches) or dict(source_branches) != expected_source_branches:
    raise SystemExit("production integer-storage cases or their range expressions changed")
positive_paths = {}
negative_paths = {}
positive_names = {}
negative_names = {}
for name, (_, _, lower, upper) in ranges.items():
    positive = HERE / f"const_enum_storage_range_{name}.elisa"
    negative = HERE / f"const_enum_storage_range_{name}_rejected.elisa"
    positive_paths[name], negative_paths[name] = positive, negative
    formula = compact(f"value >= {lower} and value <= {upper}")
    if f'"{name}"->{formula}' not in compact_source_function:
        # Signed source branches use unary negative literals; the proof models use
        # equivalent typed subtraction to avoid the prover's ambiguous-literal gate.
        source_lower, source_upper, _, _ = ranges[name]
        source_formula = f"value>={source_lower}andvalue<={source_upper}"
        if f'"{name}"->{source_formula}' not in compact_source_function:
            raise SystemExit(f"production int_fits_storage branch for {name} changed")
    proof_name = f"proof_const_enum_{name}_fits"
    proof_body = compact(function_section(positive.read_text(), proof_name))
    if f"ensureresult==({formula})" not in proof_body or f"return{formula}" not in proof_body:
        raise SystemExit(f"proof contract for {name} no longer mirrors its production storage range")
    proof_theorems = (
        (f"const_enum_{name}_accepts_in_range", compact(f"requires value >= {lower} and value <= {upper} ensure result == true return {proof_name}(value)")),
        (f"const_enum_{name}_rejects_below_range", compact(f"requires value < {lower} ensure result == true return not {proof_name}(value)")),
        (f"const_enum_{name}_rejects_above_range", compact(f"requires value > {upper} ensure result == true return not {proof_name}(value)")),
    )
    for theorem_name, theorem_shape in proof_theorems:
        if theorem_shape not in compact(function_section(positive.read_text(), theorem_name)):
            raise SystemExit(f"{theorem_name} no longer proves the intended range property")
    positive_names[name] = {
        proof_name,
        f"const_enum_{name}_accepts_in_range",
        f"const_enum_{name}_rejects_below_range",
        f"const_enum_{name}_rejects_above_range",
    }
    negative_names[name] = {
        f"false_const_enum_{name}_accepts_below",
        f"false_const_enum_{name}_accepts_above",
    }
    declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive.read_text()))
    if declarations != positive_names[name]:
        raise SystemExit(f"positive {name} proof declaration inventory changed")
    declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative.read_text()))
    if declarations != negative_names[name]:
        raise SystemExit(f"negative {name} proof declaration inventory changed")
    for theorem_name, op, bound in (
        (f"false_const_enum_{name}_accepts_below", "<", lower),
        (f"false_const_enum_{name}_accepts_above", ">", upper),
    ):
        expected_shape = compact(f"requires value {op} {bound} ensure result == true return {proof_name}(value)")
        if expected_shape not in compact(function_section(negative.read_text(), theorem_name)):
            raise SystemExit(f"{theorem_name} no longer challenges the proved boundary")

if compact(source_function).count("_->true") != 1:
    raise SystemExit("unmodeled storage types must continue to fail open without a diagnostic")
unmodeled = HERE / "const_enum_storage_range_unmodeled.elisa"
if set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", unmodeled.read_text())) != {
    "unmodeled_storage_type_is_accepted"
}:
    raise SystemExit("unmodeled-storage proof declaration inventory changed")
unmodeled_body = compact(function_section(unmodeled.read_text(), "unmodeled_storage_type_is_accepted"))
if "ensureresult==true" not in unmodeled_body or "returntrue" not in unmodeled_body:
    raise SystemExit("proof for the conservative unmodeled-storage branch changed")

check_function = compact(function_section(source_text, "check_const_enum_member_value"))
for fragment in (
    "ifis_const:",
    "Expr.IntLit(member_value,_):",
    "table.diagnostics<-table.diagnostics.push(Diagnostic{kind:DiagnosticKind.ConstEnumValueOutOfRange",
    "ifnotint_fits_storage(member_value,storage_name)",
    "Decl.Module(module_name,body,module_line):",
    "Decl.Scoped(scoped_body,scoped_line):",
):
    if fragment not in check_function:
        raise SystemExit("const-enum range check no longer applies to literal members across declaration scopes")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("const-enum storage proofs require a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, unmodeled,
    *positive_paths.values(), *negative_paths.values(),
    *source_include_closure([unmodeled, *positive_paths.values(), *negative_paths.values()]),
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


positive_reports = {}
for name, path in positive_paths.items():
    code, report = run(path)
    assert code == 0 and report["status"] == report["verification_state"] == "proved"
    assert report["summary"]["declarations"] == len(positive_names[name])
    assert report["summary"]["obligations"] == report["summary"]["proven"] == 8
    assert not report["findings"]
    assert report == run(path)[1], f"{name} proof report changed across identical runs"
    verified = {row["name"] for row in report["declaration_details"] if row.get("verified")}
    assert verified == positive_names[name]
    positive_reports[name] = report

code, unmodeled_report = run(unmodeled)
assert code == 0 and unmodeled_report["status"] == unmodeled_report["verification_state"] == "proved"
assert unmodeled_report["summary"]["declarations"] == 1
assert unmodeled_report["summary"]["obligations"] == unmodeled_report["summary"]["proven"] == 2
assert not unmodeled_report["findings"]

negative_reports = {}
for name, path in negative_paths.items():
    code, report = run(path)
    assert code == 1 and report["status"] == "failed"
    assert report["summary"]["declarations"] == len(positive_names[name]) + len(negative_names[name])
    assert report["summary"]["unproven"] == len(negative_names[name])
    assert {row["name"] for row in report["findings"]} == negative_names[name]
    assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
               for row in report["findings"])
    assert not negative_names[name] & {row["name"] for row in report["declaration_details"] if row.get("verified")}
    negative_reports[name] = report

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "const-enum integer storage acceptance and lower/upper rejection for six integer widths",
    "positive_obligations": sum(row["summary"]["proven"] for row in positive_reports.values()) + unmodeled_report["summary"]["proven"],
    "false_claims_refused": sorted(name for names in negative_names.values() for name in names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
