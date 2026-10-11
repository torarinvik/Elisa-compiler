"""Replay the pure stage1 source/environment-to-semantic-options policy proof."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROJECTION = ROOT / "src/driver/stage1_semantic_option_projection.elisa"
OPTIONS = ROOT / "src/semantic/incremental_semantic_options.elisa"
OPTIONS_TYPES = ROOT / "src/semantic/incremental_semantic_options_types.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
SOURCE_VIEW = ROOT / "src/lexer/source_view.elisa"
SOURCE_PROBES = ROOT / "src/driver/elisac_source_probes.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
POSITIVE = HERE / "stage1_semantic_option_projection.elisa"
NEGATIVE = HERE / "stage1_semantic_option_projection_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def function_region(source: str, name: str) -> str:
    match = re.search(rf"^([ \t]*)def {re.escape(name)}\(", source, re.M)
    if not match:
        raise SystemExit(f"missing production function {name}")
    end = re.search(rf"^{re.escape(match.group(1))}def ", source[match.end():], re.M)
    return source[match.start():match.end() + end.start()] if end else source[match.start():]


def call_arguments(source: str, callee: str) -> tuple[str, ...]:
    matches = list(re.finditer(re.escape(callee) + r"\s*\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected one {callee} call, found {len(matches)}")
    opening = source.find("(", matches[0].start())
    depth = 0
    quote = None
    escaped = False
    closing = None
    for index in range(opening, len(source)):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                closing = index
                break
    if closing is None:
        raise SystemExit(f"unterminated {callee} call")
    body = source[opening + 1:closing]
    arguments: list[str] = []
    start = 0
    stack: list[str] = []
    quote = None
    escaped = False
    closing_for = {")": "(", "]": "[", "}": "{"}
    for index, char in enumerate(body):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack or stack.pop() != closing_for[char]:
                raise SystemExit(f"unbalanced {callee} arguments")
        elif char == "," and not stack:
            arguments.append(body[start:index].strip())
            start = index + 1
    if stack or quote is not None:
        raise SystemExit(f"unbalanced {callee} arguments")
    if body[start:].strip():
        arguments.append(body[start:].strip())
    return tuple(compact(argument) for argument in arguments)


projection_text = PROJECTION.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
options_text = OPTIONS.read_text()
fields = (
    "enforce_unsafe_permissions", "flow_strict", "runtime_std", "flow_warn",
    "enable_smt", "warn_discarded", "enforce_progress", "enforce_extern_contracts",
    "enforce_raw_unsafe", "emit_proof_hole", "region_stack_cap",
    "enforce_global_permissions", "enforce_mutable_global_grants", "carrier_surface",
)
observations = (
    "strict_header", "runtime_std_detected", "smt_environment_enabled", "smt_header",
    "strict_externs_environment_enabled", "strict_externs_header", "unsafe_header",
    "proofhole_header", "globals_header", "permissive_environment_enabled",
    "carrier_surface_enabled",
)
expected_arguments = (
    "strict_header", "false", "runtime_std_detected", "false",
    "smt_environment_enabled or smt_header", "false", "false",
    "strict_externs_environment_enabled or strict_externs_header", "unsafe_header",
    "proofhole_header", "STAGE1_REGION_STACK_CAP", "globals_header", "not permissive_environment_enabled",
    "carrier_surface_enabled",
)
projection_body = function_region(projection_text, "stage1_semantic_options_from_observations")
compact_projection = compact(projection_body)
if 'include"../semantic/incremental_semantic_options.elisa"' not in compact(projection_text):
    raise SystemExit("policy projection no longer imports the production semantic options type and constructor")
if not re.search(r"\bconst STAGE1_REGION_STACK_CAP: i64 = 64\b", projection_text):
    raise SystemExit("Stage1 region stack cap must be defined once by its named policy constant")
if call_arguments(projection_body, "Semantic::incremental_semantic_options_from_values") != tuple(
        compact(argument) for argument in expected_arguments):
    raise SystemExit("stage1 policy projection no longer maps observations to the expected constructor fields")
if tuple(re.findall(r"ensureresult\.(\w+)==", compact_projection)) != fields:
    raise SystemExit("stage1 projection must contract every semantic option field in record order")
projection_signature = compact(projection_body.split("->", 1)[0])
if tuple(re.findall(r"(\w+):bool", projection_signature)) != observations:
    raise SystemExit("stage1 projection observation parameters or their order changed")
if 'include"../../src/driver/stage1_semantic_option_projection.elisa"' not in compact(positive_text):
    raise SystemExit("positive proof no longer imports the production policy projection")
if 'include"../../src/lexer/tokens.elisa"' not in compact(positive_text) or 'include"../../src/lexer/source_view.elisa"' not in compact(positive_text):
    raise SystemExit("positive proof is missing the production encoder's lexer dependencies")
if 'include"./stage1_semantic_option_projection.elisa"' not in compact(negative_text):
    raise SystemExit("negative controls no longer import the positive policy proof")
if not all(f"options.{field}==" in compact(positive_text) for field in fields):
    raise SystemExit("positive theorem no longer checks each projected option field")

source_probes_text = SOURCE_PROBES.read_text()
driver_text = DRIVER.read_text()
if 'include "./stage1_semantic_option_projection.elisa"' not in source_probes_text:
    raise SystemExit("Stage1 source probes no longer import the proved option projection")
if 'include "./elisac_source_probes.elisa"' not in driver_text:
    raise SystemExit("compiler driver no longer includes the source probes that supply policy observations")
stage1_body = compact(function_region(source_probes_text, "stage1_semantic_options"))
expected_policy_call = (
    "returnstage1_semantic_options_from_observations("
    "source_has_strict_header(src_ptr,source_len),"
    "runtime_std_enabled(src_ptr,source_len),"
    'env_flag_enabled("ELISA_STAGE1_SMT"),'
    "source_has_smt_header(src_ptr,source_len),"
    'env_flag_enabled("ELISA_STAGE1_STRICT_EXTERNS"),'
    'source_has_header(src_ptr,source_len,"strict-externs"),'
    "source_has_unsafe_header(src_ptr,source_len),"
    "source_has_proofhole_header(src_ptr,source_len),"
    "source_has_global_header(src_ptr,source_len),"
    'env_flag_enabled("ELISA_STAGE1_PERMISSIVE"),'
    "carrier_surface_applies())"
)
if expected_policy_call not in stage1_body:
    raise SystemExit("Stage1 production observations no longer flow to the proved projection in order")
if "Semantic::incremental_semantic_options_from_values(" in stage1_body:
    raise SystemExit("Stage1 production bypasses the proved option projection")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("stage1 policy projection proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")


def include_closure(roots: list[Path]) -> list[Path]:
    include = re.compile(r'^\s*include\s+"([^"]+)"', re.MULTILINE)
    pending = list(roots)
    seen: set[Path] = set()
    while pending:
        path = pending.pop().resolve(strict=True)
        if path in seen:
            continue
        seen.add(path)
        for relative in include.findall(path.read_text()):
            child = (path.parent / relative).resolve(strict=True)
            if child not in seen:
                pending.append(child)
    return sorted(seen)


stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *include_closure([POSITIVE, NEGATIVE, PROJECTION]),
    OPTIONS, OPTIONS_TYPES, TOKENS, SOURCE_VIEW, SOURCE_PROBES, DRIVER,
]
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
assert positive == run(POSITIVE)[1], "positive policy proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "incremental_semantic_options_from_values",
    "stage1_semantic_options_from_observations",
    "stage1_projection_preserves_each_observation_and_default",
    "source_and_environment_switches_are_combined_exactly",
} <= verified

code, negative = run(NEGATIVE)
false_claims = {
    "a_source_smt_header_can_be_ignored_when_the_environment_is_off",
    "permissive_mode_can_keep_mutable_global_grants_enforced",
}
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(false_claims) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == false_claims
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not false_claims & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == product_manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "pure stage1 semantic-option policy projection from source/environment observations",
    "fields": list(fields),
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(false_claims),
    "sources_sha256": hashes_before,
}, sort_keys=True))
