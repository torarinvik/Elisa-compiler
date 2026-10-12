"""Admit source-linked never-leak category-phrase and severity-prefix proofs."""
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
HELPER = ROOT / "src/driver/never_leak_report_names.elisa"
REPORT = ROOT / "src/driver/elisac_never_leak_report.elisa"
ACCUMULATOR = ROOT / "src/driver/elisac_never_leak_accumulator.elisa"
VALUE_THREAD = ROOT / "src/driver/elisac_never_leak_threading.elisa"
PUSH_LOOP = ROOT / "src/driver/elisac_never_leak_push_loop.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
CODES = ROOT / "src/semantic/never_leak_codes.elisa"
ENV_VALUES = ROOT / "src/driver/never_leak_env_values.elisa"
POSITIVE = HERE / "never_leak_report_labels.elisa"
NEGATIVE = HERE / "never_leak_report_labels_rejected.elisa"
ERROR_MODE = "NeverLeakEnvValues::NL_ENV_MODE_ERROR"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split()) for line in text.splitlines()
                   if not line.lstrip().startswith("#"))


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
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_in_order(body: str, parts: tuple[str, ...], message: str) -> None:
    positions = [body.find(compact(part)) for part in parts]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(message)


expected_codes = {
    "NEVER_LEAK_CHAIN": 1,
    "NEVER_LEAK_OVERLAP": 4,
    "NEVER_LEAK_LOOP": 5,
    "NEVER_LEAK_CATEGORY_UNKNOWN": 0,
}
codes_text = CODES.read_text()
for name, value in expected_codes.items():
    if not re.search(rf"(?m)^        const {name}: u8 = {value}\s*$", codes_text):
        raise SystemExit(f"source category code {name} changed")

env_text = ENV_VALUES.read_text()
if not re.search(r"(?m)^        const NL_ENV_MODE_WARN: u8 = 1\s*$", env_text):
    raise SystemExit("named warning mode must remain code 1")
if not re.search(r"(?m)^        const NL_ENV_MODE_ERROR: u8 = 2\s*$", env_text):
    raise SystemExit("named error mode must remain code 2")
if 'include "./never_leak_codes.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("Semantic no longer includes the shared never-leak category codes")

helper_text = HELPER.read_text()
phrase = compact(function_section(helper_text, "category_phrase"))
phrase_steps = (
    'return when category: Semantic::NEVER_LEAK_CHAIN -> "chain with a loop jump (its last use binds another local, and a `break`/`continue` for an enclosing loop lies in between)" if escapes else "chain (its last use binds another local, so that binding can take the statements as a block expression)"',
    'Semantic::NEVER_LEAK_OVERLAP -> "overlap (a local declared after it is still needed after its last use)"',
    'Semantic::NEVER_LEAK_LOOP -> "loop (its last use is a loop it feeds: a counter, accumulator or loop input)"',
    '_ -> "plain (its last use is a statement with no value to bind)"',
)
require_in_order(phrase, phrase_steps, "production category phrase table or fallback changed")
severity_prefix = compact(function_section(helper_text, "severity_prefix"))
if compact('return ": error: " if mode == NeverLeakEnvValues::NL_ENV_MODE_ERROR else ": warning: "') not in severity_prefix:
    raise SystemExit("production severity prefix no longer matches the named error mode and warning fallback")

driver_text = DRIVER.read_text()
if not (
    driver_text.index('include "../semantic/semantic.elisa"')
    < driver_text.index('include "./never_leak_env_values.elisa"')
    < driver_text.index('include "./never_leak_report_names.elisa"')
    < driver_text.index('include "./elisac_never_leak_report.elisa"')
):
    raise SystemExit("driver include order no longer places category codes and helpers before report wrappers")
if 'include "./never_leak_env_values.elisa"' not in driver_text:
    raise SystemExit("driver no longer includes the named environment mode")

report_text = REPORT.read_text()
if compact("return NeverLeakReportNames::category_phrase(finding.category, finding.escapes)") not in compact(function_section(report_text, "nl_category_phrase")):
    raise SystemExit("report category phrase wrapper no longer delegates to the production table")
report = compact(function_section(report_text, "nl_report_finding"))
require_in_order(report, (
    "emit_tokens_push_sview(text, NeverLeakReportNames::severity_prefix(mode))",
    'emit_tokens_push_sview(text, "local ")',
), "ordinary finding report no longer uses the production severity helper")
if "emit_tokens_push_sview(text,nl_category_phrase(finding))" not in report:
    raise SystemExit("ordinary finding report no longer uses the proved category phrase")
report_dispatch = (
    "if finding.category == Semantic::NEVER_LEAK_CHAIN: nl_render_chain(text, finding, names, source) "
    "elif finding.category == Semantic::NEVER_LEAK_OVERLAP: nl_render_overlap(text, finding, names, source) "
    "elif finding.category == Semantic::NEVER_LEAK_LOOP: nl_render_loop(text, finding, source) "
    "else: nl_render_plain(text, finding, source)"
)
if compact(report_dispatch) not in report:
    raise SystemExit("ordinary finding renderer no longer has the explicit loop and plain fallback dispatch")

severity_checks = (
    (REPORT, "nl_report_finding", 'emit_tokens_push_sview(text, NeverLeakReportNames::severity_prefix(mode))'),
    (ACCUMULATOR, "nl_report_accumulator", 'emit_tokens_push_sview(text, NeverLeakReportNames::severity_prefix(mode))'),
    (VALUE_THREAD, "nl_report_value_thread", 'emit_tokens_push_sview(text, NeverLeakReportNames::severity_prefix(mode))'),
    (PUSH_LOOP, "nl_report_push_loop", 'emit_tokens_push_sview(text, NeverLeakReportNames::severity_prefix(mode))'),
)
for path, function_name, expected in severity_checks:
    body = compact(function_section(path.read_text(), function_name))
    if compact(expected) not in body:
        raise SystemExit(f"{function_name} no longer uses the source-linked severity helper")

positive_names = {
    "category_phrase_is_exact_for_all_categories",
    "severity_prefix_is_exact_for_all_modes",
    "explicit_loop_category_has_loop_phrase",
    "unrecognized_category_uses_plain_phrase",
    "every_non_error_mode_uses_warning_prefix",
}
negative_names = {
    "the_loop_category_uses_the_plain_phrase",
    "an_unrecognized_category_uses_the_loop_phrase",
    "warning_mode_uses_error_prefix",
    "error_mode_uses_warning_prefix",
}
positive_shapes = {
    "category_phrase_is_exact_for_all_categories": "ensure result == true",
    "severity_prefix_is_exact_for_all_modes": "ensure result == true",
    "explicit_loop_category_has_loop_phrase": 'ensure result == true return NeverLeakReportNames::category_phrase(Semantic::NEVER_LEAK_LOOP, false) == "loop (its last use is a loop it feeds: a counter, accumulator or loop input)"',
    "unrecognized_category_uses_plain_phrase": 'ensure result == true return NeverLeakReportNames::category_phrase(Semantic::NEVER_LEAK_CATEGORY_UNKNOWN, true) == "plain (its last use is a statement with no value to bind)"',
    "every_non_error_mode_uses_warning_prefix": 'ensure result == true return NeverLeakReportNames::severity_prefix(NeverLeakEnvValues::NL_ENV_MODE_OFF) == ": warning: "',
}
negative_shapes = {
    "the_loop_category_uses_the_plain_phrase": 'ensure result == true return NeverLeakReportNames::category_phrase(Semantic::NEVER_LEAK_LOOP, false) == "plain (its last use is a statement with no value to bind)"',
    "an_unrecognized_category_uses_the_loop_phrase": 'ensure result == true return NeverLeakReportNames::category_phrase(Semantic::NEVER_LEAK_CATEGORY_UNKNOWN, true) == "loop (its last use is a loop it feeds: a counter, accumulator or loop input)"',
    "warning_mode_uses_error_prefix": 'ensure result == true return NeverLeakReportNames::severity_prefix(NeverLeakEnvValues::NL_ENV_MODE_WARN) == ": error: "',
    "error_mode_uses_warning_prefix": 'ensure result == true return NeverLeakReportNames::severity_prefix(NeverLeakEnvValues::NL_ENV_MODE_ERROR) == ": warning: "',
}

for path, expected, shapes in (
    (POSITIVE, positive_names, positive_shapes),
    (NEGATIVE, negative_names, negative_shapes),
):
    proof_text = path.read_text()
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if path == POSITIVE:
        for include in (
            '../../src/semantic/binding_identity_types.elisa',
            '../../src/semantic/never_leak_codes.elisa',
            '../../src/driver/never_leak_env_values.elisa',
            '../../src/driver/never_leak_report_names.elisa',
        ):
            if f'include "{include}"' not in proof_text:
                raise SystemExit(f"{path.name} no longer imports production source {include}")
    elif 'include "./never_leak_report_labels.elisa"' not in proof_text:
        raise SystemExit(f"{path.name} no longer reuses the admitted production-linked positive model")
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer states its exact production phrase/severity law")

positive_text = POSITIVE.read_text()
category_law = compact(function_section(positive_text, "category_phrase_is_exact_for_all_categories"))
require_in_order(category_law, (
    'category == Semantic::NEVER_LEAK_CHAIN and escapes and NeverLeakReportNames::category_phrase(category, escapes) == "chain with a loop jump (its last use binds another local, and a `break`/`continue` for an enclosing loop lies in between)"',
    'category == Semantic::NEVER_LEAK_CHAIN and not escapes and NeverLeakReportNames::category_phrase(category, escapes) == "chain (its last use binds another local, so that binding can take the statements as a block expression)"',
    'category == Semantic::NEVER_LEAK_OVERLAP and NeverLeakReportNames::category_phrase(category, escapes) == "overlap (a local declared after it is still needed after its last use)"',
    'category == Semantic::NEVER_LEAK_LOOP and NeverLeakReportNames::category_phrase(category, escapes) == "loop (its last use is a loop it feeds: a counter, accumulator or loop input)"',
    'category != Semantic::NEVER_LEAK_CHAIN and category != Semantic::NEVER_LEAK_OVERLAP and category != Semantic::NEVER_LEAK_LOOP and NeverLeakReportNames::category_phrase(category, escapes) == "plain (its last use is a statement with no value to bind)"',
), "category phrase theorem no longer covers every production case in order")
severity_law = compact(function_section(positive_text, "severity_prefix_is_exact_for_all_modes"))
require_in_order(severity_law, (
    f'mode == {ERROR_MODE} and NeverLeakReportNames::severity_prefix(mode) == ": error: "',
    f'mode != {ERROR_MODE} and NeverLeakReportNames::severity_prefix(mode) == ": warning: "',
), "severity theorem no longer covers error mode and the complete warning fallback")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("never-leak report-label proof requires a strict proof build")
compiler = manifest["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    REPORT, HELPER, ACCUMULATOR, VALUE_THREAD, PUSH_LOOP, DRIVER, SEMANTIC, CODES, ENV_VALUES,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE, DRIVER]),
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
assert positive == run(POSITIVE)[1], "never-leak report-label proof changed across identical runs"
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {(item["kind"], item["name"]) for item in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(item["status"] == "disproved" and item["counterexample_found"]
           for item in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "production never-leak category phrases, error-versus-warning prefixes, and non-error fallback",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
