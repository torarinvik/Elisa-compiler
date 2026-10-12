"""Replay collision-rejection proofs against both ParamGrowthSummary lookup paths."""
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
POSITIVE = HERE / "param_growth_summary_key_identity.elisa"
NEGATIVE = HERE / "param_growth_summary_key_identity_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    text = compact(body)
    positions = [text.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} changed the checked collision-validation order")


def source_line(body: str, fragment: str, label: str) -> tuple[int, int]:
    expected = compact(fragment)
    matches = [(index, len(line) - len(line.lstrip()), line)
               for index, line in enumerate(body.splitlines())
               if compact(line.strip()) == expected]
    if len(matches) != 1:
        raise SystemExit(f"{label} no longer has one unambiguous guard/update line")
    index, indent, _ = matches[0]
    return index, indent


def require_nested_under(body: str, guard: str, action: str, label: str) -> None:
    guard_index, guard_indent = source_line(body, guard, label)
    action_index, action_indent = source_line(body, action, label)
    if action_index <= guard_index or action_indent <= guard_indent:
        raise SystemExit(f"{label} moved outside its exact-key guard")


def require_same_scope_after(body: str, guard: str, action: str, label: str) -> None:
    guard_index, guard_indent = source_line(body, guard, label)
    action_index, action_indent = source_line(body, action, label)
    if action_index <= guard_index or action_indent != guard_indent:
        raise SystemExit(f"{label} no longer continues the collision chain after a key mismatch")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


helper_text = HELPER.read_text()
semantic_text = SEMANTIC.read_text()
if 'include "./param_growth_summary.elisa"' not in semantic_text:
    raise SystemExit("semantic pass no longer includes ParamGrowthSummary")

key_body = compact(function_section(helper_text, "pgs_key"))
if "return(name_hash(function)*SEMANTIC_HASH_PRIME)^name_hash(tag)" not in key_body:
    raise SystemExit("ParamGrowthSummary key hash formula changed")

cache_source = function_section(helper_text, "pgs_callee_fields")
cache_body = compact(cache_source)
cache_fragments = (
    'false return if tag == "" or callee == ""',
    "callee_hash:u64=name_hash(callee)",
    "key:u64=(callee_hash*SEMANTIC_HASH_PRIME)^name_hash(tag)",
    "cached:mutableu32=pgs_lookup_head(prior,key)",
    "whilecached!=SYMBOL_INDEX_ROW_NONE",
    "ifprior.lookup_callees[cache_row]==calleeandprior.lookup_tags[cache_row]==tag:",
    "returnprior.lookup_known[cache_row]",
    "cached<-prior.lookup_next[cache_row]",
    "triple:mutableu32=pgs_head(prior,key)",
    "ifprior.rows[row]==calleeandprior.rows[row+1]==tag:",
    "pgs_push_lookup_field(prior.rows[row+2],first_field,prior)",
    "triple<-prior.next[triple.usize()]",
)
require_ordered(cache_source, cache_fragments, "temporary ParamGrowthSummary lookup")
require_nested_under(cache_source,
                     "if prior.lookup_callees[cache_row] == callee and prior.lookup_tags[cache_row] == tag:",
                     "return prior.lookup_known[cache_row]",
                     "temporary cache hit")
require_same_scope_after(cache_source,
                         "if prior.lookup_callees[cache_row] == callee and prior.lookup_tags[cache_row] == tag:",
                         "cached <- prior.lookup_next[cache_row]",
                         "temporary cache collision")
require_nested_under(cache_source,
                     "if prior.rows[row] == callee and prior.rows[row + 1] == tag:",
                     "pgs_push_lookup_field(prior.rows[row + 2], first_field, prior)",
                     "temporary row field collection")
require_same_scope_after(cache_source,
                         "if prior.rows[row] == callee and prior.rows[row + 1] == tag:",
                         "triple <- prior.next[triple.usize()]",
                         "temporary row collision")

published_source = function_section(helper_text, "pgs_callee_fields_published")
published_body = compact(published_source)
published_fragments = (
    'false return if tag == "" or callee == ""',
    "triple:mutableu32=pgs_published_head(table,pgs_key(callee,tag))",
    "whiletriple!=SYMBOL_INDEX_ROW_NONE",
    "iftable.param_growth_rows[row]==calleeandtable.param_growth_rows[row+1]==tag:",
    "pgs_push(table.param_growth_rows[row+2],fields)",
    "triple<-table.param_growth_index_next[triple.usize()]",
)
require_ordered(published_source, published_fragments, "published ParamGrowthSummary lookup")
require_nested_under(published_source,
                     "if table.param_growth_rows[row] == callee and table.param_growth_rows[row + 1] == tag:",
                     "pgs_push(table.param_growth_rows[row + 2], fields)",
                     "published row field collection")
require_same_scope_after(published_source,
                         "if table.param_growth_rows[row] == callee and table.param_growth_rows[row + 1] == tag:",
                         "triple <- table.param_growth_index_next[triple.usize()]",
                         "published row collision")

positive_names = {
    "pgs_exact_pair_match",
    "pgs_hash_collision_on_callee_is_rejected",
    "pgs_hash_collision_on_tag_is_rejected",
    "pgs_matching_pair_is_accepted_from_its_bucket",
    "pgs_key_is_eligible",
    "pgs_empty_key_component_disables_lookup",
    "pgs_present_key_components_allow_lookup",
}
if not positive_names <= set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", POSITIVE.read_text())):
    raise SystemExit("ParamGrowthSummary key-identity proof is missing a required theorem")
positive_text = POSITIVE.read_text()
expected_matcher = compact("""def pgs_exact_pair_match(hash_bucket_matches: bool, callee_matches: bool, tag_matches: bool) -> bool:
    ensure result == (hash_bucket_matches and callee_matches and tag_matches)
    return hash_bucket_matches and callee_matches and tag_matches""")
if compact(function_section(positive_text, "pgs_exact_pair_match")) != expected_matcher:
    raise SystemExit("proof model no longer matches the production exact-pair cache predicate")
expected_eligibility = compact("""def pgs_key_is_eligible(callee_is_present: bool, tag_is_present: bool) -> bool:
    ensure result == (callee_is_present and tag_is_present)
    return callee_is_present and tag_is_present""")
if compact(function_section(positive_text, "pgs_key_is_eligible")) != expected_eligibility:
    raise SystemExit("proof model no longer matches the production nonempty-key guard")
if 'include "./param_growth_summary_key_identity.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer imports the proved exact-pair predicate")
if "def pgs_hash_alone_is_enough_for_cache_hit(" not in NEGATIVE.read_text():
    raise SystemExit("ParamGrowthSummary false collision control is missing")
if "def pgs_empty_callee_still_has_a_queryable_key(" not in NEGATIVE.read_text():
    raise SystemExit("ParamGrowthSummary empty-key false control is missing")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("ParamGrowthSummary key-identity proof requires a strict proof build")

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
assert positive == run(POSITIVE)[1], "key-identity proof changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "pgs_hash_alone_is_enough_for_cache_hit"),
    ("ensure-unproven", "pgs_empty_callee_still_has_a_queryable_key"),
]
assert negative == run(NEGATIVE)[1], "negative key-identity controls changed across repeated runs"

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "hash collisions and empty key components cannot alias ParamGrowthSummary lookups",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": [finding["name"] for finding in negative["findings"]],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
