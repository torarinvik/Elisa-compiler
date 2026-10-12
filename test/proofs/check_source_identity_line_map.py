"""Admit the source-linked line-map offset proof with an exact strict product."""
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
SOURCE = ROOT / "src/driver/elisac_source_identity.elisa"
POSITIVE = HERE / "source_identity_line_map.elisa"
NEGATIVE = HERE / "source_identity_line_map_rejected.elisa"
U32_MAX = "4294967295"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def assert_source_model(source_text: str) -> None:
    lookup = compact(function_section(source_text, "path_for_line"))
    lookup_fragments = (
        "def path_for_line(flat_line:u32,attribution:Attribution&)->PathResult:",
        "returnmissifnotattribution.validorflat_line==0",
        "low:mutableusize=0",
        "high:mutableusize=attribution.entries.count",
        "middle:usize=low+(high-low)/2",
        "ifattribution.entries[middle].flat_line<=flat_line:",
        "low<-middle+1",
        "high<-middle",
        "returnmissiflow==0",
        "entry:AttributionEntry=attribution.entries[low-1]",
        "delta:u32=flat_line-entry.flat_line",
        f"returnmissifentry.original_line>{U32_MAX}-delta",
        "original_line:entry.original_line+delta",
    )
    positions = []
    cursor = 0
    for fragment in lookup_fragments:
        position = lookup.find(compact(fragment), cursor)
        positions.append(position)
        if position >= 0:
            cursor = position + len(compact(fragment))
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise ValueError("path_for_line no longer matches the proved upper-bound and guarded-addition structure")

    retain = compact(function_section(source_text, "retain_line_map"))
    parser_fragments = (
        "flat:mutableu32=0",
        "original:mutableu32=0",
        "returnifbyte<48orbyte>57ordigits>=10",
        "digit:u32=(byte-48).u32()",
        f"flat>({U32_MAX}-digit)/10",
        "flat==0",
        "flat<previous_flat",
        "returnifbyte<48orbyte>57ordigits>=10",
        "digit:u32=(byte-48).u32()",
        f"original>({U32_MAX}-digit)/10",
        "original==0",
        "attribution.entries.push(AttributionEntry{flat_line:flat,original_line:original,path_start:start,path_length:length})",
        "previous_flat<-flat",
    )
    positions = []
    cursor = 0
    for fragment in parser_fragments:
        position = retain.find(compact(fragment), cursor)
        positions.append(position)
        if position >= 0:
            cursor = position + len(compact(fragment))
    digit_guard = compact("return if byte < 48 or byte > 57 or digits >= 10")
    digit_conversion = compact("digit: u32 = (byte - 48).u32()")
    if (any(position < 0 for position in positions) or positions != sorted(positions) or
            retain.count(digit_guard) != 2 or retain.count(digit_conversion) != 2):
        raise ValueError("retained line-map entries must remain positive, u32-bounded, and nondecreasing before lookup")


source_text = SOURCE.read_text()
assert_source_model(source_text)

# Guard the source link against the off-by-one mutations most likely to make
# the arithmetic model cease to describe the implementation.
mutations = (
    source_text.replace(f"entry.original_line > {U32_MAX} - delta",
                        f"entry.original_line >= {U32_MAX} - delta", 1),
    source_text.replace("attribution.entries[middle].flat_line <= flat_line",
                        "attribution.entries[middle].flat_line < flat_line", 1),
    source_text.replace("flat < previous_flat", "flat <= previous_flat", 1),
)
for mutated in mutations:
    try:
        assert_source_model(mutated)
    except ValueError:
        continue
    raise SystemExit("line-map source mutation escaped the proof link")

positive_names = {
    "source_line_offset_fits",
    "accepted_source_line_cannot_overflow",
    "overflowing_source_line_is_rejected",
    "exact_u32_limit_is_accepted",
    "one_past_u32_limit_is_rejected",
    "selected_line_offset_stays_in_u32",
}
negative_names = {
    "overflowing_source_line_is_accepted",
    "exact_u32_limit_is_rejected",
    "a_line_after_the_selected_entry_has_a_negative_offset",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names:
    raise SystemExit("source identity line-map proof declaration inventory changed")

positive_shapes = {
    "source_line_offset_fits": "requires 0 <= selected_flat_line and selected_flat_line <= requested_flat_line and requested_flat_line <= SOURCE_LINE_U32_MAX and 0 <= original_line and original_line <= SOURCE_LINE_U32_MAX ensure result == (original_line <= SOURCE_LINE_U32_MAX - (requested_flat_line - selected_flat_line)) delta: i64 = requested_flat_line - selected_flat_line return original_line <= SOURCE_LINE_U32_MAX - delta",
    "accepted_source_line_cannot_overflow": "requires 0 <= selected_flat_line and selected_flat_line <= requested_flat_line and requested_flat_line <= SOURCE_LINE_U32_MAX and 0 <= original_line and original_line <= SOURCE_LINE_U32_MAX and original_line <= SOURCE_LINE_U32_MAX - (requested_flat_line - selected_flat_line) ensure result == true delta: i64 = requested_flat_line - selected_flat_line return source_line_offset_fits(selected_flat_line, requested_flat_line, original_line) and original_line + delta <= SOURCE_LINE_U32_MAX",
    "overflowing_source_line_is_rejected": "requires 0 <= selected_flat_line and selected_flat_line <= requested_flat_line and requested_flat_line <= SOURCE_LINE_U32_MAX and 0 <= original_line and original_line <= SOURCE_LINE_U32_MAX and original_line > SOURCE_LINE_U32_MAX - (requested_flat_line - selected_flat_line) ensure result == true delta: i64 = requested_flat_line - selected_flat_line return original_line > SOURCE_LINE_U32_MAX - delta",
    "exact_u32_limit_is_accepted": "ensure result == true delta: i64 = 11 - 10 return 4294967294 <= SOURCE_LINE_U32_MAX - delta and 4294967294 + delta == SOURCE_LINE_U32_MAX",
    "one_past_u32_limit_is_rejected": "ensure result == true delta: i64 = 11 - 10 return SOURCE_LINE_U32_MAX > SOURCE_LINE_U32_MAX - delta",
    "selected_line_offset_stays_in_u32": "requires 0 <= selected_flat_line and selected_flat_line <= requested_flat_line and requested_flat_line <= SOURCE_LINE_U32_MAX ensure result == true return 0 <= requested_flat_line - selected_flat_line and requested_flat_line - selected_flat_line <= SOURCE_LINE_U32_MAX",
}
positive_text = POSITIVE.read_text()
for name, expected in positive_shapes.items():
    actual = compact(function_section(positive_text, name))
    if compact(expected) not in actual:
        raise SystemExit(f"{name} no longer states its line-map arithmetic claim")

negative_shapes = {
    "overflowing_source_line_is_accepted": "requires 0 <= selected_flat_line and selected_flat_line <= requested_flat_line and requested_flat_line <= SOURCE_LINE_U32_MAX and 0 <= original_line and original_line <= SOURCE_LINE_U32_MAX and original_line > SOURCE_LINE_U32_MAX - (requested_flat_line - selected_flat_line) ensure result == true delta: i64 = requested_flat_line - selected_flat_line return original_line <= SOURCE_LINE_U32_MAX - delta",
    "exact_u32_limit_is_rejected": "ensure result == true delta: i64 = 11 - 10 return 4294967294 > SOURCE_LINE_U32_MAX - delta",
    "a_line_after_the_selected_entry_has_a_negative_offset": "requires 0 <= selected_flat_line and selected_flat_line <= requested_flat_line and requested_flat_line <= SOURCE_LINE_U32_MAX ensure result == true return requested_flat_line < selected_flat_line",
}
negative_text = NEGATIVE.read_text()
for name, expected in negative_shapes.items():
    if compact(expected) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges the line-map invariant")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("source identity line-map proofs require a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE,
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 13
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "line-map proof report changed across identical runs"
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "u32 line-map offset guard under the source-linked selected-entry ordering condition",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
