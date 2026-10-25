"""Bind declaration-name proofs to the sealed AST and production accessor."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = argument_parser.parse_args()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
PARSER_TOKENS = ROOT / "src/parser/parser_tokens.elisa"
SYMBOLS_SOURCE = ROOT / "src/semantic/symbols.elisa"
POSITIVE = HERE / "ast_decl_name.elisa"
NEGATIVE = HERE / "ast_decl_name_rejected.elisa"
NAMED_VARIANTS = {"Func", "Struct", "Enum", "Alias", "Law", "Extern", "Const", "Module"}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


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


ast_text = AST_NODES.read_text()
enum_start = ast_text.find("enum Decl is Node:")
enum_end = ast_text.find("enum Pattern is Node:", enum_start)
if enum_start < 0 or enum_end < 0:
    raise SystemExit("sealed AST declaration enum or its pattern boundary disappeared")
variant_rows = []
for line in ast_text[enum_start:enum_end].splitlines():
    match = re.match(r"\s{8}([A-Z][A-Za-z0-9_]*)(?:\((.*)\))?\s*$", line)
    if match:
        variant_rows.append((match.group(1), match.group(2)))
variants = [name for name, _ in variant_rows]
if not variants or set(variants) != NAMED_VARIANTS | {"Invalid", "Import", "Scoped"}:
    raise SystemExit("update the name mapping when the sealed Decl variant inventory changes")

name_source = function_section(AST_SIDE_TABLES.read_text(), "decl_name")
match_markers = list(re.finditer(r"match declaration:", name_source))
if len(match_markers) != 1 or "ensure match declaration:" in name_source:
    raise SystemExit("Ast.decl_name must use one exhaustive implementation match; its mapping is checked by the positive theorem")
implementation_match = name_source[match_markers[0].start():]
implementation_arms = re.findall(r"(?m)^[ \t]*Decl\.([A-Za-z][A-Za-z0-9_]*)\s*(?:\([^\n)]*\))?:", implementation_match)
if implementation_arms != variants:
    raise SystemExit("Ast.decl_name implementation must cover every Decl constructor in declaration order")

for name, fields_text in variant_rows:
    if name in NAMED_VARIANTS:
        implementation_arm = re.search(
            rf"(?m)^[ \t]*Decl\.{name}\(([^)\n]*)\):[ \t]*([A-Za-z_]\w*)\b",
            implementation_match,
        )
        if not implementation_arm:
            raise SystemExit(f"Ast.decl_name must return Decl.{name}'s stored name")
        implementation_fields = [part.strip() for part in implementation_arm.group(1).split(",")]
        first_decl_field = fields_text.split(",", 1)[0].strip() if fields_text else ""
        declared_field_name = first_decl_field.split(":", 1)[0].strip()
        implementation_first_field = implementation_fields[0] if implementation_fields else ""
        if ":" in implementation_first_field:
            implementation_field_name, implementation_binding = (
                part.strip() for part in implementation_first_field.split(":", 1)
            )
        else:
            implementation_field_name = declared_field_name
            implementation_binding = implementation_first_field
        if (not re.search(r":\s*sview(?:\s*@source)?$", first_decl_field) or
                implementation_field_name != declared_field_name or
                implementation_binding != implementation_arm.group(2)):
            raise SystemExit(f"Decl.{name} must select exactly its first, declared-name field")
    else:
        expected_implementation = f"Decl.{name}: sview(\"\", 0, 0)" if name == "Invalid" else f"Decl.{name}(_, _): sview(\"\", 0, 0)"
        if compact(expected_implementation) not in compact(implementation_match):
            raise SystemExit(f"Ast.decl_name must explicitly handle positionless name case Decl.{name}")

if re.search(r"(?m)^[ \t]*_:", implementation_match):
    raise SystemExit("Ast.decl_name must remain exhaustive without a wildcard arm")

expected_member_name_helper = """def module_member_decl_name(declaration: Ast::Decl) -> sview @source:
    ensure result == Ast::decl_name(declaration)
    can Abort.Panic:
        return Ast::decl_name(declaration)"""
if compact(function_section(SYMBOLS_SOURCE.read_text(), "module_member_decl_name")) != compact(expected_member_name_helper):
    raise SystemExit("semantic module-member name lookup must delegate directly to the Ast.decl_name accessor")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "../../src/parser/parser_tokens.elisa"' not in positive_text or \
        'include "./ast_decl_name.elisa"' not in negative_text:
    raise SystemExit("positive and rejected name proofs must share the production AST modules")
POSITIVE_NAMES = {"decl_name_matches_the_owned_name_for_every_variant"}
NEGATIVE_NAMES = {"false_claim_import_name_is_retained"}
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("declaration-name proof declaration inventory changed")

theorem = function_section(positive_text, "decl_name_matches_the_owned_name_for_every_variant")
proof_arms = re.findall(r"(?m)^[ \t]*Decl\.([A-Za-z][A-Za-z0-9_]*)\s*(?:\([^\n)]*\))?:", theorem)
if proof_arms != variants or "Ast::decl_name(declaration)" not in theorem:
    raise SystemExit("universal declaration-name theorem must cover every Decl constructor and call Ast.decl_name")
for name, _ in variant_rows:
    if name in NAMED_VARIANTS:
        arm = re.search(
            rf"(?m)^[ \t]*Decl\.{name}\(([^)\n]*)\):[ \t]*\n[ \t]*return actual == source_name\b",
            theorem,
        )
        fields = [part.strip() for part in arm.group(1).split(",")] if arm else []
        if not fields or fields[0] != "source_name":
            raise SystemExit(f"Decl.{name} theorem must compare Ast.decl_name with its payload name")
    else:
        arm = re.search(
            rf"(?m)^[ \t]*Decl\.{name}(?:\([^\n)]*\))?:[ \t]*\n[ \t]*return actual == sview\(\"\", 0, 0\)",
            theorem,
        )
        if not arm:
            raise SystemExit(f"Decl.{name} theorem must prove the empty-name sentinel")

expected_negative = """def false_claim_import_name_is_retained() -> bool:
    ensure result == true
    declaration: Decl = Decl.Import(sview("module", 0, 6), Pos{line: 1, column: 0, offset: 0, end_line: 1, end_column: 0, end_offset: 0})
    actual: sview = Ast::decl_name(declaration)
    return actual == sview("module", 0, 6)"""
if compact(function_section(negative_text, "false_claim_import_name_is_retained")) != compact(expected_negative):
    raise SystemExit("rejected control must falsely claim that an import's module text is its declared name")

if ARGS.source_only:
    print(json.dumps({"source_bound": True, "variants": len(variants), "positive_claims": len(POSITIVE_NAMES)}))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error

inputs = [
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    Path(__file__),
    HERE / "proof_product_gate.py",
    AST_NODES,
    AST_SIDE_TABLES,
    PARSER_TOKENS,
    SYMBOLS_SOURCE,
    POSITIVE,
    NEGATIVE,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(NEGATIVE_NAMES) == negative["summary"]["obligations"]
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}
assert NEGATIVE_NAMES.isdisjoint({row["name"] for row in negative["declaration_details"] if row.get("verified")})

product_after = require_current_product(BIN, PROVER)
assert product_after == product, "proof-product manifest changed during replay"
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}, \
    "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "all declaration variants preserve the declared-name mapping",
    "positive_obligations": positive["summary"]["proven"],
    "independently_replayed": positive["replay"]["replayed"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
