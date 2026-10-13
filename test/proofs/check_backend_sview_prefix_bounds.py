"""Source-bind bounds proofs for the backend StringView prefix comparator."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
PREFIX_SOURCE = ROOT / "src/backend/codegen_variant_paths.elisa"
PACKED_META = ROOT / "src/backend/codegen_packed_meta.elisa"
CODEGEN = ROOT / "src/backend/codegen.elisa"
RUNTIME_STRINGS = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
SPEC = HERE / "backend_sview_prefix_bounds_spec.elisa"
POSITIVE = HERE / "backend_sview_prefix_bounds.elisa"
NEGATIVE = HERE / "backend_sview_prefix_bounds_rejected.elisa"
POSITIVE_NAMES = {
    "a_valid_prefix_range_is_admitted",
    "production_loop_accumulator_matches_the_bytewise_prefix_spec",
    "every_candidate_byte_offset_stays_inside_the_path",
    "production_loop_counter_casts_to_the_same_bounded_byte_index",
}
NEGATIVE_NAMES = {
    "false_claim_accepts_a_differing_candidate_byte",
    "false_claim_accepts_an_end_past_the_path",
    "false_claim_accepts_an_unrepresentable_path_length",
    "false_claim_accepts_an_unrepresentable_candidate_length",
    "false_claim_accepts_a_negative_path_length",
    "false_claim_accepts_a_negative_candidate_length",
    "false_claim_accepts_a_negative_start",
    "false_claim_accepts_a_reversed_range",
    "false_claim_accepts_a_slice_with_the_wrong_length",
}

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")


def strip_elisa_line_comment(line: str) -> str:
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


def compact_code(text: str) -> tuple[str, ...]:
    code_lines = []
    for line in text.splitlines():
        uncommented = strip_elisa_line_comment(line)
        if uncommented.strip():
            expanded = uncommented.expandtabs(4)
            indent = len(expanded) - len(expanded.lstrip())
            code_lines.append((indent, normalize_code_line(expanded.lstrip())))
    if not code_lines:
        return ()
    base_indent = min(indent for indent, _ in code_lines)
    return tuple(" " * (indent - base_indent) + code for indent, code in code_lines)


def include_targets(text: str) -> list[str]:
    targets = []
    for line in text.splitlines():
        directive = strip_elisa_line_comment(line).strip()
        match = re.fullmatch(r'include\s+"([^"\n]+)"', directive)
        if match:
            targets.append(match.group(1))
    return targets


if compact_code("return index") == compact_code("returnindex"):
    raise SystemExit("source normalizer collapses a token boundary")
if compact_code("if test:\n    return 1\nreturn 2") == compact_code("if test:\nreturn 1\nreturn 2"):
    raise SystemExit("source normalizer discards indentation-sensitive structure")
if include_targets('# include "./codegen_variant_paths.elisa"\ninclude "./actual.elisa" # comment') != ["./actual.elisa"]:
    raise SystemExit("include parser accepts a comment as an active directive")


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


def operational_shape(function: str) -> tuple[str, ...]:
    code = "\n".join(
        line for line in function.splitlines()
        if not line.lstrip().startswith(("ensure ", "invariant ", "decreases "))
    )
    return compact_code(code)


source_text = PREFIX_SOURCE.read_text()
expected_prefix = """
def sview_matches_prefix(path: sview, candidate: sview, start: i64, end: i64) -> bool can[Abort.Panic]:
    path_length: usize = path.len
    candidate_length: usize = candidate.len
    false return if path.len < 0 or candidate.len < 0
    false return if path_length.i64() != path.len or candidate_length.i64() != candidate.len
    false return if start < 0 or end < start or end > path.len
    false return if end - start != candidate.len
    matched: mutable bool = true
    for index in 0..<candidate_length |matched, path, candidate, start|:
        matched <- false if path[(start + index.i64()).usize()] != candidate[index]
    return matched
"""
if compact_code(function_section(source_text, "sview_matches_prefix")) != compact_code(expected_prefix):
    raise SystemExit("production prefix comparator lost its view-length, slice, or per-byte bounds guards")

runtime_text = RUNTIME_STRINGS.read_text()
expected_sview_len = """
def sview_len(view: sview) -> usize:
    0.usize() return if view.len <= 0
    view_len: usize = view.len.usize()
    return 0.usize() if view_len.i64() != view.len
    return view_len
"""
if compact_code(function_section(runtime_text, "sview_len")) != compact_code(expected_sview_len):
    raise SystemExit("prefix view-fit guard no longer matches the source StringView length conversion")
expected_sview_at = """
def sview_at(view: sview, index: usize) -> u8:
    can Unsafe.UncheckedIndex:
        return string_view_index(view, index.i64()).u8()
"""
if compact_code(function_section(runtime_text, "sview_at")) != compact_code(expected_sview_at):
    raise SystemExit("prefix comparator no longer uses the source-bound checked byte reader")
expected_string_view_index = """
def string_view_index(view: sview, index: i64) -> i64:
    can Unsafe.UncheckedIndex:
        0 return if view.len < 0
        view_len: usize = view.len.usize()
        0 return if view_len.i64() != view.len
        0 return if index < 0 or index >= view.len
        index_usize: usize = index.usize()
        0 return if index_usize.i64() != index
        return view.data[index_usize].i64()
"""
if compact_code(function_section(runtime_text, "string_view_index")) != compact_code(expected_string_view_index):
    raise SystemExit("checked StringView byte reader changed without updating its prefix bounds proof")

packed_includes = include_targets(PACKED_META.read_text())
codegen_includes = include_targets(CODEGEN.read_text())
if packed_includes.count("./codegen_variant_paths.elisa") != 1 or \
        codegen_includes.count("./codegen_packed_meta.elisa") != 1:
    raise SystemExit("source-bound prefix comparator is no longer included in the production backend")

spec_text = SPEC.read_text()
storage_assumption = "assumes each nonnegative sview length describes valid backing storage."
if storage_assumption not in spec_text:
    raise SystemExit("proof-only prefix bounds model must state its backing-storage assumption")
expected_spec = """
def prefix_range_is_valid(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    ensure result implies (path_length >= 0 and candidate_length >= 0 and path_length_usize.i64() == path_length and candidate_length_usize.i64() == candidate_length and start >= 0 and end >= start and end <= path_length and end - start == candidate_length)
    ensure (path_length >= 0 and candidate_length >= 0 and path_length_usize.i64() == path_length and candidate_length_usize.i64() == candidate_length and start >= 0 and end >= start and end <= path_length and end - start == candidate_length) implies result
    false return if path_length < 0 or candidate_length < 0
    false return if path_length_usize.i64() != path_length or candidate_length_usize.i64() != candidate_length
    false return if start < 0
    false return if end < start or end > path_length
    return end - start == candidate_length
"""
if compact_code(function_section(spec_text, "prefix_range_is_valid")) != compact_code(expected_spec):
    raise SystemExit("proof-only prefix range model changed without updating its proof gate")
expected_bytewise_spec = """
def every_candidate_byte_matches(path: sview, candidate: sview, start: i64, candidate_length: usize) -> bool:
    return forall index in 0..<candidate_length: path[(start + index.i64()).usize()] == candidate[index]
"""
if compact_code(function_section(spec_text, "every_candidate_byte_matches")) != compact_code(expected_bytewise_spec):
    raise SystemExit("proof-only bytewise prefix specification changed without updating its proof gate")

def section_without_contracts(source: str, name: str) -> tuple[str, ...]:
    return operational_shape(function_section(source, name))

guard_prefix = """
def sview_matches_prefix(path: sview, candidate: sview, start: i64, end: i64) -> bool can[Abort.Panic]:
    path_length: usize = path.len
    candidate_length: usize = candidate.len
    false return if path.len < 0 or candidate.len < 0
    false return if path_length.i64() != path.len or candidate_length.i64() != candidate.len
    false return if start < 0 or end < start or end > path.len
    false return if end - start != candidate.len
"""
if section_without_contracts(source_text, "sview_matches_prefix")[:7] != compact_code(guard_prefix):
    raise SystemExit("production prefix byte loop is not dominated by the proof-bound guard sequence")

for path, expected in ((POSITIVE, POSITIVE_NAMES), (NEGATIVE, NEGATIVE_NAMES)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "./backend_sview_prefix_bounds_spec.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} must include the proof-only prefix bounds model")

semantic_model = function_section(
    POSITIVE.read_text(), "production_loop_accumulator_matches_the_bytewise_prefix_spec"
)
production_loop = re.search(
    r"(?m)^\s*for index in 0\.\.<(\w+) \|([^|]+)\|:",
    function_section(source_text, "sview_matches_prefix"),
)
model_loop = re.search(
    r"(?m)^\s*while index < (\w+) \|([^|]+)\|:", semantic_model
)
if production_loop is None or model_loop is None:
    raise SystemExit("production comparator and bytewise proof must each expose their loop shape")
if production_loop.group(1) != "candidate_length" or \
        model_loop.group(1) != "candidate_length_usize" or \
        [item.strip() for item in production_loop.group(2).split(",")] != ["matched", "path", "candidate", "start"] or \
        [item.strip() for item in model_loop.group(2).split(",")] != ["index", "matched", "path", "candidate", "start"]:
    raise SystemExit("bytewise proof loop no longer models the production bound and carried state")

production_length = re.search(
    r"(?m)^\s*candidate_length: usize = (.+)$",
    function_section(source_text, "sview_matches_prefix"),
)
model_length = re.search(
    r"(?m)^\s*candidate_length_usize: usize = (.+)$", semantic_model
)
if production_length is None or model_length is None or \
        production_length.group(1) != model_length.group(1) or \
        production_length.group(1) != "candidate.len":
    raise SystemExit("bytewise proof loop bound is not derived from the production StringView length helper")

def accumulator_update(function: str) -> tuple[str, ...]:
    updates = [line for line in function.splitlines() if "matched <- false if " in line]
    if len(updates) != 1:
        raise SystemExit("production comparator and bytewise proof must each have one accumulator update")
    return compact_code(updates[0])

if accumulator_update(function_section(source_text, "sview_matches_prefix")) != \
        accumulator_update(semantic_model):
    raise SystemExit("bytewise proof accumulator update diverged from the production comparator")

positive_shapes = {
    "a_valid_prefix_range_is_admitted": """
def a_valid_prefix_range_is_admitted(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    requires path_length >= 0 and candidate_length >= 0
    requires path_length_usize.i64() == path_length and candidate_length_usize.i64() == candidate_length
    requires start >= 0 and end >= start and end <= path_length
    requires end - start == candidate_length
    ensure result == true
    return BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
""",
    "production_loop_accumulator_matches_the_bytewise_prefix_spec": """
def production_loop_accumulator_matches_the_bytewise_prefix_spec(path: sview, candidate: sview, start: i64, end: i64) -> bool:
    requires BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path.len, candidate.len, start, end, path.len, candidate.len)
    ensure result == BackendSviewPrefixBoundsSpec::every_candidate_byte_matches(path, candidate, start, candidate.len)
    candidate_length_usize: usize = candidate.len
    index: mutable usize = 0
    matched: mutable bool = true
    while index < candidate_length_usize |index, matched, path, candidate, start|:
        decreases candidate_length_usize - index
        invariant index <= candidate_length_usize
        invariant matched == (forall prior in 0..<index: path[(start + prior.i64()).usize()] == candidate[prior])
        matched <- false if path[(start + index.i64()).usize()] != candidate[index]
        index <- index + 1
    return matched
""",
    "every_candidate_byte_offset_stays_inside_the_path": """
def every_candidate_byte_offset_stays_inside_the_path(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize, byte_index: i64) -> bool:
    requires BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
    requires byte_index >= 0 and byte_index < candidate_length
    ensure result == true
    return start + byte_index >= start and start + byte_index < end and end <= path_length
""",
    "production_loop_counter_casts_to_the_same_bounded_byte_index": """
def production_loop_counter_casts_to_the_same_bounded_byte_index(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize, loop_index: usize) -> bool:
    requires BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
    requires loop_index < candidate_length_usize
    ensure result == true
    return (
        loop_index.i64() >= 0
        and loop_index.i64().usize() == loop_index
        and start + loop_index.i64() >= start
        and start + loop_index.i64() < end
        and (start + loop_index.i64()).usize().i64() == start + loop_index.i64()
        and end <= path_length
    )
""",
}
negative_shapes = {
    "false_claim_accepts_a_differing_candidate_byte": """
def false_claim_accepts_a_differing_candidate_byte(path: sview, candidate: sview, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize, mismatch_index: usize) -> bool:
    requires BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path.len, candidate.len, start, end, path_length_usize, candidate_length_usize)
    requires mismatch_index < candidate_length_usize
    requires path[(start + mismatch_index.i64()).usize()] != candidate[mismatch_index]
    ensure result == true
    return BackendSviewPrefixBoundsSpec::every_candidate_byte_matches(path, candidate, start, candidate_length_usize)
""",
    "false_claim_accepts_an_end_past_the_path": """
def false_claim_accepts_an_end_past_the_path(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    requires path_length >= 0 and candidate_length >= 0
    requires path_length_usize.i64() == path_length and candidate_length_usize.i64() == candidate_length
    requires start >= 0 and end > path_length
    ensure result == true
    return BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
""",
    "false_claim_accepts_an_unrepresentable_path_length": """
def false_claim_accepts_an_unrepresentable_path_length(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    requires path_length >= 0 and candidate_length >= 0
    requires path_length_usize.i64() != path_length and candidate_length_usize.i64() == candidate_length
    requires start >= 0 and end >= start and end <= path_length
    requires end - start == candidate_length
    ensure result == true
    return BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
""",
    "false_claim_accepts_an_unrepresentable_candidate_length": """
def false_claim_accepts_an_unrepresentable_candidate_length(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    requires path_length >= 0 and candidate_length >= 0
    requires path_length_usize.i64() == path_length and candidate_length_usize.i64() != candidate_length
    requires start >= 0 and end >= start and end <= path_length
    requires end - start == candidate_length
    ensure result == true
    return BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
""",
    "false_claim_accepts_a_negative_path_length": """
def false_claim_accepts_a_negative_path_length(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    requires path_length < 0 and candidate_length >= 0
    requires start >= 0 and end >= start
    ensure result == true
    return BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
""",
    "false_claim_accepts_a_negative_candidate_length": """
def false_claim_accepts_a_negative_candidate_length(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    requires path_length >= 0 and candidate_length < 0
    requires start >= 0 and end >= start
    ensure result == true
    return BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
""",
    "false_claim_accepts_a_negative_start": """
def false_claim_accepts_a_negative_start(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    requires path_length >= 0 and candidate_length >= 0
    requires path_length_usize.i64() == path_length and candidate_length_usize.i64() == candidate_length
    requires start < 0 and end >= start
    ensure result == true
    return BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
""",
    "false_claim_accepts_a_reversed_range": """
def false_claim_accepts_a_reversed_range(path_length: i64, candidate_length: i64, start: i64, end: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    requires path_length >= 0 and candidate_length >= 0
    requires path_length_usize.i64() == path_length and candidate_length_usize.i64() == candidate_length
    requires start >= 0 and end < start
    ensure result == true
    return BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, candidate_length, start, end, path_length_usize, candidate_length_usize)
""",
    "false_claim_accepts_a_slice_with_the_wrong_length": """
def false_claim_accepts_a_slice_with_the_wrong_length(path_length: i64, path_length_usize: usize, candidate_length_usize: usize) -> bool:
    requires path_length >= 5 and path_length_usize.i64() == path_length
    requires candidate_length_usize.i64() == 1
    ensure result == true
    return BackendSviewPrefixBoundsSpec::prefix_range_is_valid(path_length, 1, 2, 5, path_length_usize, candidate_length_usize)
""",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    source = path.read_text()
    for name, shape in shapes.items():
        if compact_code(function_section(source, name)) != compact_code(shape):
            raise SystemExit(f"{name} no longer states its intended StringView bounds claim")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("backend StringView prefix bounds proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", PREFIX_SOURCE, PACKED_META,
    CODEGEN, RUNTIME_STRINGS, SPEC, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES) + 1
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
positive_verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_verified == POSITIVE_NAMES | {"prefix_range_is_valid"}

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(NEGATIVE_NAMES) + 1
assert negative["summary"]["proven"] + len(NEGATIVE_NAMES) == negative["summary"]["obligations"]
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}
assert "prefix_range_is_valid" in {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "StringView prefix length representability, slice/byte-offset bounds within declared sview.len, and bytewise equality on valid slices, assuming the runtime view's backing-storage invariant",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
