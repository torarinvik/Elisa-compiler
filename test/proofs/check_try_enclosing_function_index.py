"""Source-bind and admit the try-site enclosing-function predecessor proof."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from parity_smoke_source import read_parity_smoke_source, parity_smoke_inputs
import re
import subprocess

from try_enclosing_index_checks import check_try_enclosing_index
from try_callable_resolution_checks import check_try_callable_resolution
from try_family_visibility_checks import check_try_family_visibility
from try_fallibility_proof_checks import check_try_fallibility_proofs
from proof_product_gate import require_current_product, source_include_closure, read_semantic_declaration_source


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE_FILES = [
    ROOT / "src/semantic/check_try_fallible.elisa",
    ROOT / "src/semantic/check_try_callable_lookup.elisa",
    ROOT / "src/semantic/check_try_error_family.elisa",
    ROOT / "src/semantic/check_try_fallible/using_aliases.elisa",
    ROOT / "src/semantic/check_try_fallible/callable_errors.elisa",
    ROOT / "src/semantic/check_try_fallible/callable_rows.elisa",
    ROOT / "src/semantic/check_try_fallible/callable_arguments.elisa",
    ROOT / "src/semantic/check_try_fallible/callable_overloads.elisa",
    ROOT / "src/semantic/check_try_fallible/callable_noncall_expressions.elisa",
    ROOT / "src/semantic/check_try_fallible/direct_raises.elisa",
    ROOT / "src/semantic/check_try_fallible/noncall_scan.elisa",
    ROOT / "src/semantic/check_try_fallible/noncall_checks.elisa",
    ROOT / "src/semantic/check_try_fallible/block_sources.elisa",
    ROOT / "src/semantic/check_try_fallible/fallback_casts.elisa",
]
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PIPELINE_FILES = [
    ROOT / "src/semantic/semantic_api.elisa",
    ROOT / "src/semantic/semantic_api/full_pipeline.elisa",
]
PARSER_ARGUMENT_SOURCE = ROOT / "src/parser/parser_expr_query.elisa"
PARSER_FUNCTION_SOURCE = ROOT / "src/parser/parser_types_function.elisa"
PARSER_DECLARATION_SOURCE = ROOT / "src/parser/parser_decl.elisa"
PARSER_VISIBILITY_SOURCE = ROOT / "src/parser/parser_decl_module.elisa"
PARSER_CATCH_SOURCE = ROOT / "src/parser/parser_stmt_pattern_arms.elisa"
PARSER_NOMINAL_SOURCES = [
    ROOT / "src/parser/parser_types_aggregate.elisa",
    ROOT / "src/parser/parser_export_surface.elisa",
    ROOT / "src/parser/parser_types.elisa",
]
POSITIVE = HERE / "try_enclosing_function_index.elisa"
NEGATIVE = HERE / "try_enclosing_function_index_rejected.elisa"
QUALIFIED_LEAF_FIXTURE = ROOT / "test/repro/try_qualified_module_leaf_collision.elisa"
NESTED_GLOBAL_ALIAS_FIXTURE = ROOT / "test/repro/try_nested_global_using_alias.elisa"
ZERO_OFFSET_ENCLOSING_FIXTURE = ROOT / "test/repro/try_zero_offset_enclosing_function_identity.elisa"
LINE_ZERO_NONERROR_FIXTURE = ROOT / "test/repro/try_nonerror_enclosing_line_zero.elisa"
FIRST_CLASS_AMBIGUOUS_FAMILY_FIXTURE = ROOT / "test/repro/try_first_class_ambiguous_error_family.elisa"
FIRST_CLASS_INACTIVE_DUPLICATE_FAMILY_FIXTURE = ROOT / "test/repro/try_first_class_inactive_duplicate_error_family.elisa"
TRY_SMOKE = ROOT / "test/parity/try_fallible_smoke.sh"
PRIVATE_OVERLOAD_FIXTURE = ROOT / "test/repro/try_overload_private_winner_visibility.elisa"
PRIVATE_OVERLOAD_SMOKE = ROOT / "test/parity/try_overload_private_winner_visibility_smoke.sh"
PROOF_PROCESS_TIMEOUT_SECONDS = 60

POSITION_CONSTANTS = {
    "FALLIBLE_FUNCTION_NO_OFFSET": ("u32", "4294967295"),
    "FALLIBLE_FUNCTION_NO_LINE": ("u32", "0"),
    "FALLIBLE_FUNCTION_FIRST_POSITION": ("usize", "0"),
    "FALLIBLE_FUNCTION_POSITION_STEP": ("usize", "1"),
    "FALLIBLE_FUNCTION_SEARCH_DIVISOR": ("usize", "2"),
}
POSITIVE_NAMES = {
    "try_offsets_are_valid",
    "try_offsets_are_nondecreasing",
    "try_predecessor_is_last",
    "try_linear_predecessor",
    "try_binary_predecessor",
    "last_predecessor_results_are_unique",
    "sorted_binary_predecessor_equals_linear_reference",
    "duplicate_offsets_select_the_last_qualifying_position",
    "zero_offset_is_a_real_position",
    "unsorted_offsets_keep_zero_in_linear_fallback",
    "sorted_binary_predecessor_preserves_parallel_line_mapping",
    "empty_index_reports_no_predecessor",
    "sorted_index_without_a_predecessor_reports_fallback_case",
}
NEGATIVE_NAMES = {
    "false_claim_duplicate_offsets_select_the_first_position",
    "false_claim_duplicate_offsets_keep_the_first_line",
    "false_claim_empty_index_has_a_predecessor",
    "false_claim_no_predecessor_has_a_position",
}


def strip_line_comment(line: str) -> str:
    """Remove # comments while preserving # bytes inside quoted literals."""
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
        elif char in ('"', "'"):
            quote = char
        elif char == "#":
            return line[:index]
    return line


def normalize_code_line(code: str) -> str:
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
        elif char in ('"', "'"):
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


def compact_code(text: str) -> tuple[tuple[int, str], ...]:
    code_lines = []
    for line in text.splitlines():
        uncommented = strip_line_comment(line)
        if uncommented.strip():
            expanded = uncommented.expandtabs(4)
            indent = len(expanded) - len(expanded.lstrip())
            code_lines.append((indent, normalize_code_line(expanded.lstrip())))
    if not code_lines:
        return ()
    base_indent = min(indent for indent, _ in code_lines)
    return tuple((indent - base_indent, code) for indent, code in code_lines)


def compact(text: str) -> str:
    return "\n".join(" " * indent + code for indent, code in compact_code(text))


def compact_inline(text: str) -> str:
    return " ".join(compact(text).split())


def contains_contiguous_block(source: str, block: str) -> bool:
    source_lines = compact_code(source)
    expected_lines = compact_code(block)
    for start in range(len(source_lines) - len(expected_lines) + 1):
        candidate = source_lines[start:start + len(expected_lines)]
        base_indent = candidate[0][0]
        if tuple((indent - base_indent, code) for indent, code in candidate) == expected_lines:
            return True
    return False


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}(?:\[[^\n]*\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\n]*\])?\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def constant_definitions(source: str) -> dict[str, tuple[str, str]]:
    return {
        name: (type_name, value)
        for name, type_name, value in re.findall(
            r"(?m)^\s*const ([A-Z][A-Z0-9_]*): ([A-Za-z0-9_]+) = ([^#\n]+)", source
        )
    }


source_text = "\n".join(path.read_text() for path in SOURCE_FILES)
semantic_text = SEMANTIC.read_text()
pipeline_text = "\n".join(read_semantic_declaration_source(path) for path in PIPELINE_FILES)
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
qualified_leaf_fixture = QUALIFIED_LEAF_FIXTURE.read_text()
nested_global_alias_fixture = NESTED_GLOBAL_ALIAS_FIXTURE.read_text()
zero_offset_enclosing_fixture = ZERO_OFFSET_ENCLOSING_FIXTURE.read_text()
line_zero_nonerror_fixture = LINE_ZERO_NONERROR_FIXTURE.read_text()
first_class_ambiguous_family_fixture = FIRST_CLASS_AMBIGUOUS_FAMILY_FIXTURE.read_text()
first_class_inactive_duplicate_family_fixture = FIRST_CLASS_INACTIVE_DUPLICATE_FAMILY_FIXTURE.read_text()
try_smoke = read_parity_smoke_source(TRY_SMOKE)
private_overload_fixture = PRIVATE_OVERLOAD_FIXTURE.read_text()
private_overload_smoke = PRIVATE_OVERLOAD_SMOKE.read_text()

if not __debug__:
    raise SystemExit("run without Python -O")
facts = check_try_enclosing_index(
    MANIFEST=MANIFEST,
    POSITION_CONSTANTS=POSITION_CONSTANTS,
    ROOT=ROOT,
    args=args,
    compact=compact,
    compact_inline=compact_inline,
    constant_definitions=constant_definitions,
    contains_contiguous_block=contains_contiguous_block,
    first_class_ambiguous_family_fixture=first_class_ambiguous_family_fixture,
    first_class_inactive_duplicate_family_fixture=first_class_inactive_duplicate_family_fixture,
    function_section=function_section,
    line_zero_nonerror_fixture=line_zero_nonerror_fixture,
    nested_global_alias_fixture=nested_global_alias_fixture,
    positive_text=positive_text,
    qualified_leaf_fixture=qualified_leaf_fixture,
    source_text=source_text,
    try_smoke=try_smoke,
    zero_offset_enclosing_fixture=zero_offset_enclosing_fixture,
)
facts.update(check_try_callable_resolution(
    facts=facts,
    PARSER_ARGUMENT_SOURCE=PARSER_ARGUMENT_SOURCE,
    PARSER_CATCH_SOURCE=PARSER_CATCH_SOURCE,
    PARSER_DECLARATION_SOURCE=PARSER_DECLARATION_SOURCE,
    PARSER_FUNCTION_SOURCE=PARSER_FUNCTION_SOURCE,
    PARSER_NOMINAL_SOURCES=PARSER_NOMINAL_SOURCES,
    PARSER_VISIBILITY_SOURCE=PARSER_VISIBILITY_SOURCE,
    compact_inline=compact_inline,
    function_section=function_section,
    private_overload_fixture=private_overload_fixture,
    private_overload_smoke=private_overload_smoke,
    source_text=source_text,
))
check_try_family_visibility(
    facts=facts,
    ROOT=ROOT,
    compact_inline=compact_inline,
    function_section=function_section,
    source_text=source_text,
)
check_try_fallibility_proofs(
    NEGATIVE=NEGATIVE,
    NEGATIVE_NAMES=NEGATIVE_NAMES,
    POSITIVE=POSITIVE,
    POSITIVE_NAMES=POSITIVE_NAMES,
    compact_inline=compact_inline,
    contains_contiguous_block=contains_contiguous_block,
    declarations=declarations,
    function_section=function_section,
    negative_text=negative_text,
    normalize_code_line=normalize_code_line,
    pipeline_text=pipeline_text,
    positive_text=positive_text,
    semantic_text=semantic_text,
    source_text=source_text,
    strip_line_comment=strip_line_comment,
)

if args.source_only:
    print(json.dumps({"source_bound": True, "theorems": len(POSITIVE_NAMES), "try_source_files": len(SOURCE_FILES), "pipeline_source_files": len(PIPELINE_FILES), "parser_argument_source": 1, "parser_function_source": 1, "parser_visibility_source": 1, "parser_nominal_sources": len(PARSER_NOMINAL_SOURCES)}))
    raise SystemExit(0)

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("try enclosing-function proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
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
    *(HERE / name for name in ("try_enclosing_index_checks.py", "try_callable_resolution_checks.py", "try_family_visibility_checks.py", "try_fallibility_proof_checks.py")),
    *SOURCE_FILES,
    SEMANTIC,
    *PIPELINE_FILES, *source_include_closure([PIPELINE_FILES[-1]]),
    PARSER_ARGUMENT_SOURCE,
    PARSER_FUNCTION_SOURCE,
    PARSER_DECLARATION_SOURCE,
    PARSER_VISIBILITY_SOURCE,
    PARSER_CATCH_SOURCE,
    *PARSER_NOMINAL_SOURCES,
    ZERO_OFFSET_ENCLOSING_FIXTURE,
    HERE / "parity_smoke_source.py", *parity_smoke_inputs(TRY_SMOKE),
    ROOT / "test/atoms/try_fallback_source.elisa",
    ROOT / "test/repro/try_overload_private_same_named_module_types.elisa",
    ROOT / "test/parity/try_overload_private_same_named_module_types_smoke.sh",
    ROOT / "test/repro/try_overload_nominal_identity_controls.elisa",
    ROOT / "test/parity/try_overload_nominal_identity_controls_smoke.sh",
    ROOT / "test/repro/try_overload_static_import_family.elisa",
    ROOT / "test/repro/try_overload_static_alias_family.elisa",
    ROOT / "test/repro/try_overload_imported_argument_type_id.elisa",
    LINE_ZERO_NONERROR_FIXTURE,
    FIRST_CLASS_AMBIGUOUS_FAMILY_FIXTURE,
    FIRST_CLASS_INACTIVE_DUPLICATE_FAMILY_FIXTURE,
    ROOT / "test/parity/try_overload_imported_argument_type_id_smoke.sh",
    ROOT / "test/parity/try_overload_static_import_family_smoke.sh",
    ROOT / "test/parity/try_overload_static_alias_family_smoke.sh",
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_PROCESS_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert negative["summary"]["proven"] < negative["summary"]["obligations"]
assert {finding["name"] for finding in negative["findings"]} == NEGATIVE_NAMES
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == product_manifest
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay or final provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "the model proves sorted predecessor selection and preserves its parallel line mapping; source gates pin zero-offset, unsorted-index, and no-predecessor fallback wiring to the production linear lookup",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
}, sort_keys=True))
