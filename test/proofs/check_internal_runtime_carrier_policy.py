"""Admit source-linked proofs of runtime-carrier replacements and diagnostic severity."""
from __future__ import annotations

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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/internal_runtime_carrier_policy.elisa"
CHECK = ROOT / "src/semantic/check_internal_runtime_carrier.elisa"
SEVERITY = ROOT / "src/semantic/semantic_api_severity.elisa"
MESSAGE = ROOT / "src/semantic/diagnostic_messages/resolution.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "internal_runtime_carrier_policy.elisa"
NEGATIVE = HERE / "internal_runtime_carrier_policy_rejected.elisa"

POSITIVE_NAMES = {
    "source_replacement_policy_is_the_exact_closed_table",
    "all_carrier_replacement_rows_are_exact",
    "emission_gate_matches_the_closed_carrier_set",
    "unmapped_names_use_the_empty_fallback",
    "source_warning_policy_is_exactly_the_arena_pair",
    "both_arena_carriers_are_warnings",
    "error_carriers_and_unmapped_names_are_not_warnings",
}
NEGATIVE_NAMES = {
    "string_view_has_no_replacement",
    "dynamic_array_uses_a_view_replacement",
    "an_unmapped_name_can_emit_a_carrier_finding",
    "arena_mark_is_not_a_warning",
    "an_unmapped_name_is_a_warning",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(text: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", text))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def declaration_names(text: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


def declarations(path: Path) -> set[str]:
    return declaration_names(path.read_text())


def validate_policy(text: str) -> None:
    if "module InternalRuntimeCarrierPolicy:" not in text or "    public:" not in text:
        raise SystemExit("carrier policy must remain a standalone public module")
    if declaration_names(text) != {"runtime_carrier_replacement", "is_warning"}:
        raise SystemExit("carrier policy API changed; review and prove every new public entry point")
    replacement_rows = (
        '"StringView" -> "sview[...]" '
        '"DynArray" -> "darray[T, shape]" '
        '"DynArrayView" -> "view[T]" '
        '"DynDict" -> "dict[K, V]" '
        '"Arena" -> "region scopes and inferred container regions" '
        '"ArenaMark" -> "region scopes/checkpoints" '
        '_ -> ""'
    )
    replacement_body = compact(function_section(text, "runtime_carrier_replacement"))
    expected_replacement_rows = compact(replacement_rows)
    expected_replacement_match = f"whentype_name:{expected_replacement_rows}"
    if (f"ensureresult==({expected_replacement_match})" not in replacement_body or
            f"return{expected_replacement_match}" not in replacement_body):
        raise SystemExit("carrier replacement contract or implementation no longer matches the closed table")
    warnings = '"Arena" | "ArenaMark" -> true _ -> false'
    warning_body = compact(function_section(text, "is_warning"))
    expected_warning_table = compact(warnings)
    expected_warning_match = f"whentype_name:{expected_warning_table}"
    if (f"ensureresult==({expected_warning_match})" not in warning_body or
            f"return{expected_warning_match}" not in warning_body):
        raise SystemExit("carrier warning contract or implementation no longer classifies exactly Arena/ArenaMark")


policy_text = POLICY.read_text()
validate_policy(policy_text)

# Ensure a coordinated edit to both a contract and implementation arm still fails closed.
policy_mutations = [
    policy_text.replace('"StringView" -> "sview[...]"', '"StringView" -> ""'),
    policy_text.replace('"DynArray" -> "darray[T, shape]"', '"DynArray" -> "view[T]"'),
    policy_text.replace('"DynArrayView" -> "view[T]"', '"DynArrayView" -> "darray[T, shape]"'),
    policy_text.replace('"DynDict" -> "dict[K, V]"', '"DynDict" -> ""'),
    policy_text.replace('"Arena" -> "region scopes and inferred container regions"', '"Arena" -> ""'),
    policy_text.replace('"ArenaMark" -> "region scopes/checkpoints"', '"ArenaMark" -> ""'),
    policy_text.replace('"Arena" | "ArenaMark" -> true', '"Arena" -> true'),
    policy_text.replace('_ -> ""', '_ -> "<wrong fallback>"'),
]
for mutated in policy_mutations:
    try:
        validate_policy(mutated)
    except SystemExit:
        pass
    else:
        raise SystemExit("runtime-carrier policy mutation escaped its exact-table checker")

check_text = CHECK.read_text()
if "def runtime_carrier_replacement(" in check_text or "def internal_runtime_carrier_is_warning(" in check_text:
    raise SystemExit("runtime-carrier name policy must have one source of truth")
replacement_call = "InternalRuntimeCarrierPolicy::runtime_carrier_replacement(type_name)"
if (compact(function_section(check_text, "irc_push")).count(compact(replacement_call)) != 1 or
        compact(function_section(check_text, "check_internal_runtime_carrier_declarations")).count(compact(replacement_call)) != 1):
    raise SystemExit("AST and extern diagnostic producers must both delegate to the replacement policy")
ast_emission = compact('table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.InternalRuntimeCarrier, name: type_name, line: pos.line, pos: pos, expected: replacement, actual: ""}) if replacement != ""')
extern_emission = compact('table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.InternalRuntimeCarrier, name: type_name, line: line.line, expected: replacement, actual: ""}) if replacement != ""')
if ast_emission not in compact(function_section(check_text, "irc_push")):
    raise SystemExit("AST carrier diagnostic must be emitted iff the policy replacement is nonempty")
if extern_emission not in compact(function_section(check_text, "check_internal_runtime_carrier_declarations")):
    raise SystemExit("extern carrier diagnostic must be emitted iff the policy replacement is nonempty")

severity_text = SEVERITY.read_text()
message_text = MESSAGE.read_text()
if "InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)" not in compact(severity_text):
    raise SystemExit("diagnostic severity must delegate warning classification to the proved policy")
if compact("DiagnosticKind.InternalRuntimeCarrier: SemanticDiagnosticSeverity::WARNING") not in compact(severity_text):
    raise SystemExit("warning-policy values must remain warnings after the severity error override")
if "InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)" not in compact(message_text):
    raise SystemExit("diagnostic wording must delegate warning-prefix selection to the proved policy")
if compact('push_str(buffer, "warning: ") if InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)') not in compact(message_text):
    raise SystemExit("warning carrier names must receive the source-compatible message prefix")
if "internal_runtime_carrier_is_warning" in severity_text + message_text:
    raise SystemExit("diagnostic consumers retain an unproved duplicate warning policy")

semantic_text = SEMANTIC.read_text()
policy_include = 'include "./internal_runtime_carrier_policy.elisa"'
checker_include = 'include "./check_internal_runtime_carrier.elisa"'
if semantic_text.count(policy_include) != 1 or semantic_text.count(checker_include) != 1:
    raise SystemExit("semantic pipeline must include the policy and carrier checker exactly once")
if semantic_text.index(policy_include) > semantic_text.index(checker_include):
    raise SystemExit("semantic checker must be compiled after the carrier policy module")


def validate_routing(check_text_value: str, severity_value: str, message_value: str) -> None:
    ast_body = compact(function_section(check_text_value, "irc_push"))
    extern_body = compact(function_section(check_text_value, "check_internal_runtime_carrier_declarations"))
    if ast_body.count(compact(replacement_call)) != 1 or extern_body.count(compact(replacement_call)) != 1:
        raise SystemExit("carrier producer routing changed")
    if ast_emission not in ast_body or extern_emission not in extern_body:
        raise SystemExit("carrier producer emission gate changed")
    compact_severity = compact(severity_value)
    compact_message = compact(message_value)
    if "InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)" not in compact_severity:
        raise SystemExit("severity routing changed")
    if compact("DiagnosticKind.InternalRuntimeCarrier: SemanticDiagnosticSeverity::WARNING") not in compact_severity:
        raise SystemExit("severity fallback changed")
    if "InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)" not in compact_message:
        raise SystemExit("message routing changed")
    if compact('push_str(buffer, "warning: ") if InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)') not in compact_message:
        raise SystemExit("message prefix routing changed")


for mutation_name, check_mutated, severity_mutated, message_mutated in (
    ("producer policy call", check_text.replace("InternalRuntimeCarrierPolicy::runtime_carrier_replacement(type_name)", "type_name", 1), severity_text, message_text),
    ("producer nonempty gate", check_text.replace('}) if replacement != ""', '})', 1), severity_text, message_text),
    ("severity classifier", check_text, severity_text.replace("InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)", "true", 1), message_text),
    ("severity warning arm", check_text, re.sub(r"(DiagnosticKind\.InternalRuntimeCarrier:\s*SemanticDiagnosticSeverity::)WARNING", r"\1ERROR", severity_text, count=1), message_text),
    ("message classifier", check_text, severity_text, message_text.replace("InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)", "false", 1)),
    ("message warning prefix", check_text, severity_text, message_text.replace('push_str(buffer, "warning: ") if InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)', 'push_str(buffer, "error: ") if InternalRuntimeCarrierPolicy::is_warning(diagnostic.name)', 1)),
):
    try:
        validate_routing(check_mutated, severity_mutated, message_mutated)
    except SystemExit:
        pass
    else:
        raise SystemExit(f"carrier-policy mutation escaped the source checker: {mutation_name}")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("runtime-carrier proof declaration inventory changed")
if f'include "../../src/semantic/{POLICY.name}"' not in POSITIVE.read_text():
    raise SystemExit("positive proof must include the production carrier policy module")
if 'include "./internal_runtime_carrier_policy.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("rejected claims must include the production carrier policy proof")

positive_shapes = {
    "source_replacement_policy_is_the_exact_closed_table": '''def source_replacement_policy_is_the_exact_closed_table(type_name: sview) -> bool can[Abort.Panic]:
        ensure result == true
        can Abort.Panic:
            return InternalRuntimeCarrierPolicy::runtime_carrier_replacement(type_name) == (
                when type_name:
                    "StringView" -> "sview[...]"
                    "DynArray" -> "darray[T, shape]"
                    "DynArrayView" -> "view[T]"
                    "DynDict" -> "dict[K, V]"
                    "Arena" -> "region scopes and inferred container regions"
                    "ArenaMark" -> "region scopes/checkpoints"
                    _ -> ""
            )''',
    "all_carrier_replacement_rows_are_exact": '''def all_carrier_replacement_rows_are_exact() -> bool can[Abort.Panic]:
        ensure result == true
        can Abort.Panic:
            return (
                InternalRuntimeCarrierPolicy::runtime_carrier_replacement("StringView") == "sview[...]"
                and InternalRuntimeCarrierPolicy::runtime_carrier_replacement("DynArray") == "darray[T, shape]"
                and InternalRuntimeCarrierPolicy::runtime_carrier_replacement("DynArrayView") == "view[T]"
                and InternalRuntimeCarrierPolicy::runtime_carrier_replacement("DynDict") == "dict[K, V]"
                and InternalRuntimeCarrierPolicy::runtime_carrier_replacement("Arena") == "region scopes and inferred container regions"
                and InternalRuntimeCarrierPolicy::runtime_carrier_replacement("ArenaMark") == "region scopes/checkpoints"
            )''',
    "emission_gate_matches_the_closed_carrier_set": '''def emission_gate_matches_the_closed_carrier_set(type_name: sview) -> bool can[Abort.Panic]:
        ensure result == true
        can Abort.Panic:
            return (InternalRuntimeCarrierPolicy::runtime_carrier_replacement(type_name) != "") == (
                when type_name:
                    "StringView" | "DynArray" | "DynArrayView" | "DynDict" | "Arena" | "ArenaMark" -> true
                    _ -> false
            )''',
    "unmapped_names_use_the_empty_fallback": '''def unmapped_names_use_the_empty_fallback(type_name: sview) -> bool can[Abort.Panic]:
        requires type_name != "StringView" and type_name != "DynArray" and type_name != "DynArrayView" and type_name != "DynDict" and type_name != "Arena" and type_name != "ArenaMark"
        ensure result == true
        can Abort.Panic:
            return InternalRuntimeCarrierPolicy::runtime_carrier_replacement(type_name) == ""''',
    "source_warning_policy_is_exactly_the_arena_pair": '''def source_warning_policy_is_exactly_the_arena_pair(type_name: sview) -> bool can[Abort.Panic]:
        ensure result == true
        can Abort.Panic:
            return InternalRuntimeCarrierPolicy::is_warning(type_name) == (type_name == "Arena" or type_name == "ArenaMark")''',
    "both_arena_carriers_are_warnings": '''def both_arena_carriers_are_warnings() -> bool can[Abort.Panic]:
        ensure result == true
        can Abort.Panic:
            return InternalRuntimeCarrierPolicy::is_warning("Arena") and InternalRuntimeCarrierPolicy::is_warning("ArenaMark")''',
    "error_carriers_and_unmapped_names_are_not_warnings": '''def error_carriers_and_unmapped_names_are_not_warnings(type_name: sview) -> bool can[Abort.Panic]:
        requires type_name != "StringView" and type_name != "DynArray" and type_name != "DynArrayView" and type_name != "DynDict" and type_name != "Arena" and type_name != "ArenaMark"
        ensure result == true
        can Abort.Panic:
            return (
                not InternalRuntimeCarrierPolicy::is_warning("StringView")
                and not InternalRuntimeCarrierPolicy::is_warning("DynArray")
                and not InternalRuntimeCarrierPolicy::is_warning("DynArrayView")
                and not InternalRuntimeCarrierPolicy::is_warning("DynDict")
                and not InternalRuntimeCarrierPolicy::is_warning(type_name)
            )''',
}
negative_shapes = {
    "string_view_has_no_replacement": '''def string_view_has_no_replacement() -> bool can[Abort.Panic]:
        ensure result == true
        can Abort.Panic:
            return InternalRuntimeCarrierPolicy::runtime_carrier_replacement("StringView") == ""''',
    "dynamic_array_uses_a_view_replacement": '''def dynamic_array_uses_a_view_replacement() -> bool can[Abort.Panic]:
        ensure result == true
        can Abort.Panic:
            return InternalRuntimeCarrierPolicy::runtime_carrier_replacement("DynArray") == "view[T]"''',
    "an_unmapped_name_can_emit_a_carrier_finding": '''def an_unmapped_name_can_emit_a_carrier_finding(type_name: sview) -> bool can[Abort.Panic]:
        requires type_name != "StringView" and type_name != "DynArray" and type_name != "DynArrayView" and type_name != "DynDict" and type_name != "Arena" and type_name != "ArenaMark"
        ensure result == true
        can Abort.Panic:
            return InternalRuntimeCarrierPolicy::runtime_carrier_replacement(type_name) != ""''',
    "arena_mark_is_not_a_warning": '''def arena_mark_is_not_a_warning() -> bool can[Abort.Panic]:
        ensure result == true
        can Abort.Panic:
            return not InternalRuntimeCarrierPolicy::is_warning("ArenaMark")''',
    "an_unmapped_name_is_a_warning": '''def an_unmapped_name_is_a_warning(type_name: sview) -> bool can[Abort.Panic]:
        requires type_name != "StringView" and type_name != "DynArray" and type_name != "DynArrayView" and type_name != "DynDict" and type_name != "Arena" and type_name != "ArenaMark"
        ensure result == true
        can Abort.Panic:
            return InternalRuntimeCarrierPolicy::is_warning(type_name)''',
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    proof_text = path.read_text()
    for name, expected in shapes.items():
        if compact(function_section(proof_text, name)) != compact(expected):
            raise SystemExit(f"{name} no longer states the admitted runtime-carrier proof claim")

proof_inputs = [POSITIVE, NEGATIVE, CHECK, SEVERITY, MESSAGE, SEMANTIC]
source_closure = source_include_closure(proof_inputs)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("runtime-carrier policy proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", *source_closure,
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
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert POSITIVE_NAMES <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "all six replacement mappings, empty fallback, and exact Arena/ArenaMark warning classification, bound to production consumers",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
