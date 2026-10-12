"""Admit exact-key and bounded-probe proofs for the line-map path cache."""
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
POSITIVE = HERE / "lexer_line_map_path_cache.elisa"
NEGATIVE = HERE / "lexer_line_map_path_cache_rejected.elisa"

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
        raise SystemExit(f"{label} no longer follows the proved key/probe contract")


def require_occurrences_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    text = compact(body)
    cursor = 0
    for fragment in fragments:
        position = text.find(compact(fragment), cursor)
        if position < 0:
            raise SystemExit(f"{label} no longer follows the proved key/probe contract")
        cursor = position + len(compact(fragment))


def source_line_sequence(body: str, fragments: tuple[str, ...], label: str) -> list[tuple[int, int]]:
    lines = body.splitlines()
    cursor = 0
    result = []
    for fragment in fragments:
        expected = compact(fragment)
        match = next((index for index in range(cursor, len(lines))
                      if compact(lines[index].strip()) == expected), None)
        if match is None:
            raise SystemExit(f"{label} no longer follows the proved key/probe contract")
        result.append((match, len(lines[match]) - len(lines[match].lstrip())))
        cursor = match + 1
    return result


source = CACHE.read_text()
if "const LEXER_LINE_MAP_PATH_CACHE_CAPACITY: usize = 8192" not in source:
    raise SystemExit("path-cache capacity changed; revisit the finite-probe proof")
for name in (
    "lexer_line_map_path_cache_used",
    "lexer_line_map_path_cache_hash",
    "lexer_line_map_path_cache_start",
    "lexer_line_map_path_cache_stop",
    "lexer_line_map_path_cache_std",
):
    declaration = re.search(rf"(?m)^global mutable {name}: array\[[^,]+, ([0-9]+)\]$", source)
    if declaration is None or declaration.group(1) != "8192":
        raise SystemExit(f"{name} no longer has the bounded table extent used by the proof")

paths_equal = function_section(source, "line_map_cache_paths_equal")
require_ordered(paths_equal, (
    "false return if left_stop < left_start or right_stop < right_start or left_stop - left_start != right_stop - right_start",
    "for path_offset in 0..<(left_stop - left_start)",
    "false return if map_storage[left_start + path_offset] != map_storage[right_start + path_offset]",
    "return true",
), "path equality")
equality_shape = source_line_sequence(paths_equal, (
    "false return if left_stop < left_start or right_stop < right_start or left_stop - left_start != right_stop - right_start",
    "for path_offset in 0..<(left_stop - left_start) |map_storage, left_start, right_start|:",
    "false return if map_storage[left_start + path_offset] != map_storage[right_start + path_offset]",
    "return true",
), "path equality")
length_indent, loop_indent, byte_check_indent, success_indent = [indent for _, indent in equality_shape]
if not (length_indent == loop_indent == success_indent and byte_check_indent == loop_indent + 4):
    raise SystemExit("path equality no longer rejects mismatched bytes inside its full-length scan")

build = function_section(source, "line_map_cache_build")
require_ordered(build, (
    "lexer_line_map_path_cache_used[cache_index] <- 0",
    "while cursor < map_storage.count |cursor, map_storage, trusted_prefix, realpath_buffer|:",
    "path_hash: u64 = line_map_cache_path_hash(map_storage, path_start, path_stop)",
    "path_cache_slot: mutable usize = (path_hash % LEXER_LINE_MAP_PATH_CACHE_CAPACITY.u64()).usize()",
    "path_cache_probes: mutable usize = 0.usize()",
    "while path_cache_probes < LEXER_LINE_MAP_PATH_CACHE_CAPACITY",
    "if not path_cache_found:",
), "bounded path-cache placement and fallback")

build_compact = compact(build)
probe_start = build_compact.find(compact("while path_cache_probes < LEXER_LINE_MAP_PATH_CACHE_CAPACITY"))
fallback_start = build_compact.find(compact("if not path_cache_found:"), probe_start)
if probe_start < 0 or fallback_start < 0:
    raise SystemExit("path-cache probe loop or bounded miss fallback is missing")
probe_loop = build_compact[probe_start:fallback_start]
require_ordered(build_compact[fallback_start:], (
    "if not path_cache_found:",
    "if source_line_map_path_is_runtime_std(map_storage, path_start, path_stop, trusted_prefix, realpath_buffer):",
    "is_std <- 1",
), "path-cache miss fallback")
require_occurrences_ordered(probe_loop, (
    "while path_cache_probes < LEXER_LINE_MAP_PATH_CACHE_CAPACITY",
    "if lexer_line_map_path_cache_used[path_cache_slot] != 0 can Global.Read:",
    "if lexer_line_map_path_cache_hash[path_cache_slot] == path_hash can Global.Read:",
    "if line_map_cache_paths_equal(map_storage, path_start, path_stop, old_start, old_stop):",
    "is_std <- lexer_line_map_path_cache_std[path_cache_slot] can Global.Read",
    "path_cache_found <- true",
    "break",
    "path_cache_slot <- path_cache_slot + 1.usize()",
    "path_cache_slot <- 0.usize() if path_cache_slot >= LEXER_LINE_MAP_PATH_CACHE_CAPACITY",
    "path_cache_probes <- path_cache_probes + 1.usize()",
    "else:",
    "if source_line_map_path_is_runtime_std(map_storage, path_start, path_stop, trusted_prefix, realpath_buffer):",
    "is_std <- 1",
    "lexer_line_map_path_cache_used[path_cache_slot] <- 1",
    "lexer_line_map_path_cache_hash[path_cache_slot] <- path_hash",
    "lexer_line_map_path_cache_start[path_cache_slot] <- path_start",
    "lexer_line_map_path_cache_stop[path_cache_slot] <- path_stop",
    "lexer_line_map_path_cache_std[path_cache_slot] <- is_std",
    "path_cache_found <- true",
    "break",
), "collision-safe probe loop")
if build_compact.count(compact("path_cache_found <- true")) != 2:
    raise SystemExit("path-cache hits are no longer limited to exact matches or empty-slot insertion")
for write in (
    "lexer_line_map_path_cache_used[cache_index] <- 0",
    "lexer_line_map_path_cache_used[path_cache_slot] <- 1",
    "lexer_line_map_path_cache_hash[path_cache_slot] <- path_hash",
    "lexer_line_map_path_cache_start[path_cache_slot] <- path_start",
    "lexer_line_map_path_cache_stop[path_cache_slot] <- path_stop",
    "lexer_line_map_path_cache_std[path_cache_slot] <- is_std",
):
    if build_compact.count(compact(write)) != 1:
        raise SystemExit("path-cache initialization or insertion now has extra writes")
probe_lines = build.splitlines()
probe_start_line = next(index for index, line in enumerate(probe_lines)
                        if compact(line.strip()) == compact("while path_cache_probes < LEXER_LINE_MAP_PATH_CACHE_CAPACITY |path_cache_slot, path_cache_probes, path_cache_found, path_hash, path_start, path_stop, is_std, map_storage, trusted_prefix, realpath_buffer|:"))
fallback_start_line = next(index for index, line in enumerate(probe_lines)
                           if index > probe_start_line and compact(line.strip()) == compact("if not path_cache_found:"))
probe_body = "\n".join(probe_lines[probe_start_line:fallback_start_line])
probe_shape = source_line_sequence(probe_body, (
    "while path_cache_probes < LEXER_LINE_MAP_PATH_CACHE_CAPACITY |path_cache_slot, path_cache_probes, path_cache_found, path_hash, path_start, path_stop, is_std, map_storage, trusted_prefix, realpath_buffer|:",
    "if lexer_line_map_path_cache_used[path_cache_slot] != 0 can Global.Read:",
    "if lexer_line_map_path_cache_hash[path_cache_slot] == path_hash can Global.Read:",
    "old_start: usize = lexer_line_map_path_cache_start[path_cache_slot] can Global.Read",
    "old_stop: usize = lexer_line_map_path_cache_stop[path_cache_slot] can Global.Read",
    "if line_map_cache_paths_equal(map_storage, path_start, path_stop, old_start, old_stop):",
    "is_std <- lexer_line_map_path_cache_std[path_cache_slot] can Global.Read",
    "path_cache_found <- true",
    "break",
    "path_cache_slot <- path_cache_slot + 1.usize()",
    "path_cache_slot <- 0.usize() if path_cache_slot >= LEXER_LINE_MAP_PATH_CACHE_CAPACITY",
    "path_cache_probes <- path_cache_probes + 1.usize()",
    "else:",
    "if source_line_map_path_is_runtime_std(map_storage, path_start, path_stop, trusted_prefix, realpath_buffer):",
    "is_std <- 1",
    "can Global{Read,Write}:",
    "lexer_line_map_path_cache_used[path_cache_slot] <- 1",
    "lexer_line_map_path_cache_hash[path_cache_slot] <- path_hash",
    "lexer_line_map_path_cache_start[path_cache_slot] <- path_start",
    "lexer_line_map_path_cache_stop[path_cache_slot] <- path_stop",
    "lexer_line_map_path_cache_std[path_cache_slot] <- is_std",
    "path_cache_found <- true",
    "break",
), "collision-safe probe nesting")
probe_indent, occupied_indent, hash_indent, start_indent, stop_indent, equality_indent, cached_indent, hit_found_indent, hit_break_indent, slot_indent, wrap_indent, counter_indent, empty_indent, direct_indent, direct_value_indent, write_indent, used_write_indent, hash_write_indent, start_write_indent, stop_write_indent, std_write_indent, insert_found_indent, insert_break_indent = [indent for _, indent in probe_shape]
if not (occupied_indent == probe_indent + 4 and hash_indent == occupied_indent + 4 and
        start_indent == hash_indent + 4 and stop_indent == hash_indent + 4 and
        equality_indent == hash_indent + 4 and cached_indent == equality_indent + 4 and
        hit_found_indent == cached_indent and hit_break_indent == cached_indent and
        slot_indent == occupied_indent + 4 and wrap_indent == slot_indent and
        counter_indent == slot_indent and empty_indent == occupied_indent and
        direct_indent == empty_indent + 4 and direct_value_indent == direct_indent + 4 and
        write_indent == empty_indent + 4 and used_write_indent == write_indent + 4 and
        hash_write_indent == write_indent + 4 and start_write_indent == write_indent + 4 and
        stop_write_indent == write_indent + 4 and std_write_indent == write_indent + 4 and
        insert_found_indent == empty_indent + 4 and insert_break_indent == empty_indent + 4):
    raise SystemExit("path-cache reuse, collision stepping, or empty-slot insertion escaped its proved branch")

positive_names = {
    "cache_hit_requires_occupied_hash_and_equal_path",
    "matching_exact_path_reuses_cached_classification",
    "hash_collision_uses_direct_classification",
    "empty_slot_uses_direct_classification",
    "cache_miss_uses_direct_classification",
    "wrapped_probe_slot_stays_in_range",
    "probe_counter_advances_no_farther_than_capacity",
}
negative_names = {
    "false_hash_match_alone_reuses_cached_classification",
    "false_in_range_slot_reaches_capacity",
    "false_in_range_probe_count_reaches_capacity",
    "false_cache_miss_uses_cached_classification",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "./lexer_line_map_path_cache.elisa"' not in negative_text:
    raise SystemExit("path-cache false controls no longer share the positive model")
expected_shapes = {
    "cache_hit_requires_occupied_hash_and_equal_path": """def cache_hit_requires_occupied_hash_and_equal_path(occupied: bool, hashes_match: bool, paths_equal: bool) -> bool:
        ensure result == (occupied and hashes_match and paths_equal)
        return occupied and hashes_match and paths_equal""",
    "matching_exact_path_reuses_cached_classification": """def matching_exact_path_reuses_cached_classification(occupied: bool, hashes_match: bool, paths_equal: bool, cached_is_std: bool, direct_is_std: bool) -> bool:
        requires occupied and hashes_match and paths_equal
        ensure result == cached_is_std
        return cached_is_std if occupied and hashes_match and paths_equal else direct_is_std""",
    "hash_collision_uses_direct_classification": """def hash_collision_uses_direct_classification(occupied: bool, hashes_match: bool, paths_equal: bool, cached_is_std: bool, direct_is_std: bool) -> bool:
        requires occupied and hashes_match and not paths_equal
        ensure result == direct_is_std
        return cached_is_std if occupied and hashes_match and paths_equal else direct_is_std""",
    "empty_slot_uses_direct_classification": """def empty_slot_uses_direct_classification(occupied: bool, hashes_match: bool, paths_equal: bool, cached_is_std: bool, direct_is_std: bool) -> bool:
        requires not occupied
        ensure result == direct_is_std
        return cached_is_std if occupied and hashes_match and paths_equal else direct_is_std""",
    "cache_miss_uses_direct_classification": """def cache_miss_uses_direct_classification(found: bool, cached_is_std: bool, direct_is_std: bool) -> bool:
        requires not found
        ensure result == direct_is_std
        return cached_is_std if found else direct_is_std""",
    "wrapped_probe_slot_stays_in_range": """def wrapped_probe_slot_stays_in_range(slot: i64) -> bool:
        requires slot >= 0 and slot < LINE_MAP_PATH_CACHE_CAPACITY_MODEL
        ensure result == true
        next_slot: i64 = 0 if slot + 1 >= LINE_MAP_PATH_CACHE_CAPACITY_MODEL else slot + 1
        return next_slot >= 0 and next_slot < LINE_MAP_PATH_CACHE_CAPACITY_MODEL""",
    "probe_counter_advances_no_farther_than_capacity": """def probe_counter_advances_no_farther_than_capacity(probes: i64) -> bool:
        requires probes >= 0 and probes < LINE_MAP_PATH_CACHE_CAPACITY_MODEL
        ensure result == true
        next_probes: i64 = probes + 1
        return next_probes > probes and next_probes <= LINE_MAP_PATH_CACHE_CAPACITY_MODEL""",
}
for name, expected in expected_shapes.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"{name} no longer proves the intended path-cache property")
negative_shapes = {
    "false_hash_match_alone_reuses_cached_classification": """def false_hash_match_alone_reuses_cached_classification(occupied: bool, hashes_match: bool, paths_equal: bool, cached_is_std: bool, direct_is_std: bool) -> bool:
        requires occupied and hashes_match and not paths_equal
        ensure result == cached_is_std
        return cached_is_std if cache_hit_requires_occupied_hash_and_equal_path(occupied, hashes_match, true) else direct_is_std""",
    "false_in_range_slot_reaches_capacity": """def false_in_range_slot_reaches_capacity(slot_is_in_range: bool) -> bool:
        requires slot_is_in_range
        ensure result == true
        return not slot_is_in_range""",
    "false_in_range_probe_count_reaches_capacity": """def false_in_range_probe_count_reaches_capacity(probe_is_below_limit: bool) -> bool:
        requires probe_is_below_limit
        ensure result == true
        return not probe_is_below_limit""",
    "false_cache_miss_uses_cached_classification": """def false_cache_miss_uses_cached_classification(found: bool, cached_is_std: bool, direct_is_std: bool) -> bool:
        requires not found
        ensure result == cached_is_std
        return cached_is_std if found else direct_is_std""",
}
for name, expected in negative_shapes.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"{name} no longer challenges the corresponding safety property")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("path-cache proofs require a strict proof build")

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
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["replay"]["replayed"] >= report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names) + 1
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 14
assert {item["name"] for item in positive["declaration_details"] if item.get("verified")} == positive_names
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "path-cache proof changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names) + 1
assert negative["summary"]["obligations"] == 23 and negative["summary"]["proven"] == 19
assert {finding["name"] for finding in negative["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" and finding["status"] == "unknown"
           for finding in negative["findings"])
assert negative == run(NEGATIVE)[1], "path-cache false controls changed across repeated runs"
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({"admitted": True,
                  "scope": "collision-safe path-cache hits, bounded wraparound probes, and miss fallback",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_refused": sorted(negative_names),
                  "proof_revision": product["proof"].get("head"),
                  "compiler_revision": compiler.get("source_revision"),
                  "source_sha256": hashes_before}, sort_keys=True))
