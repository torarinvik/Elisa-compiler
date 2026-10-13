"""Replay source-bound project include scanner span proofs."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
HERE = Path(__file__).resolve().parent
POSITIVE = HERE / "project_include_span_bounds.elisa"
NEGATIVE = HERE / "project_include_span_bounds_rejected.elisa"
SOURCE = ROOT / "src/driver/project_sources.elisa"

POSITIVE_NAMES = {
    "caller_line_slice_is_inside_file",
    "parsed_include_payload_is_inside_line",
    "include_payload_does_not_include_its_opening_quote",
    "project_source_scan_uses_a_synthetic_newline_at_eof",
}
NEGATIVE_NAMES = {
    "a_quote_at_the_line_limit_is_strictly_inside",
    "a_parsed_include_payload_can_overrun_the_file",
    "the_eof_scan_position_can_index_the_contents",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def source_errors(source_text: str) -> list[str]:
    errors = []
    try:
        scanner = compact(function_section(source_text, "include_directive_span"))
        discovery = compact(function_section(source_text, "discover_sources"))
    except SystemExit as error:
        return [str(error)]

    scanner_steps = (
        "cursor:mutableusize=start",
        "whilecursor<limit|cursor,line|:",
        "falsereturnifcursor+7.usize()>limit",
        "forindexin0..<7|line,cursor,keyword|:",
        "falsereturnifcursor>=limitorline[cursor]!=34",
        "cursor<-cursor+1.usize()out_start<-cursor",
    )
    scanner_positions = [scanner.find(fragment) for fragment in scanner_steps]
    if any(position < 0 for position in scanner_positions) or scanner_positions != sorted(scanner_positions):
        errors.append("include directive parser no longer bounds the keyword and opening-quote reads")

    payload_scan_at = scanner.find("out_start<-cursor")
    payload_scan = scanner[payload_scan_at:] if payload_scan_at >= 0 else ""
    payload_steps = (
        "whilecursor<limit|cursor,line|:",
        "breakifline[cursor]==34",
        "falsereturnifcursor>=limitorline[cursor]!=34",
        "out_length<-cursor-out_start",
    )
    payload_positions = [payload_scan.find(fragment) for fragment in payload_steps]
    if any(position < 0 for position in payload_positions) or payload_positions != sorted(payload_positions):
        errors.append("successful include parsing no longer proves the closing quote is before limit and records the bounded payload span")
    if 'falsereturnifline[cursor]!=32andline[cursor]!=9andline[cursor]!=13' not in scanner:
        errors.append("include directive parser no longer rejects non-whitespace bytes after its closing quote")

    caller_steps = (
        "whileposition<=contents.count|position,line_start,graph,files,contents,directory,include_dirs|:",
        "at_end:bool=position==contents.count",
        "byte:u8=10ifat_endelsecontents[position]",
        "ifbyte==10:",
        "ifinclude_directive_span(contents,line_start,position,&include_start,&include_length):",
        "bytes_extend_span(&requested,contents,include_start,include_length)",
    )
    caller_positions = [discovery.find(fragment) for fragment in caller_steps]
    if any(position < 0 for position in caller_positions) or caller_positions != sorted(caller_positions):
        errors.append("include payload spans are no longer consumed only after the bounded per-line scan")
    if "line_start:mutableusize=0.usize()" not in discovery or "line_start<-position+1.usize()" not in discovery:
        errors.append("source scanner no longer advances line slices from the previous line boundary")
    return errors


def validate_model() -> None:
    positive = POSITIVE.read_text()
    negative = NEGATIVE.read_text()
    for name, requires, returned in (
        ("caller_line_slice_is_inside_file", ("requiresline_start<=line_limitandline_limit<=contents_length",), "returnline_limit-line_start<=contents_length-line_start"),
        ("parsed_include_payload_is_inside_line", (
            "requiresline_limit<=contents_length", "requiresline_start<=payload_startandpayload_start<=closing_quote",
            "requiresclosing_quote<line_limit", "requirespayload_length==closing_quote-payload_start",
        ), "returnpayload_start<=contents_lengthandpayload_length<=contents_length-payload_start"),
        ("include_payload_does_not_include_its_opening_quote", (
            "requiresopening_quote<18446744073709551615.u64()", "requirespayload_start==opening_quote+1.u64()",
        ), "returnpayload_start>opening_quote"),
        ("project_source_scan_uses_a_synthetic_newline_at_eof", ("requiresposition<=contents_length",),
         "returnposition==contents_lengthorposition<contents_length"),
    ):
        body = compact(function_section(positive, name))
        if not all(fragment in body for fragment in requires) or "ensureresult==true" not in body or returned not in body:
            raise SystemExit(f"project include span proof {name} no longer matches its arithmetic contract")

    if declarations(POSITIVE) != POSITIVE_NAMES:
        raise SystemExit("project include span positive proof inventory changed")
    if declarations(NEGATIVE) != NEGATIVE_NAMES or 'include "./project_include_span_bounds.elisa"' not in negative:
        raise SystemExit("project include span false-claim inventory changed")
    for name, expression in (
        ("a_quote_at_the_line_limit_is_strictly_inside", 'returnclosing_quote<line_limit'),
        ("a_parsed_include_payload_can_overrun_the_file", "returnpayload_length>contents_length-payload_start"),
        ("the_eof_scan_position_can_index_the_contents", "returnposition<contents_length"),
    ):
        body = compact(function_section(negative, name))
        if "ensureresult==true" not in body or expression not in body:
            raise SystemExit(f"project include span false claim {name} no longer contradicts the bounds contract")


text = SOURCE.read_text()
errors = source_errors(text)
if errors:
    raise SystemExit("\n".join(errors))
validate_model()

# Mutation controls cover the two boundary reads and the caller's inclusive EOF sentinel.
mutated_span = text.replace("out_length <- cursor - out_start", "out_length <- cursor + out_start", 1)
if mutated_span == text or not source_errors(mutated_span):
    raise SystemExit("source gate failed to reject an invalid include payload span length")
mutated_eof = text.replace("while position <= contents.count", "while position >= contents.count", 1)
if mutated_eof == text or not source_errors(mutated_eof):
    raise SystemExit("source gate failed to reject an unsafe source-scan EOF loop guard")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project include span proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), POSITIVE, NEGATIVE, SOURCE,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert positive == run(POSITIVE)[1], "project include span proof report changed across repeated runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"]: row["kind"] for row in negative["findings"]} == {
    name: "ensure-unproven" for name in NEGATIVE_NAMES
}
assert negative["summary"]["unproven"] == len(NEGATIVE_NAMES)
assert negative == run(NEGATIVE)[1], "project include false-claim report changed across repeated runs"
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "project include proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "quoted include path span bounds and source scanner EOF selection",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
