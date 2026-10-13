"""Admit the exact parser machine-transition marker prefix policy."""
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
MARKER = ROOT / "src/parser/parser_machine_marker.elisa"
PARSER_MACHINE = ROOT / "src/parser/parser_stmt_machine.elisa"
LOWERING = ROOT / "src/parser/parser_machine_arm_lowering.elisa"
LAWS = ROOT / "src/parser/parser_machine_laws.elisa"
PARSER = ROOT / "src/parser/parser.elisa"
POSITIVE = HERE / "parser_machine_marker_prefix.elisa"
NEGATIVE = HERE / "parser_machine_marker_prefix_rejected.elisa"
PREFIX = "marker.len >= 3 and marker[0] == 35 and marker[1] == 45 and marker[2] == 62"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    generic = r"(?:\[[^\]\n]*\])?"
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}{generic}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(rf"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*{generic}\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


marker_text = MARKER.read_text()
helper = compact(function_section(marker_text, "has_prefix"))
if compact(f"ensure result == ({PREFIX})") not in helper:
    raise SystemExit("machine marker helper no longer contracts the exact three-byte prefix")
if compact(f"return {PREFIX}") not in helper:
    raise SystemExit("machine marker helper body no longer implements its exact prefix contract")
matcher = compact(function_section(marker_text, "matches"))
match_steps = (
    "false return if not has_prefix(marker)",
    "false return if marker.len != target.len + 3",
    "for index in 0..<target.len:",
    "return false if marker[index + 3] != target[index]",
    "return true",
)
match_positions = [matcher.find(compact(step)) for step in match_steps]
if any(position < 0 for position in match_positions) or match_positions != sorted(match_positions):
    raise SystemExit("production marker matcher no longer checks prefix, exact length, and every payload byte in order")

parser_machine_text = PARSER_MACHINE.read_text()
if 'include "./parser_machine_marker.elisa"' not in parser_machine_text:
    raise SystemExit("machine parser no longer imports the proved transition-marker policy")
if compact("return ParserMachineMarker::has_prefix(marker)") not in compact(function_section(parser_machine_text, "machine_transition_marker_prefix")):
    raise SystemExit("machine parser prefix wrapper no longer delegates to the proved policy")
matches_wrapper = compact(function_section(parser_machine_text, "machine_transition_marker_matches"))
if "returnParserMachineMarker::matches(marker,target)" not in matches_wrapper:
    raise SystemExit("machine parser matcher wrapper no longer delegates to the proved exact matcher")
if compact("include \"./parser_stmt_machine.elisa\"") not in compact(PARSER.read_text()):
    raise SystemExit("parser facade no longer includes the machine-transition source")

generator = compact(function_section(parser_machine_text, "machine_transition_marker"))
generator_steps = (
    "bytes: mutable darray[u8] = [35, 45, 62]",
    "for index in 0..<target.len |bytes|:",
    "bytes.push(target[index])",
    "return NameStore::append(&parser.machine_name_store, bytes, parser.name_store_chunk())",
)
generator_positions = [generator.find(compact(step)) for step in generator_steps]
if any(position < 0 for position in generator_positions) or generator_positions != sorted(generator_positions):
    raise SystemExit("machine transition marker no longer emits the proved prefix before its target bytes")

lowering = compact(function_section(LOWERING.read_text(), "lower_machine_arm_sequence"))
if "machine_transition_marker_prefix(label)" not in lowering or "machine_transition_marker_matches(label,state.name)" not in lowering:
    raise SystemExit("machine lowering no longer uses the proved marker prefix and payload matcher")
law = compact(function_section(LAWS.read_text(), "machine_arm_stmt_contains_transition_marker"))
if "machine_transition_marker_prefix(label)" not in law:
    raise SystemExit("machine arm-law validation no longer uses the proved marker prefix")

positive_names = {
    "production_machine_marker_prefix_is_exact",
    "bare_transition_marker_has_the_prefix",
    "payload_transition_marker_has_the_prefix",
    "short_transition_marker_lacks_the_prefix",
    "wrong_transition_marker_lacks_the_prefix",
    "bare_transition_marker_matches_empty_target",
    "one_byte_transition_marker_matches_target",
    "multi_byte_transition_marker_matches_exact_target",
    "different_payload_is_rejected",
    "trailing_marker_bytes_are_rejected",
    "missing_prefix_is_rejected_by_matcher",
}
negative_names = {
    "ordinary_text_is_a_transition_marker",
    "incomplete_transition_prefix_is_accepted",
    "different_transition_payload_is_accepted",
    "trailing_transition_payload_is_accepted",
}
positive_shapes = {
    "production_machine_marker_prefix_is_exact": f"ensure result == ({PREFIX}) return ParserMachineMarker::has_prefix(marker)",
    "bare_transition_marker_has_the_prefix": 'ensure result == true return ParserMachineMarker::has_prefix("#->")',
    "payload_transition_marker_has_the_prefix": 'ensure result == true return ParserMachineMarker::has_prefix("#->NextState")',
    "short_transition_marker_lacks_the_prefix": 'ensure result == true return not ParserMachineMarker::has_prefix("#-")',
    "wrong_transition_marker_lacks_the_prefix": 'ensure result == true return not ParserMachineMarker::has_prefix("##->NextState")',
    "bare_transition_marker_matches_empty_target": 'ensure result == true return ParserMachineMarker::matches("#->", "")',
    "one_byte_transition_marker_matches_target": 'ensure result == true return ParserMachineMarker::matches("#->x", "x")',
    "multi_byte_transition_marker_matches_exact_target": 'ensure result == true return ParserMachineMarker::matches("#->NextState", "NextState")',
    "different_payload_is_rejected": 'ensure result == true return not ParserMachineMarker::matches("#->NextState", "OtherState")',
    "trailing_marker_bytes_are_rejected": 'ensure result == true return not ParserMachineMarker::matches("#->NextState!", "NextState")',
    "missing_prefix_is_rejected_by_matcher": 'ensure result == true return not ParserMachineMarker::matches("##->NextState", "NextState")',
}
negative_shapes = {
    "ordinary_text_is_a_transition_marker": 'ensure result == true return ParserMachineMarker::has_prefix("NextState")',
    "incomplete_transition_prefix_is_accepted": 'ensure result == true return ParserMachineMarker::has_prefix("#-")',
    "different_transition_payload_is_accepted": 'ensure result == true return ParserMachineMarker::matches("#->NextState", "OtherState")',
    "trailing_transition_payload_is_accepted": 'ensure result == true return ParserMachineMarker::matches("#->NextState!", "NextState")',
}
for path, expected, shapes in (
    (POSITIVE, positive_names, positive_shapes),
    (NEGATIVE, negative_names, negative_shapes),
):
    proof_text = path.read_text()
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/parser/parser_machine_marker.elisa"' not in proof_text:
        raise SystemExit(f"{path.name} no longer includes the production marker policy")
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer states the intended marker-prefix property")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("parser machine marker proof requires a strict proof build")
compiler = manifest["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    MARKER, PARSER_MACHINE, LOWERING, LAWS, PARSER, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
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


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "machine marker proof report changed across identical runs"
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names | {"has_prefix"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {(item["kind"], item["name"]) for item in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(item["status"] == "disproved" and item["counterexample_found"]
           for item in negative["findings"])
assert "has_prefix" in {item["name"] for item in negative["declaration_details"] if item.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest
print(json.dumps({
    "admitted": True,
    "scope": "exact three-byte prefix recognition used by parser machine transition lowering and validation",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
