"""Admit the source-linked proof of stage0-compatible @callconv normalization."""
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
HELPER = ROOT / "src/semantic/callconv_name.elisa"
CHECK = ROOT / "src/semantic/check_callconv.elisa"
BOUNDS = ROOT / "src/semantic/check_extern_bounds.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARSER = ROOT / "src/parser/parser_decl.elisa"
STAGE0 = ROOT.parent / "compiler/src/semantic/analyzer_annotations.go"
POSITIVE = HERE / "callconv_name.elisa"
NEGATIVE = HERE / "callconv_name_rejected.elisa"

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


aliases = (
    "c", "cdecl", "default", "fast", "fastcall", "cold", "coldcc",
    "stdcall", "x86_stdcall", "x86-stdcall", "winapi", "windows",
)


def alternatives(name: str, values: tuple[str, ...]) -> str:
    return " or ".join(f'equals_ascii_case_insensitive({name}, "{value}")' for value in values)


helper_text = HELPER.read_text()
positive_text = POSITIVE.read_text()
if "const SINGLE_ARGUMENT_COUNT: u32 = 1" not in helper_text:
    raise SystemExit("source helper lost the named one-argument policy")
helper_ascii_lower = function_section(helper_text, "ascii_lower")
lowering = (
    "value + CallConvAscii::CASE_FOLD_DELTA if value >= CallConvAscii::UPPER_A "
    "and value <= CallConvAscii::UPPER_Z else value"
)
if compact("ensure result == (" + lowering + ")") not in compact(helper_ascii_lower):
    raise SystemExit("production ASCII case-fold contract changed")
if compact("return " + lowering) not in compact(helper_ascii_lower):
    raise SystemExit("production ASCII case-fold implementation changed")

equals_spec = (
    "value.len == expected.len and (forall index in 0..<expected.len: "
    "index >= value.len or ascii_lower(sview_at(value, index)) == sview_at(expected, index))"
)
for source, label in (
    (function_section(helper_text, "equals_ascii_case_insensitive"), "production string comparison"),
    (function_section(positive_text, "ascii_case_insensitive_comparison_matches_spec"), "comparison proof"),
):
    qualified_spec = equals_spec.replace("ascii_lower(", "CallConvName::ascii_lower(") if label == "comparison proof" else equals_spec
    if compact(equals_spec) not in compact(source) and compact(qualified_spec) not in compact(source):
        raise SystemExit(f"{label} no longer states the bytewise ASCII case-fold specification")
    if label == "production string comparison" and compact("return false if value.len != expected.len") not in compact(source):
        raise SystemExit("production string comparison lost its length guard")

supported_spec = alternatives("name", aliases)
c_abi_spec = alternatives("name", ("c", "cdecl", "default"))
supported_pattern = (
    'when name: "c" | "cdecl" | "default" | "fast" | "fastcall" | "cold" | "coldcc" | '
    '"stdcall" | "x86_stdcall" | "x86-stdcall" | "winapi" | "windows" -> true _ -> false'
)
c_abi_pattern = 'when name: "c" | "cdecl" | "default" -> true _ -> false'
supported_classifier = "matches_supported_ascii_case(name) or is_exact_lowercase_supported(name)"
c_abi_classifier = "matches_c_abi_ascii_case(name) or is_exact_lowercase_c_abi(name)"
if compact(supported_spec) not in compact(function_section(helper_text, "matches_supported_ascii_case")):
    raise SystemExit("case-fold fallback no longer matches the complete stage0 alias set")
if compact(supported_spec.replace("equals_ascii_case_insensitive(", "CallConvName::equals_ascii_case_insensitive(")) not in compact(
    function_section(positive_text, "supported_casefold_fallback_matches_aliases")
):
    raise SystemExit("proof no longer covers the complete supported-name case-fold fallback")
if compact(supported_pattern) not in compact(function_section(helper_text, "is_exact_lowercase_supported")):
    raise SystemExit("production classifier no longer pattern-matches the exact lowercase aliases")
if compact(supported_pattern) not in compact(function_section(positive_text, "exact_lowercase_alias_match_is_complete")):
    raise SystemExit("proof no longer covers the exact lowercase alias pattern")
if compact(supported_classifier) not in compact(function_section(helper_text, "is_supported")):
    raise SystemExit("production classifier no longer combines exact matching with case-fold fallback")
if compact(supported_classifier.replace("matches_supported_ascii_case(", "CallConvName::matches_supported_ascii_case(").replace(
    "is_exact_lowercase_supported(", "CallConvName::is_exact_lowercase_supported("
)) not in compact(
    function_section(positive_text, "source_classifier_matches_stage0_aliases")
):
    raise SystemExit("source proof no longer matches the production alias classifier")
if compact(c_abi_spec) not in compact(function_section(helper_text, "matches_c_abi_ascii_case")):
    raise SystemExit("C-ABI case-fold fallback no longer matches stage0's C aliases")
if compact(c_abi_spec.replace("equals_ascii_case_insensitive(", "CallConvName::equals_ascii_case_insensitive(")) not in compact(
    function_section(positive_text, "c_abi_casefold_fallback_matches_aliases")
):
    raise SystemExit("proof no longer covers the C-ABI case-fold fallback")
if compact(c_abi_pattern) not in compact(function_section(helper_text, "is_exact_lowercase_c_abi")):
    raise SystemExit("production C-ABI classifier no longer pattern-matches lowercase aliases")
if compact(c_abi_pattern) not in compact(function_section(positive_text, "exact_lowercase_c_abi_match_is_complete")):
    raise SystemExit("proof no longer covers the exact lowercase C-ABI pattern")
if compact(c_abi_classifier) not in compact(function_section(helper_text, "is_c_abi")):
    raise SystemExit("production C-ABI classifier no longer combines exact matching with case-fold fallback")
if compact(c_abi_classifier.replace("matches_c_abi_ascii_case(", "CallConvName::matches_c_abi_ascii_case(").replace(
    "is_exact_lowercase_c_abi(", "CallConvName::is_exact_lowercase_c_abi("
)) not in compact(
    function_section(positive_text, "source_c_abi_classifier_matches_aliases")
):
    raise SystemExit("C-ABI proof no longer matches the production classifier")

stage0_text = STAGE0.read_text()
if "switch strings.ToLower(strings.TrimSpace(value))" not in stage0_text:
    raise SystemExit("stage0 no longer trims and case-folds calling-convention names")
if "if len(annotation.Args) != 1 {" not in stage0_text:
    raise SystemExit("stage0 no longer ignores callconv annotations with the wrong argument count")
stage0_groups = (
    'case "c", "cdecl", "default": return "c", true',
    'case "fast", "fastcall": return "fast", true',
    'case "cold", "coldcc": return "cold", true',
    'case "stdcall", "x86_stdcall", "x86-stdcall": return "stdcall", true',
    'case "winapi", "windows": return "winapi", true',
)
stage0_compact = compact(stage0_text)
for group in stage0_groups:
    if compact(group) not in stage0_compact:
        raise SystemExit(f"stage0 calling-convention normalization changed: {group}")

check_text = CHECK.read_text()
bounds_text = BOUNDS.read_text()
semantic_text = SEMANTIC.read_text()
parser_text = PARSER.read_text()
if 'include "./callconv_name.elisa"' not in semantic_text:
    raise SystemExit("semantic root no longer includes the source-linked calling-convention helper")
if "CallConvName::is_supported(conv)" not in check_text:
    raise SystemExit("call-convention diagnostic no longer delegates to the proved classifier")
if "decorator.arg_count == CallConvName::SINGLE_ARGUMENT_COUNT" not in check_text:
    raise SystemExit("call-convention diagnostic no longer checks the named one-argument policy")
if "def is_supported(" in check_text:
    raise SystemExit("call-convention diagnostic reintroduced an unproved local classifier")
if "CallConvName::is_c_abi(convention)" not in bounds_text:
    raise SystemExit("extern-bounds validation no longer delegates to the proved C-ABI classifier")
if "decorator.arg_count != CallConvName::SINGLE_ARGUMENT_COUNT" not in bounds_text:
    raise SystemExit("extern-bounds validation accepts malformed multi-argument callconv annotations")
if 'include "./check_callconv.elisa"' not in semantic_text or 'include "./check_extern_bounds.elisa"' not in semantic_text:
    raise SystemExit("calling-convention consumers are no longer part of the semantic layer")
capture = function_section(parser_text, "parse_decorator_arguments")
if "token.start.usize()" not in capture or "token.start.usize() + token.length.usize()" not in capture:
    raise SystemExit("decorator arguments no longer preserve their exact token spans")
for path in (POSITIVE, NEGATIVE):
    if 'include "../../src/semantic/callconv_name.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer imports the production helper")

expected_positive = {
    "stage0_callconv_requires_one_argument",
    "ascii_case_insensitive_comparison_matches_spec",
    "supported_casefold_fallback_matches_aliases",
    "exact_lowercase_alias_match_is_complete",
    "source_classifier_matches_stage0_aliases",
    "every_stage0_callconv_alias_is_accepted",
    "callconv_case_is_ignored",
    "c_abi_casefold_fallback_matches_aliases",
    "exact_lowercase_c_abi_match_is_complete",
    "source_c_abi_classifier_matches_aliases",
    "stage0_c_family_is_classified_as_c_abi",
    "unsupported_callconv_names_are_rejected",
}
expected_negative = {
    "fastcc_is_supported",
    "case_changed_windows_suffix_is_supported",
    "fastcall_is_c_abi",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declarations(POSITIVE) != expected_positive or declarations(NEGATIVE) != expected_negative:
    raise SystemExit("calling-convention proof declaration inventory changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("calling-convention proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    HELPER,
    CHECK,
    BOUNDS,
    SEMANTIC,
    PARSER,
    STAGE0,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, CHECK, BOUNDS, SEMANTIC]),
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


positive_code, positive = run(POSITIVE)
assert positive_code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "calling-convention proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive | {
    "ascii_lower",
    "equals_ascii_case_insensitive",
    "matches_supported_ascii_case",
    "matches_c_abi_ascii_case",
    "is_exact_lowercase_supported",
    "is_exact_lowercase_c_abi",
    "is_supported",
    "is_c_abi",
} <= verified

negative_code, negative = run(NEGATIVE)
assert negative_code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(expected_negative) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" and row["status"] == "disproved" and row["counterexample_found"]
           for row in negative["findings"])

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "stage0-compatible calling-convention aliases and C-ABI classification",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"]["source_revision"],
    "inputs_sha256": hashes_before,
}, sort_keys=True))
