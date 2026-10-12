"""Replay semantic cache-option construction and stable key-layout contracts."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

root = Path(__file__).resolve().parents[2]
prover = root.parent / "elisa-proof"
binary = Path(os.environ.get("ELISA_PROOF_BIN", str(prover / "build/elisa-proof"))).resolve(strict=True)
if not __debug__:
    raise SystemExit("run without Python -O")
try:
    product_manifest = require_current_product(binary, prover)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
compiler_head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

here = Path(__file__).resolve().parent
manifest = binary.with_name(binary.name + ".manifest.json")
manifest_checksum = manifest.with_name(manifest.name + ".sha256")
types_source = root / "src/semantic/incremental_semantic_options_types.elisa"
module_source = root / "src/semantic/incremental_semantic_options.elisa"
source_view_source = root / "src/lexer/source_view.elisa"
token_model_source = root / "src/lexer/tokens.elisa"
probe_source = root / "src/driver/elisac_source_probes.elisa"
incremental_driver_source = root / "src/driver/elisac_incremental_cache.elisa"
positive_source = here / "incremental_semantic_options.elisa"
negative_source = here / "incremental_semantic_options_rejected.elisa"
inputs = [binary, manifest, manifest_checksum, prover / "ELISA_COMPILER_REV",
          here / "proof_product_gate.py", Path(__file__), types_source, module_source,
          source_view_source, token_model_source,
          probe_source, incremental_driver_source, positive_source, negative_source]
inputs.extend(source_include_closure([positive_source, negative_source]))
hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}

types_text = types_source.read_text()
module_text = module_source.read_text()
positive_text = positive_source.read_text()
negative_text = negative_source.read_text()
probe_text = probe_source.read_text()
incremental_driver_text = incremental_driver_source.read_text()
fields = (
    "enforce_unsafe_permissions", "flow_strict", "runtime_std", "flow_warn",
    "enable_smt", "warn_discarded", "enforce_progress", "enforce_extern_contracts",
    "enforce_raw_unsafe", "emit_proof_hole", "region_stack_cap",
    "enforce_global_permissions", "enforce_mutable_global_grants", "carrier_surface",
)
flag_fields = tuple(field for field in fields if field != "region_stack_cap")


def function_region(source, name):
    match = re.search(rf"^([ \t]*)def {re.escape(name)}\(", source, re.M)
    assert match, f"missing production function {name}"
    end = re.search(rf"^{re.escape(match.group(1))}def ", source[match.end():], re.M)
    return source[match.start():match.end() + end.start()] if end else source[match.start():]


def call_arguments(source, callee):
    matches = list(re.finditer(re.escape(callee) + r"\s*\(", source))
    assert len(matches) == 1, f"expected one call to {callee}, found {len(matches)}"
    opening = source.find("(", matches[0].start())
    depth = 0
    quote = None
    escaped = False
    closing = None
    for index in range(opening, len(source)):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '\"'):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                closing = index
                break
    assert closing is not None, f"unterminated call to {callee}"
    body = source[opening + 1:closing]
    arguments = []
    start = 0
    stack = []
    quote = None
    escaped = False
    closing_for = {")": "(", "]": "[", "}": "{"}
    for index, char in enumerate(body):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '\"'):
            quote = char
        elif char in "([{":
            stack.append(char)
        elif char in ")]}":
            assert stack and stack[-1] == closing_for[char], f"unbalanced delimiters in {callee}"
            stack.pop()
        elif char == "," and not stack:
            arguments.append(body[start:index].strip())
            start = index + 1
    assert not stack and quote is None, f"unbalanced expression in {callee}"
    if body[start:].strip():
        arguments.append(body[start:].strip())
    return tuple(re.sub(r"\s+", "", argument) for argument in arguments)


assert 'include "./incremental_semantic_options_types.elisa"' in module_text
assert 'include "../../src/lexer/tokens.elisa"' in positive_text
assert 'include "../../src/lexer/source_view.elisa"' in positive_text
assert 'include "../../src/semantic/incremental_semantic_options.elisa"' in positive_text
assert 'include "incremental_semantic_options.elisa"' in negative_text
assert "def incremental_semantic_options_from_values(" in types_text
assert "def incremental_semantic_options_flag(" in types_text
assert "Semantic::incremental_semantic_options_from_values(" in positive_text
assert "Semantic::incremental_semantic_options_from_values(" in negative_text
struct_match = re.search(r"struct IncrementalSemanticOptions:\n(.*?)(?:\n\s*\n|\Z)", types_text, re.S)
signature_match = re.search(r"def incremental_semantic_options_from_values\((.*?)\) ->", types_text, re.S)
assert struct_match and signature_match
declared_fields = tuple(re.findall(r"^[ \t]+(\w+): (?:bool|i64)$", struct_match.group(1), re.M))
parameters = tuple(re.findall(r"(\w+): (?:bool|i64)", signature_match.group(1)))
assert declared_fields == fields
assert parameters == fields
constructor_text = function_region(types_text, "incremental_semantic_options_from_values")
constructor_contracts = tuple(re.findall(
    r"^[ \t]+ensure result\.(\w+) == (\w+)$", constructor_text, re.M))
assert constructor_contracts == tuple((field, field) for field in fields)
flag_contracts = tuple(re.findall(
    r"^[ \t]+ensure index != (\d+) or result == \(1 if options\.(\w+) else 0\)$",
    function_region(types_text, "incremental_semantic_options_flag"), re.M))
assert flag_contracts == tuple((str(index), field) for index, field in enumerate(flag_fields))
assert "ensure index < 13 or result == 0" in function_region(
    types_text, "incremental_semantic_options_flag")
for field in fields:
    assert f"ensure result.{field} == {field}" in types_text, f"missing constructor contract for {field}"
    assert f"return false if options.{field} != {field}" in positive_text, f"proof omits constructor field {field}"
for index, field in enumerate(flag_fields):
    assert (f"return false if Semantic::incremental_semantic_options_flag(options, {index}) != "
            f"(1 if options.{field} else 0)") in positive_text, f"proof omits flag index {index}"
assert "incremental_semantic_options_flag(options, 13) != 0" in positive_text
assert sum(line.lstrip().startswith("ensure ") for line in constructor_text.splitlines()) == len(fields)
flag_assignment_rows = tuple(re.findall(
    r"^[ \t]+flags\[(\d+)\] <- incremental_semantic_options_flag\(options, (\d+)\)$",
    module_text, re.M))
assert flag_assignment_rows == tuple((str(index), str(index)) for index in range(len(flag_fields)))

cap_assignments = tuple(re.sub(r"\s+", "", line.strip()) for line in module_text.splitlines()
                        if re.match(r"^[ \t]+cap\[\d+\] <-", line))
expected_cap_assignments = tuple(
    f"cap[{index}]<-((options.region_stack_cap>>{8 * index})&255).u8()" if index else
    "cap[0]<-(options.region_stack_cap&255).u8()"
    for index in range(8)
)
assert cap_assignments == expected_cap_assignments
assert "const INCREMENTAL_SEMANTIC_OPTIONS_KEY_LENGTH: usize = 26" in module_text
assert "return output.count == INCREMENTAL_SEMANTIC_OPTIONS_KEY_LENGTH" in module_text
assert "for index in 0..<13:" in module_text
assert "return false if key[5 + index] > 1" in module_text
assert "for index in 0..<INCREMENTAL_SEMANTIC_OPTIONS_KEY_LENGTH:" in module_text
assert "return false if left[index] != right[index]" in module_text

# Bind the constructor's positional inputs to the source-derived options used by
# the driver, then bind every record field to semantic analysis and the cache key.
source_option_args = (
    "source_has_strict_header(src_ptr,source_len)", "false",
    "runtime_std_enabled(src_ptr,source_len)", "false",
    "env_flag_enabled(\"ELISA_STAGE1_SMT\")orsource_has_smt_header(src_ptr,source_len)",
    "false", "false",
    "env_flag_enabled(\"ELISA_STAGE1_STRICT_EXTERNS\")orsource_has_header(src_ptr,source_len,\"strict-externs\")",
    "source_has_unsafe_header(src_ptr,source_len)",
    "source_has_proofhole_header(src_ptr,source_len)", "64",
    "source_has_global_header(src_ptr,source_len)", "notpermissive",
    "carrier_surface_applies()",
)
stage1_options = function_region(probe_text, "stage1_semantic_options")
assert call_arguments(stage1_options, "Semantic::incremental_semantic_options_from_values") == source_option_args
analysis_gate = function_region(probe_text, "run_semantic_gate_with_snapshot")
analysis_args = call_arguments(
    analysis_gate, "Semantic::check_full_diagnostics_with_incremental_snapshot")
expected_analysis_args = (
    "file", "&diagnostics",
    *(f"options.{field}" for field in fields),
    "snapshot", "incremental_skip_count",
)
assert analysis_args == expected_analysis_args
incremental_gate = function_region(incremental_driver_text, "run_semantic_gate_incremental")
compact_incremental_gate = re.sub(r"\s+", "", incremental_gate)
assert "stage1_semantic_options(policy_source,policy_length)" in compact_incremental_gate
assert "Semantic::incremental_semantic_options_fingerprint(options)" in compact_incremental_gate
assert ("run_semantic_gate_with_snapshot(file,policy_source,policy_length,options,"
        "snapshot,&incremental_skip_count)") in compact_incremental_gate


def run(path):
    process = subprocess.run([str(binary), "--json", str(path)],
                             capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(positive_source)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
expected_obligations = len(fields) + len(flag_fields) + 3
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == expected_obligations
assert not positive["findings"]
assert positive == run(positive_source)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {"incremental_semantic_options_from_values",
            "incremental_semantic_options_flag",
            "semantic_options_constructor_preserves_every_field",
            "semantic_options_flag_indices_preserve_all_boolean_fields"}
assert expected <= verified

code, negative = run(negative_source)
false_claims = {"distinct_semantic_flags_remain_distinct",
                "wrong_flag_index_four_is_flow_warn"}
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(false_claims) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == false_claims
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not false_claims & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(binary, prover) == product_manifest, "proof product or source tree changed during replay"
assert subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                      check=True, capture_output=True, text=True).stdout.strip() == compiler_head
print(json.dumps({"admitted": True,
                  "scope": "semantic cache-options construction, driver projection, and key layout",
                  "fields_preserved": list(fields),
                  "flag_key_order": list(flag_fields),
                  "region_stack_cap_encoded_bytes": 8,
                  "producer_proven": positive["summary"]["proven"],
                  "independently_replayed": positive["replay"]["replayed"],
                  "false_claims_rejected": sorted(false_claims),
                  "sources_sha256": hashes}, sort_keys=True))
