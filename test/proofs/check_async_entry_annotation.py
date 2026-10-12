"""Admit source-linked proofs of async-entry decorator obligations."""
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
SOURCE = ROOT / "src/semantic/check_async_entry_annotations.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
DISPATCH = ROOT / "src/semantic/semantic_parallel_passes.elisa"
PIPELINE = ROOT / "src/semantic/semantic_api.elisa"
POSITIVE = HERE / "async_entry_annotation.elisa"
NEGATIVE = HERE / "async_entry_annotation_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
PASS_ID = 86
PASS_BATCH_START = 85
PASS_BATCH_SIZE = 23

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|\S', text)
    return "".join(token for token in tokens if not token.startswith("#"))


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():])
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def direct_child(source: str, parent: str, child_prefix: str) -> bool:
    lines = source.splitlines()
    parents = [index for index, line in enumerate(lines) if line.strip() == parent]
    if len(parents) != 1:
        return False
    parent_index = parents[0]
    parent_indent = len(lines[parent_index]) - len(lines[parent_index].lstrip(" \t"))
    end = parent_index + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= parent_indent:
            break
        end += 1
    children = [index for index in range(parent_index + 1, end)
                if lines[index].strip().startswith(child_prefix)]
    if len(children) != 1:
        return False
    child_indent = len(lines[children[0]]) - len(lines[children[0]].lstrip(" \t"))
    return child_indent == parent_indent + 4


def function_matches(source: str) -> bool:
    helper = function_section(source, "func_has_decorator")
    expected_helper = """def func_has_decorator(decorators: darray[Ast::Annotation], wanted: sview) -> bool:
    can Abort.Panic:
        return any decorator in decorators where decorator.name == wanted
"""
    if compact(helper) != compact(expected_helper):
        return False

    walk = function_section(source, "async_entry_check_walk")
    expected_walk = """def async_entry_check_walk(declarations: darray[Ast::Decl], table: lmut SymbolTable) -> void:
    can Memory.Allocate, Abort.Panic:
        for declaration in declarations |table| -> table:
            match declaration:
                Decl.Func(function_name, parameters, return_type, body, effects, decorators, line):
                    if func_has_decorator(decorators, "async_entry"):
                        missing_segment: bool = not func_has_decorator(decorators, "segment_agnostic") and not func_has_decorator(decorators, "segment_establishing")
                        table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.AsyncEntryAnnotation, name: function_name, line: line.line, expected: "segment", actual: ""}) if missing_segment
                        table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.AsyncEntryAnnotation, name: function_name, line: line.line, expected: "reentrant", actual: ""}) if not func_has_decorator(decorators, "reentrant_safe")
                Decl.Module(module_name, module_body, module_line):
                    table <- async_entry_check_walk(module_body, table)
                Decl.Scoped(scoped_body, scoped_line):
                    table <- async_entry_check_walk(scoped_body, table)
                _:
                    pass
"""
    if compact(walk) != compact(expected_walk):
        return False

    wrapper = function_section(source, "check_async_entry_annotations")
    expected_wrapper = """def check_async_entry_annotations(declarations: darray[Ast::Decl], table: lmut SymbolTable) -> void:
    can Memory.Allocate, Abort.Panic:
        table <- async_entry_check_walk(declarations, table)
"""
    return compact(wrapper) == compact(expected_wrapper)


source_text = SOURCE.read_text()
if not function_matches(source_text):
    raise SystemExit("async-entry source no longer matches the exact decorator and diagnostic rules")

proof_text = POSITIVE.read_text()
proof_models = {
    "needs_segment_diagnostic": """def needs_segment_diagnostic(async_entry: bool, segment_agnostic: bool, segment_establishing: bool) -> bool:
    ensure result == (async_entry and not (segment_agnostic or segment_establishing))
    return async_entry and not (segment_agnostic or segment_establishing)
""",
    "needs_reentrant_diagnostic": """def needs_reentrant_diagnostic(async_entry: bool, reentrant_safe: bool) -> bool:
    ensure result == (async_entry and not reentrant_safe)
    return async_entry and not reentrant_safe
""",
    "source_rules_are_exact": """def source_rules_are_exact(async_entry: bool, segment_agnostic: bool, segment_establishing: bool, reentrant_safe: bool) -> bool:
    ensure result == true
    return AsyncEntryAnnotationRule::needs_segment_diagnostic(async_entry, segment_agnostic, segment_establishing) ==
            (async_entry and not (segment_agnostic or segment_establishing)) and
        AsyncEntryAnnotationRule::needs_reentrant_diagnostic(async_entry, reentrant_safe) ==
            (async_entry and not reentrant_safe)
""",
}
for name, expected in proof_models.items():
    if compact(function_section(proof_text, name)) != compact(expected):
        raise SystemExit(f"proof model function {name} no longer mirrors the source-gated rule")

mutations = (
    source_text.replace(
        'not func_has_decorator(decorators, "segment_agnostic") and not func_has_decorator(decorators, "segment_establishing")',
        'not func_has_decorator(decorators, "segment_agnostic") or not func_has_decorator(decorators, "segment_establishing")',
        1,
    ),
    source_text.replace('if not func_has_decorator(decorators, "reentrant_safe")',
                        'if func_has_decorator(decorators, "reentrant_safe")', 1),
    source_text.replace('expected: "segment", actual: ""', 'expected: "reentrant", actual: ""', 1),
    source_text.replace('table <- async_entry_check_walk(module_body, table)', 'pass', 1),
    source_text.replace('table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.AsyncEntryAnnotation, name: function_name, line: line.line, expected: "segment", actual: ""}) if missing_segment', 'if false:\n                            table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.AsyncEntryAnnotation, name: function_name, line: line.line, expected: "segment", actual: ""}) if missing_segment', 1),
)
for mutation in mutations:
    if mutation == source_text or function_matches(mutation):
        raise SystemExit("async-entry source checker accepted a condition, payload, or traversal mutation")

if 'include "./check_async_entry_annotations.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic root no longer includes async-entry annotation checking")
dispatch_text = DISPATCH.read_text()
if not direct_child(dispatch_text, f"elif pass_id == {PASS_ID}:",
                   "table <- check_async_entry_annotations(loop_view.top_decls, table)"):
    raise SystemExit("parallel semantic dispatcher no longer invokes async-entry annotation checking")
if f"par_pass_run(file, &loop_view, flags, table, shared_pool, {PASS_BATCH_START}, {PASS_BATCH_SIZE})" not in PIPELINE.read_text():
    raise SystemExit("semantic pipeline no longer schedules the async-entry pass batch")

expected_positive = {
    "source_rules_are_exact",
    "either_segment_policy_satisfies_the_obligation",
    "async_entry_requires_both_obligations",
    "compliant_async_entry_has_no_missing_obligations",
    "non_async_function_needs_no_async_entry_annotations",
}
expected_negative = {
    "segment_agnostic_alone_is_insufficient",
    "segment_establishing_alone_is_insufficient",
    "reentrant_safe_satisfies_segment_policy",
    "non_async_function_requires_segment_policy",
    "compliant_async_entry_still_has_missing_annotations",
}
for path, expected in ((POSITIVE, expected_positive), (NEGATIVE, expected_negative)):
    found = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if found != expected:
        raise SystemExit(f"{path.name} theorem inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("async-entry annotation proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    SOURCE, SEMANTIC, DISPATCH, PIPELINE, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
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
assert positive == run(POSITIVE)[1], "async-entry annotation proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive | set(proof_models) <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest
print(json.dumps({
    "admitted": True,
    "scope": "async-entry segment ownership and reentrant decorator obligations",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
