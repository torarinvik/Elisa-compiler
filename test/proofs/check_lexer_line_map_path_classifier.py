"""Admit source-linked guard and prefix-bound proofs for runtime-stdlib paths."""
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
LEXER = ROOT / "src/lexer/lexer.elisa"
CACHE = ROOT / "src/lexer/lexer_line_map_cache.elisa"
MODEL = HERE / "lexer_line_map_path_classifier_model.elisa"
POSITIVE = HERE / "lexer_line_map_path_classifier.elisa"
BOUNDS = HERE / "lexer_line_map_path_component_bounds.elisa"
NEGATIVE = HERE / "lexer_line_map_path_classifier_rejected.elisa"
CACHE_PREFILTER = HERE / "lexer_line_map_path_cache_prefilter.elisa"
CACHE_PREFILTER_NEGATIVE = HERE / "lexer_line_map_path_cache_prefilter_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():])
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    text = compact(body)
    positions = [text.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} no longer follows the classifier model")


lexer_text = LEXER.read_text()
cache_text = CACHE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
model_text = MODEL.read_text()
bounds_text = BOUNDS.read_text()
cache_prefilter_text = CACHE_PREFILTER.read_text()
cache_prefilter_negative_text = CACHE_PREFILTER_NEGATIVE.read_text()

classifier = function_section(lexer_text, "source_line_map_path_is_runtime_std")
require_ordered(classifier, (
    "static if ELISA_TARGET_OS_WINDOWS: return false",
    "static else: static if ELISA_TARGET_OS_WASM: return false",
    "static else: false return if path_stop <= path_start or path_stop - path_start > 8191.usize()",
    "false return if not source_line_map_path_has_runtime_std_component(map_storage, path_start, path_stop)",
    "false return if lexer_realpath(path_cstr, realpath_buffer_ref) is null",
    "while resolved_length < realpath_buffer.count",
    "break if realpath_buffer[resolved_length] == 0",
    "false return if resolved_length == realpath_buffer.count or resolved_length <= trusted_prefix.count",
    "for prefix_index in 0..<trusted_prefix.count",
    "false return if realpath_buffer[prefix_index] != trusted_prefix[prefix_index]",
    "return true",
), "runtime-stdlib path classifier")
classifier_compact = compact(classifier)
if (classifier_compact.count("returnfalse") != 2 or
        classifier_compact.count("falsereturnif") != 5 or
        classifier_compact.count("returntrue") != 1):
    raise SystemExit("runtime-stdlib classifier gained or lost a result branch; extend its model")

component = function_section(lexer_text, "source_line_map_path_has_runtime_std_component")
require_ordered(component, (
    "false return if path_stop <= path_start",
    'marker: sview = "elisacore_std/"',
    "marker_length: usize = sview_len(marker)",
    "marker_start: mutable usize = path_start",
    "while marker_start <= path_stop and path_stop - marker_start >= marker_length",
    "matched: mutable bool = true",
    "for marker_offset in 0..<marker_length",
    "matched <- false if map_storage[marker_start + marker_offset] != sview_at(marker, marker_offset)",
    "true return if matched and marker_start > path_start and map_storage[marker_start - 1.usize()] == SOURCE_LINE_MAP_PATH_SEPARATOR",
    "marker_start <- marker_start + 1.usize()",
    "return false",
), "stdlib component prefilter")
component_compact = compact(component)
if (component_compact.count("matched:mutablebool=true") != 1 or
        component_compact.count("matched<-falseifmap_storage[marker_start+marker_offset]!=sview_at(marker,marker_offset)") != 1 or
        component_compact.count("marker_start<-marker_start+1.usize()") != 1 or
        component_compact.count("truereturnifmatchedandmarker_start>path_startandmap_storage[marker_start-1.usize()]==SOURCE_LINE_MAP_PATH_SEPARATOR") != 1 or
        component_compact.count("truereturn") != 1 or
        "matched<-true" in component_compact):
    raise SystemExit("component prefilter no longer models a complete, monotone marker-byte scan")
production_markers = re.findall(r'(?m)^\s*marker: sview = "([^"]*)"\s*$', component)
if len(production_markers) != 1 or production_markers[0] != "elisacore_std/":
    raise SystemExit("component marker spelling changed without reviewing its proof")
marker_bytes = tuple(production_markers[0].encode("ascii"))
if len(marker_bytes) != 14:
    raise SystemExit("component marker length changed without reviewing its scalar-byte proof")

root = function_section(lexer_text, "source_runtime_std_root_prefix")
require_ordered(root, (
    'trusted_suffix: sview = "/elisacore_std/"',
    "prefix.truncate(0)",
    "prefix.push(SOURCE_LINE_MAP_PATH_SEPARATOR)",
    "return prefix.count > 0.usize()",
), "trusted root prefix construction")

direct_caller = function_section(lexer_text, "source_line_is_runtime_std_from_map")
if compact("false return if not source_runtime_std_root_prefix(&trusted_prefix)") not in compact(direct_caller):
    raise SystemExit("direct classifier caller no longer requires a valid trusted root")
if "realpath_buffer.resize(8192.usize())" not in compact(direct_caller):
    raise SystemExit("direct classifier caller changed the realpath buffer capacity")

cache_builder = function_section(cache_text, "line_map_cache_build")
if compact("_ = source_runtime_std_root_prefix(&trusted_prefix)") not in compact(cache_builder):
    raise SystemExit("cached classifier caller no longer builds the trusted root")
if "realpath_buffer.resize(8192.usize())" not in compact(cache_builder):
    raise SystemExit("cached classifier caller changed the realpath buffer capacity")
if compact("trusted_prefix.count > 0.usize()") not in compact(cache_builder):
    raise SystemExit("cached classifier caller no longer requires a nonempty trusted root")
require_ordered(cache_builder, (
    "path_start: usize = scan + 1.usize()",
    "path_stop: usize = entry_stop",
    "if trusted_prefix.count > 0.usize() and path_start < path_stop and path_stop - path_start <= 8191.usize() and source_line_map_path_has_runtime_std_component(map_storage, path_start, path_stop):",
    "path_hash: u64 = line_map_cache_path_hash(map_storage, path_start, path_stop)",
), "bounded cache component prefilter")

if "const SOURCE_LINE_MAP_PATH_LIMIT_MODEL: i64 = 8191" not in model_text:
    raise SystemExit("path-span model changed without reviewing the production bound")
if "const SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL: i64 = 8192" not in model_text:
    raise SystemExit("realpath-capacity model changed without reviewing its callers")
for fragment in (
    "path_length <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL",
    "resolved_length < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL",
    "resolved_length > trusted_prefix_length",
    "prefix_bytes_equal",
):
    if compact(fragment) not in compact(function_section(model_text, "classifier_accepts_exactly_the_guard_conjunction")):
        raise SystemExit(f"classifier model is missing production guard {fragment}")

model_names = {
    "classifier_accepts_exactly_the_guard_conjunction",
    "classifier_accepts_the_maximum_source_span",
    "classifier_accepts_a_strict_child_of_the_trusted_prefix",
    "maximum_accepted_prefix_still_has_room_for_a_child_byte",
    "accepted_prefix_scan_index_is_inside_both_spans",
    "accepted_resolved_path_has_a_strict_extension_byte",
    "component_candidate_matches_exact_runtime_marker",
}
positive_case_names = {
    "a_full_marker_with_exact_bytes_after_separator_is_a_component",
    "a_marker_with_one_mismatched_byte_is_rejected",
    "a_marker_at_the_path_start_is_rejected",
    "a_marker_without_a_preceding_separator_is_rejected",
}
bound_names = {
    "component_candidate_offset_is_inside_path_span",
    "component_preceding_byte_is_inside_path_span",
    "component_scan_step_advances_inside_path_span",
    "component_scan_includes_the_exact_fit_candidate",
}
negative_names = {
    "false_accepts_a_source_span_one_byte_too_long",
    "false_accepts_the_trusted_root_itself",
    "false_accepts_a_resolved_path_shorter_than_the_trusted_root",
    "false_accepts_a_prefix_byte_mismatch",
    "false_accepts_a_failed_realpath",
    "false_accepts_a_path_without_the_std_component",
    "false_accepts_an_unsupported_platform",
    "false_accepts_a_realpath_buffer_without_a_terminator",
    "false_accepts_a_marker_with_a_mismatched_byte",
    "false_accepts_a_marker_at_the_path_start",
    "false_accepts_a_marker_without_a_preceding_separator",
}
cache_prefilter_names = {
    "cache_prefilter_accepts_exactly_a_nonempty_bounded_span",
    "cache_prefilter_accepts_the_maximum_classifier_span",
}
cache_prefilter_negative_names = {
    "false_accepts_a_cache_prefilter_span_one_byte_too_long",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


positive_names = model_names | positive_case_names
if (declarations(MODEL) != model_names or
        declarations(POSITIVE) != positive_case_names or
        declarations(BOUNDS) != bound_names or
        declarations(NEGATIVE) != negative_names or
        declarations(CACHE_PREFILTER) != cache_prefilter_names or
        declarations(CACHE_PREFILTER_NEGATIVE) != cache_prefilter_negative_names):
    raise SystemExit("runtime-stdlib classifier proof inventory changed")
model_include = 'include "./lexer_line_map_path_classifier_model.elisa"'
if model_include not in positive_text or model_include not in negative_text or model_include not in bounds_text:
    raise SystemExit("positive and negative claims must share the same classifier model")
if model_include not in cache_prefilter_text or 'include "./lexer_line_map_path_cache_prefilter.elisa"' not in cache_prefilter_negative_text:
    raise SystemExit("cache-prefilter controls no longer reuse their proved classifier model")

marker_params = ", ".join(f"byte{index}: u8" for index in range(len(marker_bytes)))
marker_equalities = " and ".join(
    f"byte{index} == {byte}" for index, byte in enumerate(marker_bytes)
)
component_parameters = marker_params + ", starts_after_path_start: bool, preceding_byte_is_separator: bool"
component_predicate = (
    f"({marker_equalities} and starts_after_path_start and preceding_byte_is_separator)"
)
component_return = " and ".join((marker_equalities, "starts_after_path_start", "preceding_byte_is_separator"))

def component_call(byte_values=marker_bytes, starts=True, separator=True):
    arguments = [str(value) for value in byte_values]
    arguments.extend(("true" if starts else "false", "true" if separator else "false"))
    return "component_candidate_matches_exact_runtime_marker(" + ", ".join(arguments) + ")"

def component_case(name, expected, byte_values=marker_bytes, starts=True, separator=True):
    return f"""def {name}() -> bool:
        ensure result == {expected}
        return {component_call(byte_values, starts, separator)}"""

component_shapes = {
    "component_candidate_matches_exact_runtime_marker": f"""def component_candidate_matches_exact_runtime_marker({component_parameters}) -> bool:
        ensure result == {component_predicate}
        return {component_return}""",
    "a_full_marker_with_exact_bytes_after_separator_is_a_component": component_case(
        "a_full_marker_with_exact_bytes_after_separator_is_a_component", "true"),
    "a_marker_with_one_mismatched_byte_is_rejected": component_case(
        "a_marker_with_one_mismatched_byte_is_rejected", "false", marker_bytes[:-1] + (46,)),
    "a_marker_at_the_path_start_is_rejected": component_case(
        "a_marker_at_the_path_start_is_rejected", "false", starts=False),
    "a_marker_without_a_preceding_separator_is_rejected": component_case(
        "a_marker_without_a_preceding_separator_is_rejected", "false", separator=False),
    "false_accepts_a_marker_with_a_mismatched_byte": component_case(
        "false_accepts_a_marker_with_a_mismatched_byte", "true", marker_bytes[:-1] + (46,)),
    "false_accepts_a_marker_at_the_path_start": component_case(
        "false_accepts_a_marker_at_the_path_start", "true", starts=False),
    "false_accepts_a_marker_without_a_preceding_separator": component_case(
        "false_accepts_a_marker_without_a_preceding_separator", "true", separator=False),
}
bound_shapes = {
    "component_candidate_offset_is_inside_path_span": """def component_candidate_offset_is_inside_path_span(path_span: i64, candidate_offset: i64, marker_offset: i64) -> bool:
        requires path_span >= 14 and path_span <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and candidate_offset >= 0 and candidate_offset <= path_span - 14 and marker_offset >= 0 and marker_offset < 14
        ensure result == true
        return candidate_offset + marker_offset < path_span""",
    "component_preceding_byte_is_inside_path_span": """def component_preceding_byte_is_inside_path_span(path_span: i64, candidate_offset: i64) -> bool:
        requires path_span > 0 and path_span <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and candidate_offset > 0 and candidate_offset < path_span
        ensure result == true
        return candidate_offset - 1 >= 0 and candidate_offset - 1 < path_span""",
    "component_scan_step_advances_inside_path_span": """def component_scan_step_advances_inside_path_span(path_span: i64, candidate_offset: i64) -> bool:
        requires path_span >= 14 and path_span <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and candidate_offset >= 0 and candidate_offset <= path_span - 14
        ensure result == true
        return candidate_offset < candidate_offset + 1 and candidate_offset + 1 <= path_span""",
    "component_scan_includes_the_exact_fit_candidate": """def component_scan_includes_the_exact_fit_candidate(path_span: i64, candidate_offset: i64) -> bool:
        requires path_span >= 14 and path_span <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and candidate_offset == path_span - 14
        ensure result == true
        return candidate_offset + 14 == path_span""",
}
cache_prefilter_shapes = {
    "cache_prefilter_accepts_exactly_a_nonempty_bounded_span": """def cache_prefilter_accepts_exactly_a_nonempty_bounded_span(trusted_root_nonempty: bool, path_length: i64) -> bool:
        requires path_length >= 0 and path_length <= SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL
        ensure result == (trusted_root_nonempty and path_length > 0 and path_length <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL)
        return trusted_root_nonempty and path_length > 0 and path_length <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL""",
    "cache_prefilter_accepts_the_maximum_classifier_span": """def cache_prefilter_accepts_the_maximum_classifier_span() -> bool:
        ensure result == true
        return true and 8191 > 0 and 8191 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL""",
    "false_accepts_a_cache_prefilter_span_one_byte_too_long": """def false_accepts_a_cache_prefilter_span_one_byte_too_long() -> bool:
        ensure result == true
        return true and 8192 > 0 and 8192 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL""",
}

expected_shapes = {
    "classifier_accepts_exactly_the_guard_conjunction": """def classifier_accepts_exactly_the_guard_conjunction(supported_platform: bool, path_length: i64, has_runtime_std_component: bool, realpath_succeeded: bool, resolved_length: i64, trusted_prefix_length: i64, prefix_bytes_equal: bool) -> bool:
        requires path_length >= 0 and resolved_length >= 0 and resolved_length <= SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and trusted_prefix_length > 0
        ensure result == (supported_platform and path_length > 0 and path_length <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and has_runtime_std_component and realpath_succeeded and resolved_length < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and resolved_length > trusted_prefix_length and prefix_bytes_equal)
        return supported_platform and path_length > 0 and path_length <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and has_runtime_std_component and realpath_succeeded and resolved_length < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and resolved_length > trusted_prefix_length and prefix_bytes_equal""",
    "classifier_accepts_the_maximum_source_span": """def classifier_accepts_the_maximum_source_span() -> bool:
        ensure result == true
        return true and 8191 > 0 and 8191 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and true and true and 15 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 15 > 14 and true""",
    "classifier_accepts_a_strict_child_of_the_trusted_prefix": """def classifier_accepts_a_strict_child_of_the_trusted_prefix() -> bool:
        ensure result == true
        return true and 15 > 0 and 15 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and true and true and 15 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 15 > 14 and true""",
    "maximum_accepted_prefix_still_has_room_for_a_child_byte": """def maximum_accepted_prefix_still_has_room_for_a_child_byte() -> bool:
        ensure result == true
        return 8190 < 8191 and 8191 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 8191 > 8190""",
    "accepted_prefix_scan_index_is_inside_both_spans": """def accepted_prefix_scan_index_is_inside_both_spans(resolved_length: i64, trusted_prefix_length: i64, prefix_index: i64) -> bool:
        requires resolved_length >= 0 and resolved_length < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and resolved_length > trusted_prefix_length and trusted_prefix_length > 0 and prefix_index >= 0 and prefix_index < trusted_prefix_length
        ensure result == true
        return prefix_index < resolved_length and prefix_index < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and prefix_index < trusted_prefix_length""",
    "accepted_resolved_path_has_a_strict_extension_byte": """def accepted_resolved_path_has_a_strict_extension_byte(resolved_length: i64, trusted_prefix_length: i64) -> bool:
        requires resolved_length > trusted_prefix_length and trusted_prefix_length > 0
        ensure result == true
        return resolved_length - trusted_prefix_length >= 1""",
    "false_accepts_a_source_span_one_byte_too_long": """def false_accepts_a_source_span_one_byte_too_long() -> bool:
        ensure result == true
        return true and 8192 > 0 and 8192 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and true and true and 15 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 15 > 14 and true""",
    "false_accepts_the_trusted_root_itself": """def false_accepts_the_trusted_root_itself() -> bool:
        ensure result == true
        return true and 1 > 0 and 1 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and true and true and 14 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 14 > 14 and true""",
    "false_accepts_a_resolved_path_shorter_than_the_trusted_root": """def false_accepts_a_resolved_path_shorter_than_the_trusted_root() -> bool:
        ensure result == true
        return true and 1 > 0 and 1 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and true and true and 13 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 13 > 14 and true""",
    "false_accepts_a_prefix_byte_mismatch": """def false_accepts_a_prefix_byte_mismatch() -> bool:
        ensure result == true
        return true and 1 > 0 and 1 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and true and true and 15 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 15 > 14 and false""",
    "false_accepts_a_failed_realpath": """def false_accepts_a_failed_realpath() -> bool:
        ensure result == true
        return true and 1 > 0 and 1 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and true and false and 15 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 15 > 14 and true""",
    "false_accepts_a_path_without_the_std_component": """def false_accepts_a_path_without_the_std_component() -> bool:
        ensure result == true
        return true and 1 > 0 and 1 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and false and true and 15 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 15 > 14 and true""",
    "false_accepts_an_unsupported_platform": """def false_accepts_an_unsupported_platform() -> bool:
        ensure result == true
        return false and 1 > 0 and 1 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and true and true and 15 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 15 > 14 and true""",
    "false_accepts_a_realpath_buffer_without_a_terminator": """def false_accepts_a_realpath_buffer_without_a_terminator() -> bool:
        ensure result == true
        return true and 1 > 0 and 1 <= SOURCE_LINE_MAP_PATH_LIMIT_MODEL and true and true and 8192 < SOURCE_LINE_MAP_REALPATH_CAPACITY_MODEL and 8192 > 14 and true""",
    **component_shapes,
    **bound_shapes,
    **cache_prefilter_shapes,
}
for name, expected in expected_shapes.items():
    proof_text = (model_text if name in model_names else
                  positive_text if name in positive_case_names else
                  bounds_text if name in bound_names else
                  cache_prefilter_text if name in cache_prefilter_names else
                  cache_prefilter_negative_text if name in cache_prefilter_negative_names else negative_text)
    if compact(function_section(proof_text, name)) != compact(expected):
        raise SystemExit(f"{name} no longer checks the intended classifier condition")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("path-classifier proofs require a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
          PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
          Path(__file__), HERE / "proof_product_gate.py", LEXER, CACHE, MODEL, POSITIVE, BOUNDS,
          NEGATIVE, CACHE_PREFILTER, CACHE_PREFILTER_NEGATIVE]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["replay"]["replayed"] >= report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(model_names) + len(positive_case_names) + 2
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert {item["name"] for item in positive["declaration_details"] if item.get("verified")} == positive_names
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "positive classifier proof report changed across replays"

code, bounds = run(BOUNDS)
assert code == 0 and bounds["status"] == bounds["verification_state"] == "proved"
assert bounds["summary"]["declarations"] == len(model_names) + len(bound_names) + 2
assert bounds["summary"]["obligations"] == bounds["summary"]["proven"]
assert {item["name"] for item in bounds["declaration_details"] if item.get("verified")} == model_names | bound_names
assert not bounds["findings"]
assert bounds == run(BOUNDS)[1], "component-bound proof report changed across replays"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(model_names) + len(negative_names) + 2
assert negative["summary"]["obligations"] == negative["summary"]["proven"] + len(negative_names)
assert {finding["name"] for finding in negative["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" and finding["status"] == "unknown"
           for finding in negative["findings"])
negative_verified = {item["name"] for item in negative["declaration_details"] if item.get("verified")}
assert model_names <= negative_verified
assert not negative_names & negative_verified
assert negative == run(NEGATIVE)[1], "false classifier controls changed across replays"

code, cache_prefilter = run(CACHE_PREFILTER)
assert code == 0 and cache_prefilter["status"] == cache_prefilter["verification_state"] == "proved"
assert cache_prefilter["summary"]["declarations"] == len(model_names) + len(cache_prefilter_names) + 2
assert cache_prefilter["summary"]["obligations"] == cache_prefilter["summary"]["proven"]
assert {item["name"] for item in cache_prefilter["declaration_details"] if item.get("verified")} == model_names | cache_prefilter_names
assert not cache_prefilter["findings"]
assert cache_prefilter == run(CACHE_PREFILTER)[1], "cache-prefilter proof report changed across replays"

code, cache_prefilter_negative = run(CACHE_PREFILTER_NEGATIVE)
assert code == 1 and cache_prefilter_negative["status"] == "failed"
assert cache_prefilter_negative["summary"]["declarations"] == len(model_names) + len(cache_prefilter_names) + len(cache_prefilter_negative_names) + 2
assert cache_prefilter_negative["summary"]["obligations"] == cache_prefilter_negative["summary"]["proven"] + len(cache_prefilter_negative_names)
assert {finding["name"] for finding in cache_prefilter_negative["findings"]} == cache_prefilter_negative_names
assert all(finding["kind"] == "ensure-unproven" and finding["status"] == "unknown"
           for finding in cache_prefilter_negative["findings"])
assert cache_prefilter_negative == run(CACHE_PREFILTER_NEGATIVE)[1], "oversized cache-prefilter control changed across replays"

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({"admitted": True,
                  "scope": "runtime-stdlib classifier guards, exact component matching, component scan bounds, strict-prefix extension, and prefix-index bounds",
                  "positive_obligations": positive["summary"]["proven"],
                  "component_bound_obligations": bounds["summary"]["proven"],
                  "cache_prefilter_obligations": cache_prefilter["summary"]["proven"],
                  "false_claims_refused": sorted(negative_names),
                  "cache_prefilter_false_claims_refused": sorted(cache_prefilter_negative_names),
                  "proof_revision": product["proof"].get("head"),
                  "compiler_revision": compiler.get("source_revision"),
                  "source_sha256": hashes_before}, sort_keys=True))
