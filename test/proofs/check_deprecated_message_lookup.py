"""Source-bind the deprecated-call name/message scan to its recursive proof."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check source bindings without requiring the pinned proof product")
ARGS = argument_parser.parse_args()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/semantic/deprecated_message_lookup.elisa"
CONSUMER = ROOT / "src/semantic/check_deprecated_call.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "deprecated_message_lookup.elisa"
NEGATIVE = HERE / "deprecated_message_lookup_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source_text = SOURCE.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_index_model = '''
ghost def message_index_from(names: darray[sview]&, callee_name: sview, remaining: usize) -> usize:
    requires remaining <= names.count
    decreases remaining
    return names.count if remaining == 0
    return remaining - 1 if names[remaining - 1] == callee_name
    return message_index_from(names, callee_name, remaining - 1)
'''
expected_index_scan = '''
def message_index(names: darray[sview]&, callee_name: sview) -> usize:
    ensure result == message_index_from(names, callee_name, names.count)
    index: mutable usize = names.count
    while index > 0 |index, names, callee_name|:
        decreases index
        invariant index <= names.count
        invariant message_index_from(names, callee_name, index) == message_index_from(names, callee_name, names.count)
        probe: usize = index - 1
        if names[probe] == callee_name:
            return probe
        index <- probe
    return names.count
'''
if compact(function_section(source_text, "message_index_from")) != compact(expected_index_model):
    raise SystemExit("recursive deprecated-message index model changed without updating its proof")
if compact(function_section(source_text, "message_index")) != compact(expected_index_scan):
    raise SystemExit("production deprecated-message index scan no longer refines its recursive model")
expected_wrapper = '''
def deprecated_message_index(callee_name: sview, names: darray[sview]&, messages: darray[sview @source]&) -> usize:
    requires names.count == messages.count
    can Abort.Panic:
        return SemanticDeprecatedMessageLookup::message_index(names, callee_name)
'''
if compact(function_section(consumer_text, "deprecated_message_index")) != compact(expected_wrapper):
    raise SystemExit("semantic consumer no longer delegates lookup to the proved helper")
if "messages:darray[sview@source]&" not in compact(function_section(consumer_text, "deprecated_call_expression")) or \
        "messages:mutabledarray[sview@source]&" not in compact(function_section(consumer_text, "collect_deprecated_functions")) or \
        "messages:mutabledarray[sview@source]@source=[]" not in compact(function_section(consumer_text, "check_deprecated_call")):
    raise SystemExit("deprecated message views no longer retain their source region through diagnostic creation")
if consumer_text.count('include "./deprecated_message_lookup.elisa"') != 1:
    raise SystemExit("deprecated-call consumer must include the isolated lookup exactly once")
if semantic_text.count('include "./check_deprecated_call.elisa"') != 1:
    raise SystemExit("semantic root must include the deprecated-call consumer exactly once")
collector = compact(function_section(consumer_text, "collect_deprecated_functions"))
if "requiresnames.count==messages.count" not in collector or \
        "ensurenames.count==messages.count" not in collector or \
        collector.count("invariantnames.count==messages.count") != 2 or \
        collector.count("assertnames.count==messages.count") < 5 or \
        "deprecated_function_pair_append(function_name,strip_quotes(message),names,messages)" not in collector:
    raise SystemExit("deprecated declaration collection no longer preserves parallel-array length equality")
pair_append = compact(function_section(consumer_text, "deprecated_function_pair_append"))
if "requiresnames.count==messages.count" not in pair_append or \
        "ensurenames.count==messages.count" not in pair_append or \
        "names.push(function_name)messages.push(message)" not in pair_append:
    raise SystemExit("deprecated declaration pair append no longer proves the parallel-array length invariant")
for name in ("deprecated_call_expression", "deprecated_call_statements", "deprecated_call_walk"):
    if "requiresnames.count==messages.count" not in compact(function_section(consumer_text, name)):
        raise SystemExit(f"{name} no longer carries the parallel-array lookup precondition")
call_expression = compact(function_section(consumer_text, "deprecated_call_expression"))
if "deprecated_message_index(callee_name,names,messages)ifcallee_name!=\"\"elsenames.count" not in call_expression or \
        "actual:messages[message_index]" not in call_expression or \
        "ifmessage_index<names.count" not in call_expression:
    raise SystemExit("deprecated-call diagnostics no longer use the bounds-checked scalar message index")
root_check = compact(function_section(consumer_text, "check_deprecated_call"))
root_order = (
    "names:mutabledarray[sview]=[]",
    "messages:mutabledarray[sview@source]@source=[]",
    "assertnames.count==messages.count",
    "collect_deprecated_functions(file.top_decls,file.annotation_args,names,messages)",
    "assertnames.count==messages.count",
    "table<-deprecated_call_walk(file.top_decls,names,messages,table)ifnames.count>0",
)
root_positions = []
root_cursor = 0
for fragment in root_order:
    position = root_check.find(fragment, root_cursor)
    root_positions.append(position)
    if position >= 0:
        root_cursor = position + len(fragment)
if any(position < 0 for position in root_positions) or root_positions != sorted(root_positions):
    raise SystemExit("top-level deprecated-call pass no longer establishes array parity before lookup traversal")

positive_names = {
    "production_lookup_matches_recursive_model",
    "missing_name_has_no_message",
    "empty_table_has_no_message",
    "duplicate_name_uses_last_message",
    "one_name_returns_its_parallel_message",
}
negative_names = {
    "false_claim_duplicate_name_uses_first_message",
    "false_claim_missing_name_is_found",
}
if declarations(positive_text) != positive_names:
    raise SystemExit("deprecated-message positive proof inventory changed")
if declarations(negative_text) != negative_names or \
        'include "./deprecated_message_lookup.elisa"' not in negative_text:
    raise SystemExit("deprecated-message false-claim inventory changed")

expected_positive = {
    "production_lookup_matches_recursive_model": '''
def production_lookup_matches_recursive_model(names: darray[sview]&, messages: darray[sview]&, callee_name: sview) -> bool can[Abort.Panic]:
    requires names.count == messages.count
    ensure result == true
    can Abort.Panic:
        return SemanticDeprecatedMessageLookup::message_index(names, callee_name) == SemanticDeprecatedMessageLookup::message_index_from(names, callee_name, names.count)
''',
    "missing_name_has_no_message": '''
def missing_name_has_no_message() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        names: darray[sview] = ["old_api", "other_api"]
        index: usize = SemanticDeprecatedMessageLookup::message_index(names, "new_api")
        return index == names.count
''',
    "empty_table_has_no_message": '''
def empty_table_has_no_message() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        names: darray[sview] = []
        index: usize = SemanticDeprecatedMessageLookup::message_index(names, "old_api")
        return index == names.count
''',
    "duplicate_name_uses_last_message": '''
def duplicate_name_uses_last_message() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        names: darray[sview] = ["old_api", "other_api", "old_api"]
        messages: darray[sview] = ["first", "unrelated", "last"]
        index: usize = SemanticDeprecatedMessageLookup::message_index(names, "old_api")
        return index == 2 and messages[index] == "last"
''',
    "one_name_returns_its_parallel_message": '''
def one_name_returns_its_parallel_message() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        names: darray[sview] = ["old_api"]
        messages: darray[sview] = ["use new_api"]
        index: usize = SemanticDeprecatedMessageLookup::message_index(names, "old_api")
        return index == 0 and messages[index] == "use new_api"
''',
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive theorem {name} changed without updating its source-bound proof gate")

expected_negative = {
    "false_claim_duplicate_name_uses_first_message": '''
def false_claim_duplicate_name_uses_first_message() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        names: darray[sview] = ["old_api", "old_api"]
        index: usize = SemanticDeprecatedMessageLookup::message_index(names, "old_api")
        return index == 0
''',
    "false_claim_missing_name_is_found": '''
def false_claim_missing_name_is_found() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        names: darray[sview] = ["old_api"]
        index: usize = SemanticDeprecatedMessageLookup::message_index(names, "new_api")
        return index < names.count
''',
}
for name, expected in expected_negative.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"false-claim theorem {name} changed without updating its source-bound proof gate")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "proof_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("deprecated-message proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, CONSUMER, SEMANTIC,
    POSITIVE, NEGATIVE, *source_closure,
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


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "deprecated-message proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "proof inputs changed during admission"
