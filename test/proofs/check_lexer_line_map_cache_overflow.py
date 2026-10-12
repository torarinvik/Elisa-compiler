"""Replay overflow-fallback proofs against the lexer's source-line cache."""
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
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
CACHE = ROOT / "src/lexer/lexer_line_map_cache.elisa"
FACADE = ROOT / "src/lexer/lexer.elisa"
POSITIVE = HERE / "lexer_line_map_cache_overflow.elisa"
NEGATIVE = HERE / "lexer_line_map_cache_overflow_rejected.elisa"

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
        raise SystemExit(f"{label} changed the checked overflow/fallback order")


def source_line(body: str, fragment: str, label: str) -> tuple[int, int]:
    expected = compact(fragment)
    matches = [(index, len(line) - len(line.lstrip()))
               for index, line in enumerate(body.splitlines())
               if compact(line.strip()) == expected]
    if len(matches) != 1:
        raise SystemExit(f"{label} no longer has one unambiguous source line")
    return matches[0]


def require_nested_under(body: str, guard: str, action: str, label: str) -> None:
    guard_index, guard_indent = source_line(body, guard, label)
    action_index, action_indent = source_line(body, action, label)
    if action_index <= guard_index or action_indent <= guard_indent:
        raise SystemExit(f"{label} moved outside the checked overflow branch")


def require_nested_return_under(body: str, guard: str, later: str, label: str) -> None:
    guard_index, guard_indent = source_line(body, guard, label)
    later_index, _ = source_line(body, later, label)
    candidates = [(index, len(line) - len(line.lstrip()))
                  for index, line in enumerate(body.splitlines())
                  if index > guard_index and compact(line.strip()) == "return" and index < later_index]
    if len(candidates) != 1 or candidates[0][1] <= guard_indent:
        raise SystemExit(f"{label} no longer returns from inside the overflow branch")


cache_text = CACHE.read_text()
facade_text = FACADE.read_text()
if 'include "./lexer_line_map_cache.elisa"' not in facade_text:
    raise SystemExit("lexer facade no longer includes its line-map cache implementation")
if "const LEXER_LINE_MAP_CAPACITY: usize = 65536" not in cache_text:
    raise SystemExit("line-map cache capacity changed; revisit the overflow proof")

ready = function_section(cache_text, "line_map_cache_ready")
if ready.count("return lexer_line_map_state == 1") != 2:
    raise SystemExit("line-map cache readiness no longer requires the ready state on both paths")
if "return false" not in ready:
    raise SystemExit("line-map cache readiness no longer fails closed without an environment map")
require_ordered(ready, (
    "if key == lexer_line_map_key and lexer_line_map_state != 0:",
    "line_map_cache_build()",
    "lexer_line_map_key <- key",
), "line-map cache readiness")
ready_returns = [match.start() for match in re.finditer("return lexer_line_map_state == 1", ready)]
key_guard = ready.find("if key == lexer_line_map_key and lexer_line_map_state != 0:")
build_call = ready.find("line_map_cache_build()")
key_store = ready.find("lexer_line_map_key <- key")
if len(ready_returns) != 2 or not (key_guard < ready_returns[0] < build_call < key_store < ready_returns[1]):
    raise SystemExit("line-map cache readiness no longer returns cached state only after key validation or rebuild")

build = function_section(cache_text, "line_map_cache_build")
overflow_guard = "if lexer_line_map_count >= LEXER_LINE_MAP_CAPACITY can Global.Read:"
require_nested_return_under(build, overflow_guard,
                            "lexer_line_map_flat[lexer_line_map_count] <- entry_flat",
                            "overflow early return")
require_ordered(build, (
    "lexer_line_map_state <- 2",
    overflow_guard,
    "lexer_line_map_flat[lexer_line_map_count] <- entry_flat",
    "lexer_line_map_state <- 1",
), "line-map cache overflow handling")
if build.count("lexer_line_map_state <- 1") != 1:
    raise SystemExit("line-map cache must publish readiness at one successful completion point")
outer_loop = "while cursor < map_storage.count |cursor, map_storage, trusted_prefix, realpath_buffer|:"
if compact(outer_loop) not in compact(build):
    raise SystemExit("line-map cache build lost its complete map scan")
build_lines = build.splitlines()
outer_index, outer_indent = source_line(build, outer_loop, "successful cache publication")
cursor_done, _ = source_line(build, "cursor <- entry_stop + 1.usize()", "successful cache publication")
ready_lines = [(index, len(line) - len(line.lstrip()))
               for index, line in enumerate(build_lines)
               if compact(line.strip()) == compact("lexer_line_map_state <- 1")]
post_loop_writes = [(index, len(line) - len(line.lstrip()))
                    for index, line in enumerate(build_lines)
                    if compact(line.strip()) == compact("can Global.Write:") and index > cursor_done
                    and len(line) - len(line.lstrip()) == outer_indent]
if len(ready_lines) != 1 or len(post_loop_writes) != 1:
    raise SystemExit("cache readiness is no longer published by one post-scan write")
ready_index, ready_indent = ready_lines[0]
write_index, _ = post_loop_writes[0]
if not (outer_index < cursor_done < write_index < ready_index and ready_indent == outer_indent + 4):
    raise SystemExit("cache readiness moved into the scan loop or before its last row")
if (compact(build_lines[ready_index - 1].strip()) != compact("can Global.Write:")
        or len(build_lines[ready_index - 1]) - len(build_lines[ready_index - 1].lstrip()) != ready_indent - 4):
    raise SystemExit("successful cache publication lost its write guard")

original = function_section(facade_text, "source_original_line")
require_ordered(original, (
    "(line_map_cached_original_line(flat_line) can Global.Read) return if (line_map_cache_ready() can Global{Read,Write})",
    "return source_original_line_from_map(flat_line)",
), "original-line cache fallback")
runtime_std = function_section(facade_text, "source_line_is_runtime_std")
require_ordered(runtime_std, (
    "(line_map_cached_is_runtime_std(flat_line) can Global.Read) return if (line_map_cache_ready() can Global{Read,Write})",
    "return source_line_is_runtime_std_from_map(flat_line)",
), "runtime-stdlib cache fallback")

positive_names = {
    "line_map_cache_usable_only_in_ready_state",
    "choose_line_map_result",
    "overflow_uses_per_call_map",
    "every_nonready_state_uses_per_call_map",
    "ready_state_uses_cache",
}
positive_text = POSITIVE.read_text()
if not positive_names <= set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text)):
    raise SystemExit("line-map cache proof is missing a required theorem")
expected_selector = compact("""def choose_line_map_result(state: i64, cached_result: i64, parsed_result: i64) -> i64:
    ensure result == (cached_result if state == LINE_MAP_CACHE_READY else parsed_result)
    return cached_result if state == LINE_MAP_CACHE_READY else parsed_result""")
if compact(function_section(positive_text, "choose_line_map_result")) != expected_selector:
    raise SystemExit("proof model no longer matches the cache-versus-parser result selection")
for name, expected in {
    "overflow_uses_per_call_map": "def overflow_uses_per_call_map(cached_result: i64, parsed_result: i64) -> bool: ensure result == true return (cached_result if LINE_MAP_CACHE_NOT_READY == LINE_MAP_CACHE_READY else parsed_result) == parsed_result",
    "every_nonready_state_uses_per_call_map": "def every_nonready_state_uses_per_call_map(state: i64, cached_result: i64, parsed_result: i64) -> bool: requires state != LINE_MAP_CACHE_READY ensure result == true return (cached_result if state == LINE_MAP_CACHE_READY else parsed_result) == parsed_result",
    "ready_state_uses_cache": "def ready_state_uses_cache(state: i64, cached_result: i64, parsed_result: i64) -> bool: requires state == LINE_MAP_CACHE_READY ensure result == true return (cached_result if state == LINE_MAP_CACHE_READY else parsed_result) == cached_result",
}.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"{name} no longer proves the corresponding state-selected result")
if 'include "./lexer_line_map_cache_overflow.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("overflow false control no longer imports the result selector")
if "def nonready_state_uses_partial_cache(" not in NEGATIVE.read_text():
    raise SystemExit("partial-cache false control is missing")
if compact(function_section(NEGATIVE.read_text(), "nonready_state_uses_partial_cache")) != compact(
    "def nonready_state_uses_partial_cache(state: i64, cached_result: i64, parsed_result: i64) -> bool: requires state != LINE_MAP_CACHE_READY ensure result == true return (cached_result if state == LINE_MAP_CACHE_READY else parsed_result) == cached_result"
):
    raise SystemExit("partial-cache control no longer asserts the false overflow selection")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("line-map cache proof requires a strict proof build")

inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, Path(__file__), CACHE, FACADE, POSITIVE, NEGATIVE]
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
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names <= verified
assert positive == run(POSITIVE)[1], "line-map cache proof changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "nonready_state_uses_partial_cache"),
]
assert negative == run(NEGATIVE)[1], "line-map cache false control changed across repeated runs"

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "cache overflow and every non-ready cache state use the per-call line-map parser",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claim_rejected": negative["findings"][0]["name"],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
