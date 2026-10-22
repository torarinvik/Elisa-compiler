"""Source-bind and admit the try-site enclosing-function predecessor proof."""
from __future__ import annotations

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
SOURCE = ROOT / "src/semantic/check_try_fallible.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PIPELINE = ROOT / "src/semantic/semantic_api.elisa"
POSITIVE = HERE / "try_enclosing_function_index.elisa"
NEGATIVE = HERE / "try_enclosing_function_index_rejected.elisa"
PROOF_PROCESS_TIMEOUT_SECONDS = 60

POSITION_CONSTANTS = {
    "FALLIBLE_FUNCTION_NO_OFFSET": ("u32", "0"),
    "FALLIBLE_FUNCTION_NO_LINE": ("u32", "0"),
    "FALLIBLE_FUNCTION_FIRST_POSITION": ("usize", "0"),
    "FALLIBLE_FUNCTION_POSITION_STEP": ("usize", "1"),
    "FALLIBLE_FUNCTION_SEARCH_DIVISOR": ("usize", "2"),
}
POSITIVE_NAMES = {
    "try_offsets_are_nonzero",
    "try_offsets_are_nondecreasing",
    "try_predecessor_is_last",
    "try_linear_predecessor",
    "try_binary_predecessor",
    "last_predecessor_results_are_unique",
    "sorted_binary_predecessor_equals_linear_reference",
    "duplicate_offsets_select_the_last_qualifying_position",
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


source_text = SOURCE.read_text()
semantic_text = SEMANTIC.read_text()
pipeline_text = PIPELINE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")
source_constants = constant_definitions(source_text)
if not source_constants:
    raise SystemExit("could not read production position constants")
for name, definition in POSITION_CONSTANTS.items():
    if source_constants.get(name) != definition:
        raise SystemExit(f"production try-position constant changed: {name}")
proof_constants = constant_definitions(positive_text)
for proof_name, source_name in (
    ("TRY_ENCLOSING_NO_OFFSET", "FALLIBLE_FUNCTION_NO_OFFSET"),
    ("TRY_ENCLOSING_FIRST_POSITION", "FALLIBLE_FUNCTION_FIRST_POSITION"),
    ("TRY_ENCLOSING_POSITION_STEP", "FALLIBLE_FUNCTION_POSITION_STEP"),
    ("TRY_ENCLOSING_BINARY_DIVISOR", "FALLIBLE_FUNCTION_SEARCH_DIVISOR"),
):
    if proof_constants.get(proof_name) != source_constants.get(source_name):
        raise SystemExit(f"proof and production try-position constants differ: {proof_name} / {source_name}")

expected_linear = """
def enclosing_try_function(table: SymbolTable&, try_line: u32, try_offset: u32) -> (line: u32, offset: u32):
    best_line: mutable u32 = FALLIBLE_FUNCTION_NO_LINE
    best_offset_line: mutable u32 = FALLIBLE_FUNCTION_NO_LINE
    best_offset: mutable u32 = FALLIBLE_FUNCTION_NO_OFFSET
    for symbol in table.symbols |best_line, best_offset_line, best_offset|:
        if symbol.kind == SymbolKind.Func:
            best_line <- symbol.line if symbol.line <= try_line and symbol.line >= best_line
            if try_offset != FALLIBLE_FUNCTION_NO_OFFSET and symbol.offset != FALLIBLE_FUNCTION_NO_OFFSET and symbol.offset <= try_offset and symbol.offset >= best_offset:
                best_offset <- symbol.offset
                best_offset_line <- symbol.line
    return (best_offset_line, best_offset) if best_offset != FALLIBLE_FUNCTION_NO_OFFSET
    return (best_line, FALLIBLE_FUNCTION_NO_OFFSET)
"""
expected_builder = """
def fallible_function_position_index_build(index: mutable FallibleFunctionPositionIndex&, table: SymbolTable&) -> void:
    can Memory.Allocate, Abort.Panic:
        positions: mutable darray[FallibleFunctionPosition] = []
        offsets_ordered: mutable bool = true
        saw_previous: mutable bool = false
        previous_offset: mutable u32 = FALLIBLE_FUNCTION_NO_OFFSET
        for symbol in table.symbols |positions, offsets_ordered, saw_previous, previous_offset|:
            if symbol.kind == SymbolKind.Func and symbol.offset != FALLIBLE_FUNCTION_NO_OFFSET:
                offsets_ordered <- false if saw_previous and symbol.offset < previous_offset
                positions <- positions.push(FallibleFunctionPosition{offset: symbol.offset, line: symbol.line})
                previous_offset <- symbol.offset
                saw_previous <- true
        index.positions <- positions
        index.offsets_ordered <- offsets_ordered
        index.ready <- true
"""
expected_indexed = """
def enclosing_try_function_indexed(index: mutable FallibleFunctionPositionIndex&, table: SymbolTable&, try_line: u32, try_offset: u32) -> (line: u32, offset: u32):
    can Memory.Allocate, Abort.Panic:
        if not index.ready:
            fallible_function_position_index_build(index, table)
        if try_offset != FALLIBLE_FUNCTION_NO_OFFSET and index.offsets_ordered:
            low: mutable usize = FALLIBLE_FUNCTION_FIRST_POSITION
            high: mutable usize = index.positions.count
            while low < high |low, high, index, try_offset|:
                middle: usize = low + (high - low) / FALLIBLE_FUNCTION_SEARCH_DIVISOR
                if index.positions[middle].offset <= try_offset:
                    low <- middle + FALLIBLE_FUNCTION_POSITION_STEP
                else:
                    high <- middle
            if low > FALLIBLE_FUNCTION_FIRST_POSITION:
                position: FallibleFunctionPosition = index.positions[low - FALLIBLE_FUNCTION_POSITION_STEP]
                return (position.line, position.offset)
        return enclosing_try_function(table, try_line, try_offset)
"""
for name, expected in (
    ("enclosing_try_function", expected_linear),
    ("fallible_function_position_index_build", expected_builder),
    ("enclosing_try_function_indexed", expected_indexed),
):
    if compact(function_section(source_text, name)) != compact(expected):
        raise SystemExit(f"production {name} changed without updating the source-bound proof")

rows_function = function_section(source_text, "check_try_fallible_rows")
expected_dispatch = """
row_enclosing: mutable (line: u32, offset: u32) = (0, 0)
if try_site_count > 1:
    row_enclosing <- enclosing_try_function_indexed(function_positions, table, annotation.line, annotation.offset)
else:
    row_enclosing <- enclosing_try_function(table, annotation.line, annotation.offset)
row_module: sview = fallible_fn_module_indexed(module_index, module_annotations, row_enclosing.offset, row_enclosing.line)
"""
if not contains_contiguous_block(rows_function, expected_dispatch):
    raise SystemExit("try rows must use indexed enclosing-function lookup only for multiple try sites and feed its result into module scope resolution")
if compact_inline(rows_function).count("enclosing_try_function_indexed(") != 1 or \
        compact_inline(rows_function).count("enclosing_try_function(") != 1:
    raise SystemExit("try rows must retain exactly one indexed and one linear enclosing-function dispatch arm")
propagation_call = "table <- check_try_propagation_row(annotation, row_enclosing, row_module, row_qualifier, annotations, error_set_annotations, error_set_index, propagation_site_count, module_index, module_annotations, error_index, table, first_class_error_family, noncall_binding.lambda_error_family, noncall_binding.inside_lambda)"
if compact_inline(propagation_call) not in compact_inline(rows_function):
    raise SystemExit("resolved enclosing function must flow into try-propagation diagnostics")

main_try_check = function_section(source_text, "check_try_fallible")
rows_call = "table <- check_try_fallible_rows(file.top_decls, file.enum_annotations, projection.error_set_annotations, module_index, projection.module_annotations, projection.try_qualifiers, error_index, try_site_count, table) can Global{Read,Write} if try_site_count > 0"
if compact_inline(main_try_check).count(compact_inline(rows_call)) != 1:
    raise SystemExit("check_try_fallible must invoke the source-row checker when at least one try site exists")

if semantic_text.count('include "./check_try_fallible.elisa"') != 1:
    raise SystemExit("semantic module no longer includes the try-fallibility checker exactly once")
pipeline_function = function_section(pipeline_text, "check_full_into_pipeline")
pipeline_steps = [
    normalize_code_line(line)
    for line in pipeline_function.splitlines()
    if strip_line_comment(line).strip()
]
pipeline_call = normalize_code_line("table <- check_try_fallible(loop_view, table) can Global{Read,Write}")
pipeline_timer = normalize_code_line('PhaseTimer::minor("sem:check_try_fallible") can Global{Read,Write}')
if not any(pipeline_steps[index:index + 2] == [pipeline_call, pipeline_timer]
           for index in range(len(pipeline_steps) - 1)):
    raise SystemExit("semantic pipeline no longer invokes and times check_try_fallible")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("try enclosing-function proof inventory is incomplete or contains extras")
if 'include "./try_enclosing_function_index.elisa"' not in negative_text:
    raise SystemExit("negative controls no longer include the positive predecessor proof")

positive_shapes = {
    "try_predecessor_is_last": (
        "offsets[index] != TRY_ENCLOSING_NO_OFFSET and offsets[index] <= query",
        "forall later in index + TRY_ENCLOSING_POSITION_STEP..<offsets.count",
        "forall candidate in TRY_ENCLOSING_FIRST_POSITION..<offsets.count",
    ),
    "try_linear_predecessor": (
        "if offsets[index] != TRY_ENCLOSING_NO_OFFSET and offsets[index] <= query:",
        "selected <- index",
        "invariant found implies (",
        "invariant found or (",
        "forall prior in TRY_ENCLOSING_FIRST_POSITION..<index",
        "offsets[prior] == TRY_ENCLOSING_NO_OFFSET or offsets[prior] > query",
        "return (found, selected)",
    ),
    "try_binary_predecessor": (
        "requires try_offsets_are_nonzero(offsets)",
        "requires try_offsets_are_nondecreasing(offsets)",
        "invariant forall prior in TRY_ENCLOSING_FIRST_POSITION..<low: offsets[prior] <= query",
        "invariant forall later in high..<offsets.count: offsets[later] > query",
        "if offsets[middle] <= query:",
        "low <- middle + TRY_ENCLOSING_POSITION_STEP",
        "high <- middle",
        "return (true, low - TRY_ENCLOSING_POSITION_STEP)",
        "return (false, TRY_ENCLOSING_FIRST_POSITION)",
    ),
    "last_predecessor_results_are_unique": (
        "requires try_predecessor_is_last(offsets, query, left_found, left_index)",
        "requires try_predecessor_is_last(offsets, query, right_found, right_index)",
        "ensure left_found == right_found and left_index == right_index",
        "left_found == right_found and left_index == right_index",
    ),
    "sorted_binary_predecessor_equals_linear_reference": (
        "ensure try_binary_predecessor(offsets, query) == try_linear_predecessor(offsets, query)",
        "linear: (found: bool, index: usize) = try_linear_predecessor(offsets, query)",
        "indexed: (found: bool, index: usize) = try_binary_predecessor(offsets, query)",
        "return last_predecessor_results_are_unique(offsets, query, linear.found, linear.index, indexed.found, indexed.index)",
    ),
    "duplicate_offsets_select_the_last_qualifying_position": (
        "indexed.index == TRY_ENCLOSING_SECOND_POSITION",
    ),
    "try_offsets_are_nonzero": (
        "forall position in TRY_ENCLOSING_FIRST_POSITION..<offsets.count",
        "offsets[position] != TRY_ENCLOSING_NO_OFFSET",
    ),
    "try_offsets_are_nondecreasing": (
        "forall left in TRY_ENCLOSING_FIRST_POSITION..<offsets.count",
        "forall right in left..<offsets.count: offsets[left] <= offsets[right]",
    ),
    "sorted_binary_predecessor_preserves_parallel_line_mapping": (
        "requires offsets.count == lines.count",
        "requires try_offsets_are_nonzero(offsets)",
        "requires try_offsets_are_nondecreasing(offsets)",
        "indexed == linear and lines[indexed.index] == lines[linear.index] and offsets[indexed.index] == offsets[linear.index]",
    ),
    "empty_index_reports_no_predecessor": (
        "offsets: darray[u32] = []",
        "not indexed.found and indexed.index == TRY_ENCLOSING_FIRST_POSITION",
    ),
    "sorted_index_without_a_predecessor_reports_fallback_case": (
        "requires try_offsets_are_nonzero(offsets)",
        "requires try_offsets_are_nondecreasing(offsets)",
        "offsets.count == TRY_ENCLOSING_FIRST_POSITION or offsets[TRY_ENCLOSING_FIRST_POSITION] > query",
        "not indexed.found and indexed.index == TRY_ENCLOSING_FIRST_POSITION and indexed == linear",
    ),
}
for name, fragments in positive_shapes.items():
    body = compact_inline(function_section(positive_text, name))
    if any(compact_inline(fragment) not in body for fragment in fragments):
        raise SystemExit(f"positive predecessor theorem changed its stated contract or algorithm: {name}")
for name in NEGATIVE_NAMES:
    if f"def {name}(" not in negative_text:
        raise SystemExit(f"negative predecessor control missing: {name}")
negative_shapes = {
    "false_claim_duplicate_offsets_select_the_first_position": "indexed.index == TRY_ENCLOSING_FIRST_POSITION",
    "false_claim_duplicate_offsets_keep_the_first_line": "lines[indexed.index] == lines[TRY_ENCLOSING_FIRST_POSITION]",
    "false_claim_empty_index_has_a_predecessor": "return indexed.found",
    "false_claim_no_predecessor_has_a_position": "return indexed.found",
}
for name, fragment in negative_shapes.items():
    if compact_inline(fragment) not in compact_inline(function_section(negative_text, name)):
        raise SystemExit(f"negative predecessor control no longer states its counterclaim: {name}")
for raw_value in ("middle: usize = low + (high - low) / 2", "low <- middle + 1", "low - 1"):
    if raw_value in positive_text:
        raise SystemExit(f"proof model contains a raw position-search value: {raw_value}")

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
    SOURCE,
    SEMANTIC,
    PIPELINE,
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
