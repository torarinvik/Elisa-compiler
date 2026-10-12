"""Admit arithmetic bounds for the line-map cache's binary lower-bound search."""
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
CACHE = ROOT / "src/lexer/lexer_line_map_cache.elisa"
POSITIVE = HERE / "lexer_line_map_best_bounds.elisa"
NEGATIVE = HERE / "lexer_line_map_best_bounds_rejected.elisa"

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
        raise SystemExit(f"{label} no longer follows the proved interval bounds")


def source_line(body: str, fragment: str, label: str) -> tuple[int, int]:
    expected = compact(fragment)
    matches = [(index, len(line) - len(line.lstrip()))
               for index, line in enumerate(body.splitlines())
               if compact(line.strip()) == expected]
    if len(matches) != 1:
        raise SystemExit(f"{label} no longer has one unambiguous source line")
    return matches[0]


def require_nested_return_under(body: str, guard: str, later: str, label: str) -> None:
    guard_index, guard_indent = source_line(body, guard, label)
    later_index, _ = source_line(body, later, label)
    returns = [(index, len(line) - len(line.lstrip()))
               for index, line in enumerate(body.splitlines())
               if index > guard_index and index < later_index
               and compact(line.strip()) == "return"]
    if len(returns) != 1 or returns[0][1] <= guard_indent:
        raise SystemExit(f"{label} overflow no longer returns before a cache row write")


source = CACHE.read_text()
if "const LEXER_LINE_MAP_CAPACITY: usize = 65536" not in source:
    raise SystemExit("line-map capacity changed; revisit the signed arithmetic model")

build = function_section(source, "line_map_cache_build")
overflow_guard = "if lexer_line_map_count >= LEXER_LINE_MAP_CAPACITY can Global.Read:"
require_ordered(build, (
    "lexer_line_map_count <- 0",
    "while cursor < map_storage.count |cursor, map_storage, trusted_prefix, realpath_buffer|:",
    overflow_guard,
    "lexer_line_map_flat[lexer_line_map_count] <- entry_flat",
    "lexer_line_map_count <- lexer_line_map_count + 1",
), "bounded cache construction")
if build.count("lexer_line_map_count <- lexer_line_map_count + 1") != 1:
    raise SystemExit("cache row count no longer advances exactly once per stored entry")
require_nested_return_under(build, overflow_guard,
                            "lexer_line_map_flat[lexer_line_map_count] <- entry_flat",
                            "bounded cache construction")

best = function_section(source, "line_map_cache_best")
require_ordered(build, (
    "lexer_line_map_sorted <- true",
    "if lexer_line_map_count > 0 and entry_flat < lexer_line_map_flat[lexer_line_map_count - 1] can Global.Read:",
    "lexer_line_map_sorted <- false",
    "lexer_line_map_flat[lexer_line_map_count] <- entry_flat",
), "sorted cache invariant")
if build.count("lexer_line_map_sorted <- true") != 1 or build.count("lexer_line_map_sorted <- false") != 1:
    raise SystemExit("sorted-state flag no longer tracks exactly the descending-entry check")
require_ordered(best, (
    "if lexer_line_map_sorted can Global.Read:",
    "low: mutable usize = 0",
    "high: mutable usize = lexer_line_map_count can Global.Read",
    "while low < high |low, high, flat_line|:",
    "middle: usize = low + (high - low) / 2",
    "if lexer_line_map_flat[middle] <= flat_line can Global.Read:",
    "low <- middle + 1",
    "high <- middle",
    "best <- low.i64() - 1",
), "sorted line-map lookup")
require_ordered(best, (
    "best <- low.i64() - 1",
    "-1 return if best < 0",
    "-1 return if (lexer_line_map_flat[best.usize()] == 0 can Global.Read)",
    "return best",
), "line-map predecessor access")
if "else:" not in best or "for index in 0..<(lexer_line_map_count can Global.Read)" not in best:
    raise SystemExit("unsorted cache tables no longer use the linear lookup fallback")

positive_names = {
    "lower_bound_midpoint_stays_inside",
    "advancing_low_stays_bounded_and_shrinks",
    "retreating_high_stays_bounded_and_shrinks",
    "accepting_branch_strictly_reduces_interval_width",
    "rejecting_branch_strictly_reduces_interval_width",
    "zero_lower_bound_produces_the_negative_one_sentinel",
    "positive_lower_bound_produces_a_valid_predecessor",
    "accepting_midpoint_preserves_first_greater_boundary",
    "rejecting_midpoint_preserves_first_greater_boundary",
}
negative_names = {
    "false_midpoint_can_reach_high",
    "false_right_branch_keeps_old_high",
    "false_accepting_branch_can_skip_boundary",
    "false_rejecting_branch_can_discard_boundary",
    "false_accepting_branch_does_not_reduce_width",
    "false_rejecting_branch_does_not_reduce_width",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

positive_text = POSITIVE.read_text()
expected_positive = {
    "lower_bound_midpoint_stays_inside": """def lower_bound_midpoint_stays_inside(low: i64, high: i64, count: i64) -> bool:
        requires low >= 0 and low < high and high <= count and count <= LINE_MAP_BEST_MAX_COUNT
        ensure result == true
        middle: i64 = low + (high - low) / 2
        return middle >= low and middle < high and middle < count""",
    "advancing_low_stays_bounded_and_shrinks": """def advancing_low_stays_bounded_and_shrinks(low: i64, high: i64, middle: i64) -> bool:
        requires low >= 0 and low <= middle and middle < high
        ensure result == true
        next_low: i64 = middle + 1
        return next_low > low and next_low <= high""",
    "retreating_high_stays_bounded_and_shrinks": """def retreating_high_stays_bounded_and_shrinks(low: i64, high: i64, middle: i64) -> bool:
        requires low >= 0 and low <= middle and middle < high
        ensure result == true
        next_high: i64 = middle
        return next_high >= low and next_high < high""",
    "accepting_branch_strictly_reduces_interval_width": """def accepting_branch_strictly_reduces_interval_width(low: i64, high: i64, middle: i64) -> bool:
        requires low >= 0 and low <= middle and middle < high
        ensure result == true
        next_low: i64 = middle + 1
        return high - next_low < high - low""",
    "rejecting_branch_strictly_reduces_interval_width": """def rejecting_branch_strictly_reduces_interval_width(low: i64, high: i64, middle: i64) -> bool:
        requires low >= 0 and low <= middle and middle < high
        ensure result == true
        next_high: i64 = middle
        return next_high - low < high - low""",
    "zero_lower_bound_produces_the_negative_one_sentinel": """def zero_lower_bound_produces_the_negative_one_sentinel() -> bool:
        ensure result == true
        low: i64 = 0
        best: i64 = low - 1
        return best == (0 - 1)""",
    "positive_lower_bound_produces_a_valid_predecessor": """def positive_lower_bound_produces_a_valid_predecessor(low: i64, count: i64) -> bool:
        requires low > 0 and low <= count and count <= LINE_MAP_BEST_MAX_COUNT
        ensure result == true
        best: i64 = low - 1
        return best >= 0 and best < count""",
    "accepting_midpoint_preserves_first_greater_boundary": """def accepting_midpoint_preserves_first_greater_boundary(low: i64, high: i64, middle: i64, boundary: i64) -> bool:
        requires low >= 0 and low <= middle and middle < high and low <= boundary and boundary <= high and middle < boundary
        ensure result == true
        next_low: i64 = middle + 1
        return next_low > low and next_low <= boundary and boundary <= high""",
    "rejecting_midpoint_preserves_first_greater_boundary": """def rejecting_midpoint_preserves_first_greater_boundary(low: i64, high: i64, middle: i64, boundary: i64) -> bool:
        requires low >= 0 and low <= boundary and boundary <= middle and middle < high
        ensure result == true
        next_high: i64 = middle
        return low <= boundary and boundary <= next_high and next_high < high""",
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"{name} no longer proves the checked binary-search property")

negative_text = NEGATIVE.read_text()
if 'include "./lexer_line_map_best_bounds.elisa"' not in negative_text:
    raise SystemExit("line-map search false controls no longer share the positive model")
expected_negative = {
    "false_midpoint_can_reach_high": """def false_midpoint_can_reach_high(low: i64, high: i64, count: i64) -> bool:
        requires low >= 0 and low < high and high <= count and count <= LINE_MAP_BEST_MAX_COUNT
        ensure result == true
        middle: i64 = low + (high - low) / 2
        return middle >= high""",
    "false_right_branch_keeps_old_high": """def false_right_branch_keeps_old_high(low: i64, high: i64, middle: i64) -> bool:
        requires low >= 0 and low <= middle and middle < high
        ensure result == true
        next_high: i64 = middle
        return next_high == high""",
    "false_accepting_branch_can_skip_boundary": """def false_accepting_branch_can_skip_boundary(low: i64, high: i64, middle: i64, boundary: i64) -> bool:
        requires low >= 0 and low <= middle and middle < high and low <= boundary and boundary <= high and middle < boundary
        ensure result == true
        next_low: i64 = middle + 1
        return next_low > boundary""",
    "false_rejecting_branch_can_discard_boundary": """def false_rejecting_branch_can_discard_boundary(low: i64, high: i64, middle: i64, boundary: i64) -> bool:
        requires low >= 0 and low <= boundary and boundary <= middle and middle < high
        ensure result == true
        next_high: i64 = middle
        return next_high < boundary""",
    "false_accepting_branch_does_not_reduce_width": """def false_accepting_branch_does_not_reduce_width(low: i64, high: i64, middle: i64) -> bool:
        requires low >= 0 and low <= middle and middle < high
        ensure result == true
        next_low: i64 = middle + 1
        return high - next_low >= high - low""",
    "false_rejecting_branch_does_not_reduce_width": """def false_rejecting_branch_does_not_reduce_width(low: i64, high: i64, middle: i64) -> bool:
        requires low >= 0 and low <= middle and middle < high
        ensure result == true
        next_high: i64 = middle
        return next_high - low >= high - low""",
}
for name, expected in expected_negative.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"{name} no longer challenges the claimed search invariant")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("line-map search bounds require a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
          PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
          Path(__file__), Path(__file__).with_name("proof_product_gate.py"),
          CACHE, POSITIVE, NEGATIVE]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names) + 1
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 2 * len(positive_names)
assert {item["name"] for item in positive["declaration_details"] if item.get("verified")} == positive_names
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "line-map bounds proof changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names) + 1
assert negative["summary"]["obligations"] == 2 * (len(positive_names) + len(negative_names))
assert {finding["name"] for finding in negative["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" and finding["status"] == "unknown"
           for finding in negative["findings"])
assert negative == run(NEGATIVE)[1], "line-map false controls changed across repeated runs"
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({"admitted": True,
                  "scope": "sorted line-map lower-bound midpoint, interval progress, and predecessor index",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_refused": sorted(negative_names),
                  "proof_revision": product["proof"].get("head"),
                  "compiler_revision": product["compiler"].get("source_revision"),
                  "source_sha256": hashes_before}, sort_keys=True))
