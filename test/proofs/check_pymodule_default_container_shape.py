"""Replay source-linked proofs of the PyModule default container classifiers."""
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
POSITIVE = HERE / "pymodule_default_container_shape.elisa"
NEGATIVE = HERE / "pymodule_default_container_shape_rejected.elisa"
POLICY = ROOT / "src/driver/elisac_pymodule_default_container_shape_policy.elisa"
DEFAULT_POLICY = ROOT / "src/driver/elisac_pymodule_default_policy.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
PARSER_TOKENS = ROOT / "src/parser/parser_tokens.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

POSITIVE_NAMES = {
    "empty_container_classifier_matches_ast_shape",
    "container_classifier_matches_ast_shape",
    "an_empty_container_literal_is_a_container",
    "empty_array_is_empty_and_is_a_container",
    "empty_dictionary_is_empty_and_is_a_container",
    "empty_set_is_empty_and_is_a_container",
    "a_construct_is_a_container_but_not_an_empty_literal",
    "an_integer_literal_is_not_a_container",
}
EXPECTED_VERIFIED = POSITIVE_NAMES | {"is_empty_container", "is_container"}
NEGATIVE_NAMES = {
    "a_nonempty_array_is_an_empty_literal",
    "a_construct_is_not_a_container",
    "an_integer_literal_is_an_empty_container",
}
REQUIRED_CALLERS = {
    "elisac_pymodule_default_builder.elisa": ("pymodule_default_is_container(",),
    "elisac_pymodule_c_function_2.elisa": (
        "pymodule_default_is_container(", "pymodule_default_is_empty_container(",
    ),
    "elisac_pymodule_struct_py_to_c.elisa": (
        "pymodule_default_is_container(", "pymodule_default_is_empty_container(",
    ),
    "elisac_pymodule_cleanup.elisa": ("pymodule_default_is_container(",),
    "elisac_pymodule_c_report.elisa": (
        "pymodule_default_is_container(", "pymodule_default_is_empty_container(",
    ),
    "elisac_pymodule_dict_input.elisa": ("pymodule_default_is_container(",),
    "elisac_pymodule_set_input.elisa": ("pymodule_default_is_container(",),
}


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def function_section(source: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def\s+{re.escape(name)}(?=\[|\()", source)
    if not match:
        raise SystemExit(f"missing source or proof declaration: {name}")
    following = re.search(r"(?m)^\s*(?:def\s+|public:|private:|module\s+|extend\s+)", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def enum_variants(source: str, label: str) -> dict[str, tuple[str, ...]]:
    start = re.search(r"(?m)^(?P<indent> *)enum Expr is Node:\s*$", source)
    if not start:
        raise ValueError(f"{label} has no `enum Expr is Node` declaration")
    tail = source[start.end():]
    indentation = len(start.group("indent"))
    end = re.search(rf"(?m)^ {{{indentation}}}(?:def|enum|struct|const enum|extend)\s+", tail)
    body = tail[:end.start()] if end else tail
    variants: dict[str, tuple[str, ...]] = {}
    for line in body.splitlines():
        match = re.fullmatch(rf" {{{indentation + 4}}}([A-Z][A-Za-z0-9_]*)(?:\((.*)\))?\s*", line)
        if not match:
            continue
        name, fields_text = match.groups()
        if name in variants:
            raise ValueError(f"{label} repeats expression constructor {name}")
        fields = tuple(part.strip() for part in fields_text.split(",")) if fields_text else ()
        variants[name] = fields
    if not variants:
        raise ValueError(f"{label} has no expression constructors")
    return variants


def struct_fields(source: str, name: str, label: str) -> tuple[str, ...]:
    match = re.search(rf"(?m)^(?P<indent> *)struct\s+{re.escape(name)}:\s*$", source)
    if not match:
        raise ValueError(f"{label} has no {name} struct")
    header_indent = len(match.group("indent"))
    field_indent = header_indent + 4
    fields = []
    for line in source[match.end():].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= header_indent:
            break
        if line_indent != field_indent:
            continue
        field = re.fullmatch(r"\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?:mutable\s+)?([^=\n]+?)(?:\s*=.*)?\s*", line)
        if field:
            fields.append(f"{field.group(1)}: {field.group(2).strip()}")
    return tuple(fields)


def source_projection_errors(
    production_nodes: str,
    production_side_tables: str,
    production_tokens: str,
    projection: str,
) -> list[str]:
    errors: list[str] = []
    try:
        production = enum_variants(production_nodes, "production AST")
        model = enum_variants(projection, "proof AST projection")
        if tuple(production) != tuple(model):
            errors.append("proof AST projection constructor order/set differs from production Ast::Expr")

        # These are the only constructor payloads read by the proved predicates or
        # the concrete witness theorems. Other payloads are intentionally abstracted
        # because both production matches route those constructors to the wildcard.
        relevant_fields = {
            "IntLit": ("value: i64", "pos: Pos"),
            "Ident": ("name: sview", "pos: Pos"),
            "Array": ("elements: darray[Expr]", "pos: Pos"),
            "SetLit": ("elements: darray[Expr]", "pos: Pos"),
            "DictLit": ("entries: darray[DictEntry]", "pos: Pos"),
            "Construct": ("type: Expr", "fields: darray[FieldInit]", "pos: Pos"),
        }
        for name, fields in relevant_fields.items():
            if production.get(name) != fields:
                errors.append(f"production Ast::Expr.{name} payload changed: {production.get(name)}")
            if model.get(name) != fields:
                errors.append(f"proof Ast::Expr.{name} projection differs from its used production payload")

        pos_fields = ("line: u32", "column: u32", "offset: u32", "end_line: u32", "end_column: u32", "end_offset: u32")
        proof_pos = struct_fields(projection, "Pos", "proof AST projection")
        source_pos = struct_fields(production_tokens, "Pos", "production parser tokens")
        if proof_pos != pos_fields or source_pos != pos_fields:
            errors.append("proof/source Pos projection no longer matches the six production coordinate fields")

        dict_entry = ("key: Expr", "value: Expr")
        if struct_fields(projection, "DictEntry", "proof AST projection") != dict_entry or \
                struct_fields(production_side_tables, "DictEntry", "production AST side tables") != dict_entry:
            errors.append("proof DictEntry projection differs from production key/value fields")
        source_field_init = struct_fields(production_side_tables, "FieldInit", "production AST side tables")
        projection_field_init = struct_fields(projection, "FieldInit", "proof AST projection")
        if source_field_init[:2] != ("name: sview", "value: Expr") or \
                projection_field_init != ("name: sview", "value: Expr"):
            errors.append("proof FieldInit projection no longer carries the production name/value fields")
        if len(source_field_init) < 2:
            errors.append("production FieldInit lost its name/value fields")
    except ValueError as error:
        errors.append(str(error))
    return errors


def match_arms(block: str, separator: str, label: str) -> tuple[tuple[str, str], ...]:
    arms = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pattern = rf"(.+?)(?<!:){re.escape(separator)}(?!:)\s*(.+)" if separator == ":" else rf"(.+?)\s*{re.escape(separator)}\s*(.+)"
        match = re.fullmatch(pattern, stripped)
        if not match:
            raise SystemExit(f"malformed {label} arm: {stripped}")
        arms.append((compact(match.group(1)), compact(match.group(2))))
    return tuple(arms)


def match_blocks(function: str, label: str) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    contract = re.search(r"ensure\s+result\s*==\s*\(\s*match expression:\s*\n(.*?)^\s*\)", function, re.DOTALL | re.MULTILINE)
    implementation = re.search(r"return\s+match expression:\s*\n(.*)", function, re.DOTALL)
    if not contract or not implementation:
        raise SystemExit(f"{label} needs an exact match contract and implementation")
    return (match_arms(contract.group(1), ":", f"{label} contract"),
            match_arms(implementation.group(1), ":", f"{label} implementation"))


EXPECTED_EMPTY_ARMS = (
    ("Ast::Expr.Array(elements,_)" , "elements.count==0"),
    ("Ast::Expr.DictLit(entries,_)" , "entries.count==0"),
    ("Ast::Expr.SetLit(elements,_)" , "elements.count==0"),
    ("_", "false"),
)
EXPECTED_CONTAINER_ARMS = (
    ("Ast::Expr.Array(_,_)", "true"),
    ("Ast::Expr.DictLit(_,_)", "true"),
    ("Ast::Expr.SetLit(_,_)", "true"),
    ("Ast::Expr.Construct(_,_,_)", "true"),
    ("_", "false"),
)
EXPECTED_CONTAINER_PROOF_ARMS = (
    ("Ast::Expr.Array(_,_)|Ast::Expr.DictLit(_,_)|Ast::Expr.SetLit(_,_)|Ast::Expr.Construct(_,_,_)", "true"),
    ("_", "false"),
)


def validate_source(
    policy_text: str,
    default_policy_text: str,
    driver_text: str,
    projection_text: str,
    ast_nodes_text: str,
    ast_side_tables_text: str,
    parser_tokens_text: str,
    driver_sources: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    errors.extend(source_projection_errors(ast_nodes_text, ast_side_tables_text, parser_tokens_text, projection_text))
    if 'include "./elisac_pymodule_default_container_shape_policy.elisa"' not in driver_text or \
            'include "./elisac_pymodule_default_policy.elisa"' not in driver_text or \
            driver_text.index('include "./elisac_pymodule_default_container_shape_policy.elisa"') > driver_text.index('include "./elisac_pymodule_default_policy.elisa"'):
        errors.append("compiler driver must include the proved container policy before its consumers")

    for name, expected_arms in (("is_empty_container", EXPECTED_EMPTY_ARMS), ("is_container", EXPECTED_CONTAINER_ARMS)):
        section = function_section(policy_text, name)
        if match_blocks(section, name) != (expected_arms, expected_arms):
            errors.append(f"production {name} contract/implementation differs from its closed AST shape table")
        wrapper = compact(function_section(default_policy_text, f"pymodule_default_{name}"))
        expected_wrapper = compact(
            f"def pymodule_default_{name}(expression: Ast::Expr) -> bool can[Abort.Panic]:\n"
            f"    can Abort.Panic:\n"
            f"        return PymoduleDefaultContainerShapePolicy::{name}(expression)"
        )
        if wrapper != expected_wrapper:
            errors.append(f"production PyModule wrapper for {name} no longer delegates exactly to the proved helper")
        qualified = f"PymoduleDefaultContainerShapePolicy::{name}("
        other_qualified_calls = [path for path, source in driver_sources.items()
                                 if qualified in source and path != "elisac_pymodule_default_policy.elisa"]
        if other_qualified_calls:
            errors.append(f"production callers bypass the checked wrapper for {name}: {other_qualified_calls}")

    for path, required_calls in REQUIRED_CALLERS.items():
        source = driver_sources.get(path, "")
        if not source:
            errors.append(f"required PyModule consumer source is missing: {path}")
            continue
        for call in required_calls:
            if call not in source:
                errors.append(f"{path} no longer routes its default handling through {call[:-1]}")

    proof_text = POSITIVE.read_text()
    negative_text = NEGATIVE.read_text()
    if 'include "../../src/driver/elisac_pymodule_default_container_shape_policy.elisa"' not in proof_text:
        errors.append("positive proof no longer includes the exact production container-shape helper")
    if 'include "./pymodule_default_container_shape.elisa"' not in negative_text:
        errors.append("false-claim controls no longer include the source-linked positive proof")

    positive_names = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", proof_text))
    negative_names = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text))
    if positive_names != POSITIVE_NAMES:
        errors.append(f"positive declaration inventory changed: {sorted(positive_names)}")
    if negative_names != NEGATIVE_NAMES:
        errors.append(f"false-claim declaration inventory changed: {sorted(negative_names)}")

    for name, theorem, expected in (
        ("is_empty_container", "empty_container_classifier_matches_ast_shape", EXPECTED_EMPTY_ARMS),
        ("is_container", "container_classifier_matches_ast_shape", EXPECTED_CONTAINER_PROOF_ARMS),
    ):
        proof_function = function_section(proof_text, theorem)
        body = compact(proof_function)
        if f"PymoduleDefaultContainerShapePolicy::{name}(expression)" not in body:
            errors.append(f"universal {name} theorem no longer exercises the production helper")
        when = re.search(r"when expression:\s*\n(.*?)(?=^\s*\))", proof_function, re.DOTALL | re.MULTILINE)
        if not when or match_arms(when.group(1), "->", f"{name} proof table") != expected:
            errors.append(f"universal {name} theorem no longer states its exact constructor table")

    witness_fragments = {
        "empty_array_is_empty_and_is_a_container": ("Ast::Expr.Array(elements,pos)", "elements:darray[Ast::Expr]=[]", "is_container(expression)"),
        "empty_dictionary_is_empty_and_is_a_container": ("Ast::Expr.DictLit(entries,pos)", "entries:darray[Ast::DictEntry]=[]", "is_container(expression)"),
        "empty_set_is_empty_and_is_a_container": ("Ast::Expr.SetLit(elements,pos)", "elements:darray[Ast::Expr]=[]", "is_container(expression)"),
        "a_construct_is_a_container_but_not_an_empty_literal": ("Ast::Expr.Construct(type_expression,fields,pos)", "is_container(expression)", "notPymoduleDefaultContainerShapePolicy::is_empty_container(expression)"),
        "an_integer_literal_is_not_a_container": ("Ast::Expr.IntLit(TEST_INTEGER,pos)", "notPymoduleDefaultContainerShapePolicy::is_container(expression)", "notPymoduleDefaultContainerShapePolicy::is_empty_container(expression)"),
    }
    for name, fragments in witness_fragments.items():
        body = compact(function_section(proof_text, name))
        if any(fragment not in body for fragment in fragments):
            errors.append(f"positive witness {name} no longer exercises its declared production AST constructor")
    if "PymoduleDefaultContainerShapePolicy::is_empty_container(expression)orPymoduleDefaultContainerShapePolicy::is_container(expression)" not in compact(function_section(proof_text, "an_empty_container_literal_is_a_container")):
        errors.append("empty-container subset theorem no longer states the production implication")

    negative_claims = {
        "a_nonempty_array_is_an_empty_literal": ("elements:darray[Ast::Expr]=[Ast::Expr.IntLit(TEST_INTEGER,pos)]", "returnPymoduleDefaultContainerShapePolicy::is_empty_container(expression)"),
        "a_construct_is_not_a_container": ("Ast::Expr.Construct(type_expression,fields,pos)", "returnnotPymoduleDefaultContainerShapePolicy::is_container(expression)"),
        "an_integer_literal_is_an_empty_container": ("Ast::Expr.IntLit(TEST_INTEGER,pos)", "returnPymoduleDefaultContainerShapePolicy::is_empty_container(expression)"),
    }
    for name, fragments in negative_claims.items():
        body = compact(function_section(negative_text, name))
        if any(fragment not in body for fragment in fragments):
            errors.append(f"false-claim control {name} no longer challenges the intended constructor case")

    return errors


policy_text = POLICY.read_text()
default_policy_text = DEFAULT_POLICY.read_text()
driver_text = DRIVER.read_text()
projection_text = POSITIVE.read_text()
ast_nodes_text = AST_NODES.read_text()
ast_side_tables_text = AST_SIDE_TABLES.read_text()
parser_tokens_text = PARSER_TOKENS.read_text()
driver_sources = {path.name: path.read_text() for path in (ROOT / "src/driver").glob("*.elisa")}
source_errors = validate_source(policy_text, default_policy_text, driver_text, projection_text,
                                ast_nodes_text, ast_side_tables_text, parser_tokens_text, driver_sources)
if source_errors:
    raise SystemExit("\n".join(source_errors))

# Ensure the gate notices stale AST projections and policy drift rather than silently
# certifying an unrelated abstract model.
mutated_projection = projection_text.replace("            SetLit(elements: darray[Expr], pos: Pos)",
                                             "            SetNode(elements: darray[Expr], pos: Pos)", 1)
if mutated_projection == projection_text or not source_projection_errors(
        ast_nodes_text, ast_side_tables_text, parser_tokens_text, mutated_projection):
    raise SystemExit("source projection gate failed to reject a renamed AST constructor")
mutated_policy = policy_text.replace("Ast::Expr.SetLit(elements, _)", "Ast::Expr.Array(elements, _)", 1)
if mutated_policy == policy_text or not validate_source(mutated_policy, default_policy_text, driver_text,
        projection_text, ast_nodes_text, ast_side_tables_text, parser_tokens_text, driver_sources):
    raise SystemExit("source gate failed to reject a changed production container-shape arm")
mutated_callers = dict(driver_sources)
caller_path = next(iter(REQUIRED_CALLERS))
required_call = REQUIRED_CALLERS[caller_path][0]
mutated_callers[caller_path] = mutated_callers[caller_path].replace(required_call, "pymodule_default_container_kind(")
if mutated_callers[caller_path] == driver_sources[caller_path] or not validate_source(
        policy_text, default_policy_text, driver_text, projection_text, ast_nodes_text,
        ast_side_tables_text, parser_tokens_text, mutated_callers):
    raise SystemExit("source gate failed to reject a consumer that bypasses the proved wrapper")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("PyModule container-shape proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    DRIVER, POLICY, DEFAULT_POLICY, AST_NODES, AST_SIDE_TABLES, PARSER_TOKENS,
    *source_closure, *(ROOT / "src/driver").glob("*.elisa"),
]
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
assert positive == run(POSITIVE)[1], "positive proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert EXPECTED_VERIFIED <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
findings = {row["name"]: row["kind"] for row in negative["findings"]}
assert set(findings) == NEGATIVE_NAMES
assert set(findings.values()) == {"ensure-unproven"}
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed Ast::Expr shape of PyModule default container predicates",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
