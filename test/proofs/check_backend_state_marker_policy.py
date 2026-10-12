"""Admit the exact reversible state-marker tag mapping used by codegen."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POLICY = ROOT / "src/backend/codegen_state_marker_policy.elisa"
FACADE = ROOT / "src/backend/codegen.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
VALUE_TYPE = ROOT / "src/backend/codegen_value_type.elisa"
ANNOTATION_SCOPE = ROOT / "src/backend/codegen_annotation_scope.elisa"
NAME_MANGLING = ROOT / "src/backend/codegen_name_mangling.elisa"
POSITIVE = HERE / "backend_state_marker_policy.elisa"
NEGATIVE = HERE / "backend_state_marker_policy_rejected.elisa"


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


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


policy_text = POLICY.read_text()
facade_text = FACADE.read_text()
env_text = ENV.read_text()
value_type_text = VALUE_TYPE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

tags = {
    "UNKNOWN": 0,
    "LOCAL": 1,
    "FROZEN": 2,
    "JOINABLE": 3,
    "PENDING": 4,
    "HELD": 5,
}
for name, value in tags.items():
    declaration = f"const BUILTIN_STATE_MARKER_{name}_TAG: u32 = {value}"
    if compact(declaration) not in compact(policy_text):
        raise SystemExit(f"policy lost named state-marker tag {name}")

name_rows = (
    ("Local", "LOCAL"),
    ("Frozen", "FROZEN"),
    ("Joinable", "JOINABLE"),
    ("Pending", "PENDING"),
    ("Held", "HELD"),
)
tag_patterns = " ".join(
    f'"{name}": BUILTIN_STATE_MARKER_{tag}_TAG'
    for name, tag in name_rows
)
expected_tag_for_name = (
    f"def tag_for_name(name: sview) -> u32: "
    "ensure result == (when name: "
    + " ".join(f'"{name}" -> BUILTIN_STATE_MARKER_{tag}_TAG' for name, tag in name_rows)
    + " _ -> BUILTIN_STATE_MARKER_UNKNOWN_TAG) "
    f"return match name: {tag_patterns} _: BUILTIN_STATE_MARKER_UNKNOWN_TAG"
)
if compact(function_section(policy_text, "tag_for_name")) != compact(expected_tag_for_name):
    raise SystemExit("name-to-tag policy no longer uses the exact closed match table")

tag_rows = tuple((tag, name) for name, tag in name_rows)
expected_name_for_tag = (
    "def name_for_tag(tag: u32) -> sview: "
    "ensure result == (match tag: "
    + " ".join(f"BUILTIN_STATE_MARKER_{tag}_TAG: \"{name}\"" for tag, name in tag_rows)
    + ' _: "unknown") '
    + "return match tag: "
    + " ".join(f'BUILTIN_STATE_MARKER_{tag}_TAG: "{name}"' for tag, name in tag_rows)
    + ' _: "unknown"'
)
if compact(function_section(policy_text, "name_for_tag")) != compact(expected_name_for_tag):
    raise SystemExit("tag-to-name policy no longer uses the exact closed match table")

expected_name_proof = (
    "def marker_name_to_tag_contract_is_exact(name: sview) -> bool: "
    "ensure result == true "
    "return BackendStateMarkerPolicy::tag_for_name(name) == (when name: "
    + " ".join(f'\"{name}\" -> BackendStateMarkerPolicy::BUILTIN_STATE_MARKER_{tag}_TAG' for name, tag in name_rows)
    + " _ -> BackendStateMarkerPolicy::BUILTIN_STATE_MARKER_UNKNOWN_TAG)"
)
expected_tag_proof = (
    "def marker_tag_to_name_contract_is_exact(tag: u32) -> bool: "
    "ensure result == true "
    "return BackendStateMarkerPolicy::name_for_tag(tag) == (match tag: "
    + " ".join(f'BackendStateMarkerPolicy::BUILTIN_STATE_MARKER_{tag}_TAG: \"{name}\"' for tag, name in tag_rows)
    + ' _: "unknown")'
)
if compact(function_section(positive_text, "marker_name_to_tag_contract_is_exact")) != compact(expected_name_proof):
    raise SystemExit("name-to-tag proof no longer checks the exact universal mapping equation")
if compact(function_section(positive_text, "marker_tag_to_name_contract_is_exact")) != compact(expected_tag_proof):
    raise SystemExit("tag-to-name proof no longer checks the exact universal mapping equation")

expected_type_wrapper = (
    "def builtin_state_marker_type(name: sview) -> ValueType: "
    "tag: u32 = BackendStateMarkerPolicy::tag_for_name(name) "
    "return ValueType{kind: TypeKind.Unmodeled, bits: tag}"
)
if compact(function_section(value_type_text, "builtin_state_marker_type")) != compact(expected_type_wrapper):
    raise SystemExit("backend ValueType no longer uses the proved marker tag policy")
expected_name_wrapper = (
    "def builtin_state_marker_name(tag: u32) -> sview: "
    "return BackendStateMarkerPolicy::name_for_tag(tag)"
)
if compact(function_section(value_type_text, "builtin_state_marker_name")) != compact(expected_name_wrapper):
    raise SystemExit("backend name mangling no longer uses the proved reverse marker policy")

policy_include = 'include "./codegen_state_marker_policy.elisa"'
env_include = 'include "./codegen_env.elisa"'
if policy_include not in facade_text or facade_text.index(policy_include) > facade_text.index(env_include):
    raise SystemExit("codegen must load the marker policy before assembling Backend")
if 'include "./codegen_value_type.elisa"' not in env_text:
    raise SystemExit("Backend environment no longer assembles the ValueType wrappers")
if "builtin_state_marker_type(type_name)" not in ANNOTATION_SCOPE.read_text():
    raise SystemExit("typestate annotation resolution no longer maps through the proved wrapper")
if compact("state_marker: ValueType = builtin_state_marker_type(type_name) state_marker return if state_marker.bits != 0") not in compact(ANNOTATION_SCOPE.read_text()):
    raise SystemExit("annotation resolution no longer preserves nonzero marker identities")
if "builtin_state_marker_name(value_type.bits)" not in NAME_MANGLING.read_text():
    raise SystemExit("generic name mangling no longer reverses the proved marker tag")
if compact("TypeKind.Unmodeled: text <- builtin_state_marker_name(value_type.bits)") not in compact(NAME_MANGLING.read_text()):
    raise SystemExit("name mangling no longer uses marker tags for Unmodeled state identities")

positive_names = {
    "marker_name_to_tag_contract_is_exact",
    "marker_tag_to_name_contract_is_exact",
    "every_marker_name_round_trips",
    "every_marker_tag_round_trips",
    "unknown_marker_values_use_the_sentinel",
    "marker_tags_are_nonzero_and_distinct",
}
negative_names = {
    "local_marker_must_not_use_frozen_tag",
    "frozen_tag_must_not_name_local",
    "unknown_name_must_not_use_known_tag",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/backend/codegen_state_marker_policy.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer imports the production marker policy")

for marker, tag in name_rows:
    if f'BackendStateMarkerPolicy::name_for_tag(BackendStateMarkerPolicy::tag_for_name("{marker}")) == "{marker}"' not in positive_text:
        raise SystemExit(f"round-trip proof lost marker {marker}")
    tag_variable = f"{tag.lower()}_tag"
    tag_declaration = f"{tag_variable}: u32 = BackendStateMarkerPolicy::BUILTIN_STATE_MARKER_{tag}_TAG"
    if tag_declaration not in positive_text:
        raise SystemExit(f"round-trip proof lost tag declaration {tag}")
    if f'BackendStateMarkerPolicy::tag_for_name(BackendStateMarkerPolicy::name_for_tag({tag_variable})) == {tag_variable}' not in positive_text:
        raise SystemExit(f"reverse round-trip proof lost tag {tag}")

expected_wrong_claims = {
    "local_marker_must_not_use_frozen_tag": "return BackendStateMarkerPolicy::tag_for_name(\"Local\") == BackendStateMarkerPolicy::BUILTIN_STATE_MARKER_FROZEN_TAG",
    "frozen_tag_must_not_name_local": "return BackendStateMarkerPolicy::name_for_tag(BackendStateMarkerPolicy::BUILTIN_STATE_MARKER_FROZEN_TAG) == \"Local\"",
    "unknown_name_must_not_use_known_tag": "return BackendStateMarkerPolicy::tag_for_name(\"Other\") == BackendStateMarkerPolicy::BUILTIN_STATE_MARKER_LOCAL_TAG",
}
for name, claim in expected_wrong_claims.items():
    if compact(f"def {name}() -> bool: ensure result == true {claim}") not in compact(negative_text):
        raise SystemExit(f"{name} false-control assertion changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("state-marker policy proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POLICY, FACADE, ENV, VALUE_TYPE, ANNOTATION_SCOPE, NAME_MANGLING,
    *source_closure,
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
assert positive == run(POSITIVE)[1], "marker proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert negative == run(NEGATIVE)[1], "marker false-control report changed across repeated runs"

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact codegen state-marker tags, forward and reverse round trips, sentinel behavior, and tag uniqueness",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
