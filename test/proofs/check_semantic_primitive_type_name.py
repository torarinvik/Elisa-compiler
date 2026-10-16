"""Admit the source-linked semantic primitive-name policy proof."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true")
args = argument_parser.parse_args()


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/primitive_type_name_policy.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
RESOLVE = ROOT / "src/semantic/resolve_struct_layout.elisa"
SHADOW_CHECK = ROOT / "src/semantic/check_def_shadows_builtin.elisa"
POSITIVE = HERE / "semantic_primitive_type_name.elisa"
NEGATIVE = HERE / "semantic_primitive_type_name_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def match_literals(body: str, description: str, fallback: str) -> list[str]:
    match = re.search(r"return match name:\s*\n(.*)", body, re.DOTALL)
    if match is None:
        raise SystemExit(f"{description} lost its exhaustive name match")
    lines = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    literals: list[str] = []
    for line in lines:
        arm = re.fullmatch(r'("[^"\\]+"(?:\s*\|\s*"[^"\\]+")*): true', line)
        if arm:
            literals.extend(re.findall(r'"([^"\\]+)"', arm.group(1)))
        elif line == f"_: {fallback}":
            if line != lines[-1]:
                raise SystemExit(f"{description} has arms after its fallback")
        else:
            raise SystemExit(f"{description} contains an unexpected match arm: {line}")
    if not lines or lines[-1] != f"_: {fallback}":
        raise SystemExit(f"{description} lost its exact fallback")
    return literals


fixed_names = (
    "i8", "i16", "i32", "i64", "int", "isize", "u8", "u16", "u32", "u64", "usize", "uintptr",
    "f32", "f64", "bool", "char", "void", "cstr", "dstr", "sview", "bitset", "bitfield",
)
builtin_scalar_names = (
    "i8", "i16", "i32", "i64", "int", "isize", "u8", "u16", "u32", "u64", "usize", "uintptr",
    "f16", "f32", "f64", "bool", "char",
)
policy_text = POLICY.read_text()
policy_compact = compact(policy_text)
expected_constants = {
    "INT_PREFIX_LENGTH": "1",
    "MIN_INT_NAME_LENGTH": "INT_PREFIX_LENGTH + 1",
    "INT_LEAD_INDEX": "0",
    "INDEX_STEP": "1",
    "ASCII_LOWER_I": "105",
    "ASCII_LOWER_U": "117",
    "ASCII_DIGIT_ZERO": "48",
    "ASCII_DIGIT_NINE": "57",
}
for name, value in expected_constants.items():
    if compact(f"const {name}: usize = {value}") not in policy_compact and \
            compact(f"const {name}: u8 = {value}") not in policy_compact:
        raise SystemExit(f"primitive-name policy changed constant {name}")

digit = compact(function_section(policy_text, "is_ascii_digit"))
if compact("ensure result == (byte >= ASCII_DIGIT_ZERO and byte <= ASCII_DIGIT_NINE)") not in digit or \
        compact("return byte >= ASCII_DIGIT_ZERO and byte <= ASCII_DIGIT_NINE") not in digit:
    raise SystemExit("ASCII digit helper no longer matches its closed byte interval")

shape = compact(function_section(policy_text, "is_bit_width_int_shape"))
shape_spec = "name.len >= MIN_INT_NAME_LENGTH and (name[INT_LEAD_INDEX] == ASCII_LOWER_I or name[INT_LEAD_INDEX] == ASCII_LOWER_U) and (forall digit_index in INT_PREFIX_LENGTH..<name.len: is_ascii_digit(name[digit_index]))"
if compact("ensure result == (" + shape_spec + ")") not in shape or \
        compact("return " + shape_spec) not in shape:
    raise SystemExit("total width-name shape no longer returns its contract-safe lexical specification")

bit_width = compact(function_section(policy_text, "is_bit_width_int"))
for required in (
    "ensure result == is_bit_width_int_shape(name)",
    "return is_bit_width_int_shape(name)",
):
    if compact(required) not in bit_width:
        raise SystemExit(f"bit-width spelling checker lost its contract-bound specification: {required}")

primitive = function_section(policy_text, "is_primitive_type")
if match_literals(primitive, "primitive type policy", "is_bit_width_int(name)") != list(fixed_names):
    raise SystemExit("primitive type match differs from the ordered closed source-level set")
if compact("ensure when name: " + " | ".join(f'"{name}"' for name in fixed_names) +
            " -> result == true _ -> result == is_bit_width_int_shape(name)") not in compact(primitive):
    raise SystemExit("primitive type contract differs from the production fixed-name match")

builtin_scalar = function_section(policy_text, "is_builtin_scalar_type_name")
if match_literals(builtin_scalar, "builtin scalar type policy", "is_bit_width_int(name)") != list(builtin_scalar_names):
    raise SystemExit("builtin scalar match differs from the exact Stage0 shadow-warning name set")
if compact("ensure when name: " + " | ".join(f'"{name}"' for name in builtin_scalar_names) +
            " -> result == true _ -> result == is_bit_width_int_shape(name)") not in compact(builtin_scalar):
    raise SystemExit("builtin scalar postcondition differs from its closed match policy")

semantic = SEMANTIC.read_text()
module_include = 'include "./primitive_type_name_policy.elisa"'
resolve_include = 'include "./resolve_struct_layout.elisa"'
shadow_include = 'include "./check_def_shadows_builtin.elisa"'
if module_include not in semantic or resolve_include not in semantic or shadow_include not in semantic or \
        semantic.index(module_include) > semantic.index(resolve_include) or \
        semantic.index(module_include) > semantic.index(shadow_include):
    raise SystemExit("semantic facade must import the primitive-name policy before its resolver")
if compact(function_section(RESOLVE.read_text(), "is_primitive_type")) != compact("""
def is_primitive_type(name: sview) -> bool:
    can Abort.Panic:
        return SemanticPrimitiveTypeName::is_primitive_type(name)
"""):
    raise SystemExit("struct-layout resolution no longer delegates primitive classification to the proved policy")
unresolved_type = compact(function_section(RESOLVE.read_text(), "is_unresolved_type"))
if compact("return false if: name.len == 1 is_primitive_type(name) is_registered_type(name, table)") not in unresolved_type:
    raise SystemExit("unresolved-type classification no longer consumes the proved primitive-name policy")
shadow_walk = compact(function_section(SHADOW_CHECK.read_text(), "def_shadows_builtin_walk"))
if compact('if SemanticPrimitiveTypeName::is_builtin_scalar_type_name(function_name)') not in shadow_walk:
    raise SystemExit("builtin-shadow diagnostics no longer consume the proved scalar-name policy")

positive_names = {
    "bit_width_spelling_matches_the_exact_lexical_spec",
    "primitive_classifier_matches_its_closed_match_contract",
    "builtin_scalar_name_classifier_matches_closed_match_contract",
    "every_fixed_builtin_scalar_head_is_recognized",
    "arbitrary_width_builtin_scalar_function_names_are_recognized",
    "every_fixed_primitive_head_is_recognized",
    "decimal_width_spellings_are_syntactically_recognized",
    "malformed_or_unrelated_names_are_not_primitive",
}
negative_names = {
    "ordinary_named_type_is_primitive",
    "malformed_bit_width_suffix_is_accepted",
    "single_prefix_is_a_complete_bit_width_name",
    "fixed_integer_head_is_not_primitive",
    "non_scalar_primitive_is_a_builtin_scalar",
    "unsigned_alias_is_a_builtin_scalar",
    "malformed_builtin_width_is_accepted",
}
for path, expected, label in ((POSITIVE, positive_names, "positive"), (NEGATIVE, negative_names, "negative")):
    if declaration_names(path) != expected:
        raise SystemExit(f"{label} proof inventory changed")
if 'include "../../src/semantic/primitive_type_name_policy.elisa"' not in POSITIVE.read_text() or \
        'include "./semantic_primitive_type_name.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("positive and negative proofs must include the production policy and each other")

if args.source_only:
    print(f"source_bound=True positive={len(positive_names)} false_controls={len(negative_names)}")
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("semantic primitive-name proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
          stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", POLICY,
          SEMANTIC, RESOLVE, SHADOW_CHECK, POSITIVE, NEGATIVE,
          *source_include_closure([POSITIVE, NEGATIVE])]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == replay(POSITIVE)[1], "semantic primitive-name proof changed across repeated runs"
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "closed semantic primitive and builtin scalar names, lexical iN/uN recognition, and builtin-shadow policy wiring",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
