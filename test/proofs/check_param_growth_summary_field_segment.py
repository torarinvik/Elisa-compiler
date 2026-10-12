"""Replay field-segment isolation proofs against ParamGrowthSummary memoization."""
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
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
HELPER = ROOT / "src/semantic/param_growth_summary.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "param_growth_summary_field_segment.elisa"
NEGATIVE = HERE / "param_growth_summary_field_segment_rejected.elisa"

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
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    text = compact(body)
    positions = [text.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} no longer follows the checked segment boundary")


def source_line(body: str, fragment: str, label: str) -> tuple[int, int]:
    expected = compact(fragment)
    matches = [(index, len(line) - len(line.lstrip()))
               for index, line in enumerate(body.splitlines())
               if compact(line.strip()) == expected]
    if len(matches) != 1:
        raise SystemExit(f"{label} no longer has one unambiguous source line")
    return matches[0]


def require_nested_under(body: str, guard: str, action: str, label: str) -> None:
    guard_index, guard_indent = source_line(body, guard, label)
    action_index, action_indent = source_line(body, action, label)
    if action_index <= guard_index or action_indent <= guard_indent:
        raise SystemExit(f"{label} moved outside its current-segment scan")


def require_same_scope_after(body: str, guard: str, action: str, label: str) -> None:
    guard_index, guard_indent = source_line(body, guard, label)
    action_index, action_indent = source_line(body, action, label)
    if action_index <= guard_index or action_indent != guard_indent:
        raise SystemExit(f"{label} is no longer appended after the complete segment scan")


helper_text = HELPER.read_text()
semantic_text = SEMANTIC.read_text()
if 'include "./param_growth_summary.elisa"' not in semantic_text:
    raise SystemExit("semantic pass no longer includes ParamGrowthSummary")

push_source = function_section(helper_text, "pgs_push_lookup_field")
push_fragments = (
    "existing: mutable usize = first_field",
    "while existing < prior.lookup_fields.count",
    "return if prior.lookup_fields[existing] == field",
    "existing <- existing + 1",
    "prior.lookup_fields <- prior.lookup_fields.push(field)",
)
require_ordered(push_source, push_fragments, "field-segment deduplicator")
require_nested_under(push_source,
                     "while existing < prior.lookup_fields.count |existing, field, prior|:",
                     "return if prior.lookup_fields[existing] == field",
                     "duplicate-field check")
require_nested_under(push_source,
                     "while existing < prior.lookup_fields.count |existing, field, prior|:",
                     "existing <- existing + 1",
                     "field-segment scan step")
require_same_scope_after(push_source,
                         "while existing < prior.lookup_fields.count |existing, field, prior|:",
                         "prior.lookup_fields <- prior.lookup_fields.push(field)",
                         "new field append")

lookup_source = function_section(helper_text, "pgs_callee_fields")
lookup_fragments = (
    "first_field: usize = prior.lookup_fields.count",
    "triple: mutable u32 = pgs_head(prior, key)",
    "if prior.rows[row] == callee and prior.rows[row + 1] == tag:",
    "pgs_push_lookup_field(prior.rows[row + 2], first_field, prior)",
    "field_count: usize = prior.lookup_fields.count - first_field",
    "prior.lookup_field_starts <- prior.lookup_field_starts.push(first_field)",
    "prior.lookup_field_counts <- prior.lookup_field_counts.push(field_count)",
)
require_ordered(lookup_source, lookup_fragments, "ParamGrowthSummary result-segment construction")
require_nested_under(lookup_source,
                     "if prior.rows[row] == callee and prior.rows[row + 1] == tag:",
                     "pgs_push_lookup_field(prior.rows[row + 2], first_field, prior)",
                     "key-scoped field collection")

positive_names = {
    "pgs_should_append_current_field",
    "pgs_current_segment_duplicate_is_suppressed",
    "pgs_older_segment_match_does_not_suppress_current_field",
    "pgs_current_segment_match_suppresses_after_older_match",
}
positive_text = POSITIVE.read_text()
if not positive_names <= set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text)):
    raise SystemExit("field-segment proof is missing a required theorem")
expected_predicate = compact("""def pgs_should_append_current_field(found_in_current_segment: bool) -> bool:
    ensure result == not found_in_current_segment
    return not found_in_current_segment""")
if compact(function_section(positive_text, "pgs_should_append_current_field")) != expected_predicate:
    raise SystemExit("proof model no longer expresses segment-local duplicate detection")
if 'include "./param_growth_summary_field_segment.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("false field-segment control no longer imports the proved predicate")
if "def pgs_older_segment_match_suppresses_current_field(" not in NEGATIVE.read_text():
    raise SystemExit("false cross-segment suppression control is missing")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("field-segment proof requires a strict proof build")

inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, Path(__file__), HELPER, SEMANTIC, POSITIVE, NEGATIVE]
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
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names <= verified
assert positive == run(POSITIVE)[1], "field-segment proof changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "pgs_older_segment_match_suppresses_current_field"),
]
assert negative == run(NEGATIVE)[1], "negative field-segment control changed across repeated runs"

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "field deduplication is local to each memoized key segment",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claim_rejected": negative["findings"][0]["name"],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
