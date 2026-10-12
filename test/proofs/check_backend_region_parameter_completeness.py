"""Source-bind and strictly replay the region-parameter witness-index proof."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SCAN = ROOT / "src/backend/codegen_region_parameter_scan.elisa"
SCAN_SPEC = HERE / "backend_region_parameter_scan_spec.elisa"
REGIONS = ROOT / "src/backend/codegen_abi_regions.elisa"
ABI_FACTS = ROOT / "src/backend/codegen_abi_facts.elisa"
POSITIVE = HERE / "backend_region_parameter_completeness.elisa"
NEGATIVE = HERE / "backend_region_parameter_completeness_rejected.elisa"
POSITIVE_NAMES = {
    "a_matching_witness_bounds_the_first_result",
    "the_returned_index_satisfies_the_complete_scan_contract",
}
NEGATIVE_NAMES = {"a_missing_region_parameter_line_is_present"}

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")


def strip_elisa_line_comment(line: str) -> str:
    """Remove a # comment without treating a # inside a quoted literal as comment syntax."""
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ("\\\"", "'"):
            quote = char
        elif char == "#":
            return line[:index]
    return line


def normalize_code_line(code: str) -> str:
    """Collapse insignificant whitespace while preserving quoted literal bytes and token gaps."""
    output = []
    quote = None
    escaped = False
    pending_space = False
    for char in code.strip():
        if quote is not None:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ("\\\"", "'"):
            if pending_space and output:
                output.append(" ")
            pending_space = False
            quote = char
            output.append(char)
        elif char.isspace():
            pending_space = True
        else:
            if pending_space and output:
                output.append(" ")
            pending_space = False
            output.append(char)
    return "".join(output)


def compact_code(text: str) -> tuple[str, ...]:
    """Normalize source lines while preserving token boundaries and relative indentation."""
    code_lines = []
    for line in text.splitlines():
        uncommented = strip_elisa_line_comment(line)
        if uncommented.strip():
            expanded = uncommented.expandtabs(4)
            indent = len(expanded) - len(expanded.lstrip())
            code_lines.append((indent, normalize_code_line(expanded.lstrip())))
    if not code_lines:
        return ()
    base_indent = min(indent for indent, _ in code_lines)
    return tuple((" " * (indent - base_indent)) + code for indent, code in code_lines)


def include_targets(text: str) -> list[str]:
    """Return only actual, line-level Elisa include directives, excluding comments."""
    targets = []
    for line in text.splitlines():
        directive = strip_elisa_line_comment(line).strip()
        match = re.fullmatch(r'include\s+"([^"\n]+)"', directive)
        if match:
            targets.append(match.group(1))
    return targets


if compact_code("return index") == compact_code("returnindex"):
    raise SystemExit("source normalizer collapses a token boundary")
if compact_code("if test:\n    return 1\nreturn 2") == compact_code("if test:\nreturn 1\nreturn 2"):
    raise SystemExit("source normalizer discards indentation-sensitive structure")
if include_targets('# include "./codegen_region_parameter_scan.elisa"\ninclude "./codegen_abi_regions.elisa" # actual') != ["./codegen_abi_regions.elisa"]:
    raise SystemExit("include parser accepts a comment as an active directive")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


scan_source = SCAN.read_text()
expected_scan = """
def first_matching_index(lines: darray[u32], target: u32) -> usize:
    ensure result <= lines.count
    ensure result < lines.count implies lines[result] == target
    index: mutable usize = 0
    while index < lines.count |index, lines, target|:
        decreases lines.count - index
        invariant index <= lines.count
        invariant forall prior in 0..<index: lines[prior] != target
        return index if lines[index] == target
        index <- index + 1
    return index
"""
if compact_code(function_section(scan_source, "first_matching_index")) != compact_code(expected_scan):
    raise SystemExit("production region-parameter witness scan changed without updating its source-bound proof")

spec_source = SCAN_SPEC.read_text()
expected_spec = """
def first_matching_index(lines: darray[u32], target: u32) -> usize:
    ensure result <= lines.count
    ensure result < lines.count implies lines[result] == target
    ensure result < lines.count implies (forall prior in 0..<result: lines[prior] != target)
    ensure result == lines.count implies (forall candidate in 0..<lines.count: lines[candidate] != target)
    index: mutable usize = 0
    while index < lines.count |index, lines, target|:
        decreases lines.count - index
        invariant index <= lines.count
        invariant forall prior in 0..<index: lines[prior] != target
        return index if lines[index] == target
        index <- index + 1
    return index
"""
if compact_code(function_section(spec_source, "first_matching_index")) != compact_code(expected_spec):
    raise SystemExit("proof-only region scan contract/model changed without updating the proof gate")

def operational_shape(function: str) -> str:
    code = "\n".join(line for line in function.splitlines() if not line.lstrip().startswith("ensure "))
    return compact_code(code)

if operational_shape(function_section(scan_source, "first_matching_index")) != \
        operational_shape(function_section(spec_source, "first_matching_index")):
    raise SystemExit("proof-only scan loop no longer exactly matches the production executable loop")

region_source = REGIONS.read_text()
expected_wrapper = """
def line_has_region_parameter(line: u32, structs: StructTable&) -> bool:
    return BackendRegionParameterScan::first_matching_index(structs.regions.region_param_lines, line) < structs.regions.region_param_lines.count
"""
if compact_code(function_section(region_source, "line_has_region_parameter")) != compact_code(expected_wrapper):
    raise SystemExit("ABI region-parameter lookup no longer derives membership from the verified witness index")

signature = compact_code(function_section(region_source, "signature_arena_count"))
expected_signature = """
def signature_arena_count(params: darray[ParamDecl]&, return_value_type: ValueType, body: darray[Stmt], line: u32, structs: mutable StructTable&) -> usize can[Abort.Panic, Memory.Allocate, Unsafe.PointerCast]:
    can Abort.Panic, Memory.Allocate, Unsafe.PointerCast:
        arena_managed: bool = params_manage_arena(params, structs)
        count: mutable usize = 1 if value_type_returns_caller_region(return_value_type, structs) and not arena_managed else 0
        flags: mutable darray[bool] = []
        region_flags_for_function(params, body, line, structs, flags)
        for parameter_index in 0..<flags.count |flags, count|:
            count <- count + 1.usize() if flags[parameter_index]
        count <- count + 1.usize() if line_has_region_parameter(line, structs)
        return count
"""
if signature != compact_code(expected_signature):
    raise SystemExit("signature arena count no longer adds the explicit-region slot in the source-bound count path")

abi_includes = include_targets(ABI_FACTS.read_text())
scan_include = "./codegen_region_parameter_scan.elisa"
region_include = "./codegen_abi_regions.elisa"
if abi_includes.count(scan_include) != 1 or abi_includes.count(region_include) != 1 or \
        abi_includes.index(scan_include) > abi_includes.index(region_include):
    raise SystemExit("backend must include the verified region scan before the ABI region policy")


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


for path, expected in ((POSITIVE, POSITIVE_NAMES), (NEGATIVE, NEGATIVE_NAMES)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "./backend_region_parameter_scan_spec.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} must include the proof-only source-bound witness scan")

positive_shape = """
def a_matching_witness_bounds_the_first_result(lines: darray[u32], target: u32, witness_index: usize) -> bool:
    requires witness_index < lines.count
    requires lines[witness_index] == target
    ensure result == true
    found_index: usize = BackendRegionParameterScanSpec::first_matching_index(lines, target)
    return found_index < lines.count and found_index <= witness_index
"""
if compact_code(function_section(POSITIVE.read_text(), "a_matching_witness_bounds_the_first_result")) != compact_code(positive_shape):
    raise SystemExit("positive lemma no longer proves the returned match is no later than any arbitrary matching witness")

complete_contract_shape = """
def the_returned_index_satisfies_the_complete_scan_contract(lines: darray[u32], target: u32) -> bool:
    ensure result == true
    found_index: usize = BackendRegionParameterScanSpec::first_matching_index(lines, target)
    return (
        found_index <= lines.count
        and (found_index < lines.count implies lines[found_index] == target)
        and (found_index < lines.count implies (forall prior in 0..<found_index: lines[prior] != target))
        and (found_index == lines.count implies (forall candidate in 0..<lines.count: lines[candidate] != target))
    )
"""
if compact_code(function_section(POSITIVE.read_text(), "the_returned_index_satisfies_the_complete_scan_contract")) != compact_code(complete_contract_shape):
    raise SystemExit("positive lemma no longer consumes the scan's complete first-match/sentinel contract")

negative_shape = """
def a_missing_region_parameter_line_is_present() -> bool:
    ensure result == true
    return BackendRegionParameterScanSpec::first_matching_index([9, 16, 27], 10) < 3
"""
if compact_code(function_section(NEGATIVE.read_text(), "a_missing_region_parameter_line_is_present")) != compact_code(negative_shape):
    raise SystemExit("negative control no longer asserts a false result for a concrete absent line")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("region-parameter witness proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SCAN, REGIONS, ABI_FACTS,
    POSITIVE, NEGATIVE, SCAN_SPEC, *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES) + 1
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == replay(POSITIVE)[1], "region-parameter proof report changed across identical runs"
positive_verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_verified == POSITIVE_NAMES | {"first_matching_index"}

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(NEGATIVE_NAMES) + 1
assert negative["summary"]["proven"] + len(NEGATIVE_NAMES) == negative["summary"]["obligations"]
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "a_missing_region_parameter_line_is_present"),
]
assert "first_matching_index" in {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "region-parameter first-match proof model with exact production-loop binding; quantified ensures remain proof-only",
    "positive_obligations": positive["summary"]["proven"],
    "false_claim_rejected": [row["name"] for row in negative["findings"]],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
