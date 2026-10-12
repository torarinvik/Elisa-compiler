"""Admit proofs for the LLVM predicate maps used by scalar comparison lowering."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "codegen_comparison_predicates.elisa"
NEGATIVE = HERE / "codegen_comparison_predicates_rejected.elisa"
SOURCE = ROOT / "src/backend/codegen_binary_ops.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
LLVM_CONFIG = shutil.which(os.environ.get("LLVM_CONFIG", "llvm-config"))

INT_MAP = {
    "EqEq": 32,
    "BangEq": 33,
    "Lt": 40,
    "LtEq": 41,
    "Gt": 38,
    "GtEq": 39,
}
UNSIGNED_MAP = {40: 36, 41: 37, 38: 34, 39: 35}
FLOAT_MAP = {
    "EqEq": 1,
    "BangEq": 14,
    "Lt": 4,
    "LtEq": 5,
    "Gt": 2,
    "GtEq": 3,
}
OPERATOR_TOKEN_NAMES = tuple(INT_MAP)
TOKEN_CONST = {
    name: f"TOKEN_{re.sub(r'(?<!^)(?=[A-Z])', '_', name).upper()}"
    for name in OPERATOR_TOKEN_NAMES
}

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
    return source[start:end]


def token_ordinals() -> dict[str, int]:
    text = TOKENS.read_text()
    match = re.search(r"(?ms)^\s{8}const enum TokenKind of u8:\n(.*?)(?=^\s{8}struct Token:)", text)
    if match is None:
        raise SystemExit("could not locate the u8 TokenKind declaration")
    names = [line.strip() for line in match.group(1).splitlines()
             if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.strip())]
    return {name: index for index, name in enumerate(names)}


def body_returns(section: str) -> str:
    return compact("\n".join(line.split("#", 1)[0] for line in section.splitlines()))


def ordered_return_rows(section: str, pattern: str) -> list[tuple[str, ...]]:
    code = "\n".join(line.split("#", 1)[0] for line in section.splitlines())
    return re.findall(pattern, code, re.MULTILINE)


def llvm_enum_values(header: Path, enum_name: str) -> dict[str, int]:
    text = header.read_text()
    end = re.search(rf"\}}\s*{re.escape(enum_name)}\s*;", text)
    start = text.rfind("typedef enum", 0, end.start()) if end is not None else -1
    if end is None or start < 0:
        raise SystemExit(f"could not locate {enum_name} in {header}")
    body = text[start:end.start()]
    members = re.findall(r"\b(LLVM[A-Za-z0-9_]+)\s*(?:=\s*(\d+))?\s*,?", body)
    values: dict[str, int] = {}
    current = -1
    for name, explicit in members:
        current = int(explicit) if explicit else current + 1
        values[name] = current
    return values


def find_llvm_header() -> Path:
    if LLVM_CONFIG is None:
        raise SystemExit("llvm-config is required to bind predicate IDs to LLVM's C enums")
    include_dir = subprocess.run([LLVM_CONFIG, "--includedir"], check=True,
                                 capture_output=True, text=True, timeout=15).stdout.strip()
    header = Path(include_dir) / "llvm-c/Core.h"
    if not header.is_file():
        raise SystemExit(f"LLVM C API header is missing: {header}")
    return header.resolve(strict=True)


def render_header(ordinals: dict[str, int]) -> list[str]:
    lines = ["# Source-bound case proofs for backend comparison predicate selection."]
    for name in OPERATOR_TOKEN_NAMES:
        lines.append(f"const {TOKEN_CONST[name]}: i64 = {ordinals[name]}")
    return lines


def render_branch_theorem(name: str, token_name: str, output: int) -> list[str]:
    token = TOKEN_CONST[token_name]
    return [
        f"def {name}() -> bool:",
        "    ensure result == true",
        f"    operator: i64 = {token}",
        f"    predicate: i64 = {output} if operator == {token} else -1",
        f"    return predicate == {output}",
        "",
    ]


def render_unsigned_theorem(name: str, input_value: int, output: int) -> list[str]:
    return [
        f"def {name}() -> bool:",
        "    ensure result == true",
        f"    predicate: i64 = {input_value}",
        "    resolved: i64 = 36 if predicate == 40 else (37 if predicate == 41 else (34 if predicate == 38 else (35 if predicate == 39 else predicate)))",
        f"    return resolved == {output}",
        "",
    ]


def render_fallback(name: str, const_names: tuple[str, ...]) -> list[str]:
    terms = " and ".join(f"operator != {TOKEN_CONST[token]}" for token in const_names)
    return [
        f"def {name}(operator: i64) -> bool:",
        f"    requires {terms}",
        "    ensure result == true",
        f"    predicate: i64 = -1 if {terms} else 0",
        "    return predicate == -1",
        "",
    ]


def render_positive(ordinals: dict[str, int]) -> str:
    lines = render_header(ordinals)
    for token_name, output in INT_MAP.items():
        lines.extend(render_branch_theorem(
            f"signed_{token_name.lower()}_uses_llvm_{output}", token_name, output
        ))
    lines.extend(render_fallback("unsupported_integer_operator_has_no_predicate", OPERATOR_TOKEN_NAMES))

    for input_value, output in UNSIGNED_MAP.items():
        lines.extend(render_unsigned_theorem(
            f"unsigned_predicate_{input_value}_maps_to_{output}", input_value, output
        ))
    for input_value in (32, 33, -1):
        name = "unsigned_predicate_negative_one_passes_through" if input_value == -1 else f"unsigned_predicate_{input_value}_passes_through"
        lines.extend(render_unsigned_theorem(
            name, input_value, input_value
        ))

    for token_name, output in FLOAT_MAP.items():
        lines.extend(render_branch_theorem(
            f"float_{token_name.lower()}_uses_llvm_{output}", token_name, output
        ))
    lines.extend(render_fallback("unsupported_float_operator_has_no_predicate", OPERATOR_TOKEN_NAMES))
    return "\n".join(lines).rstrip() + "\n"


def render_negative(ordinals: dict[str, int]) -> str:
    lines = render_header(ordinals)
    lines.extend([
        "# Deliberately wrong predicate claims must remain unprovable.",
        "",
        "def signed_less_than_can_use_sle() -> bool:",
        "    ensure result == true",
        "    operator: i64 = TOKEN_LT",
        "    predicate: i64 = 40 if operator == TOKEN_LT else -1",
        "    return predicate == 41",
        "",
        "def unsigned_less_than_can_keep_slt() -> bool:",
        "    ensure result == true",
        "    predicate: i64 = 40",
        "    resolved: i64 = 36 if predicate == 40 else (37 if predicate == 41 else (34 if predicate == 38 else (35 if predicate == 39 else predicate)))",
        "    return resolved == 40",
        "",
        "def float_not_equal_can_use_ordered_one() -> bool:",
        "    ensure result == true",
        "    operator: i64 = TOKEN_BANG_EQ",
        "    predicate: i64 = 14 if operator == TOKEN_BANG_EQ else -1",
        "    return predicate == 6",
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def require_source_binding(int_enum: dict[str, int], real_enum: dict[str, int]) -> dict[str, int]:
    ordinals = token_ordinals()
    for name in OPERATOR_TOKEN_NAMES:
        if name not in ordinals:
            raise SystemExit(f"TokenKind lost comparison token {name}")
    constants = {name: ordinals[name] for name in OPERATOR_TOKEN_NAMES}
    if "Plus" not in ordinals or ordinals["Plus"] in constants.values():
        raise SystemExit("ordinary plus token collides with a comparison token")
    if len(set(constants.values())) != len(constants):
        raise SystemExit("comparison TokenKind ordinals are not distinct")

    source = SOURCE.read_text()
    int_section = function_section(source, "int_predicate_of")
    int_body = body_returns(int_section)
    int_rows = ordered_return_rows(
        int_section, r"^\s*(\d+)\s+return\s+if\s+operator\s*==\s*TokenKind\.([A-Za-z_][A-Za-z0-9_]*)\s*$"
    )
    if [(name, int(value)) for value, name in int_rows] != list(INT_MAP.items()) or "return-1" not in int_body:
        raise SystemExit("integer predicate function no longer has the exact signed comparison map")

    unsigned_section = function_section(source, "unsigned_predicate_of")
    unsigned_body = body_returns(unsigned_section)
    unsigned_rows = ordered_return_rows(
        unsigned_section, r"^\s*(\d+)\s+return\s+if\s+predicate\s*==\s*(\d+)\s*$"
    )
    if [(int(source_value), int(target)) for target, source_value in unsigned_rows] != list(UNSIGNED_MAP.items()) or "returnpredicate" not in unsigned_body:
        raise SystemExit("unsigned predicate function no longer remaps only the four ordering predicates")

    float_section = function_section(source, "float_predicate_of")
    float_body = body_returns(float_section)
    float_rows = ordered_return_rows(
        float_section, r"^\s*(\d+)\s+return\s+if\s+operator\s*==\s*TokenKind\.([A-Za-z_][A-Za-z0-9_]*)\s*$"
    )
    if [(name, int(value)) for value, name in float_rows] != list(FLOAT_MAP.items()) or "return-1" not in float_body:
        raise SystemExit("floating predicate function no longer has the exact comparison map")

    llvm_int_names = {
        32: "LLVMIntEQ", 33: "LLVMIntNE", 40: "LLVMIntSLT", 41: "LLVMIntSLE",
        38: "LLVMIntSGT", 39: "LLVMIntSGE", 36: "LLVMIntULT", 37: "LLVMIntULE",
        34: "LLVMIntUGT", 35: "LLVMIntUGE",
    }
    llvm_real_names = {
        1: "LLVMRealOEQ", 14: "LLVMRealUNE", 4: "LLVMRealOLT", 5: "LLVMRealOLE",
        2: "LLVMRealOGT", 3: "LLVMRealOGE",
    }
    for value, enum_name in llvm_int_names.items():
        if int_enum.get(enum_name) != value:
            raise SystemExit(f"LLVMIntPredicate changed {enum_name} from the codegen mapping {value}")
    for value, enum_name in llvm_real_names.items():
        if real_enum.get(enum_name) != value:
            raise SystemExit(f"LLVMRealPredicate changed {enum_name} from the codegen mapping {value}")

    emit = body_returns(function_section(source, "emit_binary"))
    call_order = (
        "float_predicate:i32=float_predicate_of(operator)",
        'LLVMBuildFCmp(builder,float_predicate,left,right,"fcmp")',
        "predicate:i32=int_predicate_of(operator)",
        "ifpredicate>=0:",
        "resolved:i32=unsigned_predicate_of(predicate)ifunsignedelsepredicate",
        'LLVMBuildICmp(builder,resolved,left,right,"cmp")',
    )
    positions = [emit.find(fragment) for fragment in call_order]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("scalar comparison lowering no longer routes through the proved predicate maps")
    if emit.find("returnnull", positions[-1]) < 0:
        raise SystemExit("unmodeled integer comparisons no longer decline after the checked predicate branch")
    return constants


LLVM_HEADER = find_llvm_header()
LLVM_INT_ENUM = llvm_enum_values(LLVM_HEADER, "LLVMIntPredicate")
LLVM_REAL_ENUM = llvm_enum_values(LLVM_HEADER, "LLVMRealPredicate")
token_ids = require_source_binding(LLVM_INT_ENUM, LLVM_REAL_ENUM)
expected_positive = render_positive(token_ids)
expected_negative = render_negative(token_ids)

if sys.argv[1:] == ["--write-proofs"]:
    POSITIVE.write_text(expected_positive)
    NEGATIVE.write_text(expected_negative)
    print("wrote comparison predicate proofs from the source-bound token and LLVM tables")
    raise SystemExit(0)

if POSITIVE.read_text() != expected_positive or NEGATIVE.read_text() != expected_negative:
    raise SystemExit("comparison predicate proof files differ from their deterministic renderer")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("comparison predicate proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    SOURCE,
    TOKENS,
    LLVM_HEADER,
    Path(LLVM_CONFIG).resolve(strict=True),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def source_sections(path: Path) -> tuple[list[str], dict[str, str]]:
    source = path.read_text()
    constants = re.findall(r"(?m)^const [^\n]+\n", source)
    sections: dict[str, str] = {}
    for match in re.finditer(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source):
        name = match.group(1)
        end_match = re.search(r"(?m)^def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
        end = match.end() + end_match.start() if end_match else len(source)
        sections[name] = source[match.start():end]
    return constants, sections


def isolated_report(path: Path, name: str, constants: list[str], sections: dict[str, str]) -> tuple[int, dict]:
    with tempfile.TemporaryDirectory(prefix="elisa-codegen-predicate-") as temp_dir:
        isolated = Path(temp_dir) / f"{name}.elisa"
        isolated.write_text("".join(constants) + sections[name])
        process = subprocess.run([str(BIN), "--json", str(isolated)], capture_output=True,
                                 text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


positive_constants, positive_sections = source_sections(POSITIVE)
positive_names = set(positive_sections)
if len(positive_names) != 21:
    raise SystemExit("positive predicate proof declaration inventory changed")
positive_obligations = 0
for name in sorted(positive_names):
    code, report = isolated_report(POSITIVE, name, positive_constants, positive_sections)
    assert code == 0 and report["status"] == report["verification_state"] == "proved", name
    assert report["summary"]["proven"] == report["summary"]["obligations"] == 2, name
    assert {row["name"] for row in report["declaration_details"] if row.get("verified")} == {name}
    positive_obligations += report["summary"]["proven"]

negative_constants, negative_sections = source_sections(NEGATIVE)
negative_names = set(negative_sections)
if negative_names != {
    "signed_less_than_can_use_sle",
    "unsigned_less_than_can_keep_slt",
    "float_not_equal_can_use_ordered_one",
}:
    raise SystemExit("negative predicate proof declaration inventory changed")
for name in sorted(negative_names):
    code, report = isolated_report(NEGATIVE, name, negative_constants, negative_sections)
    assert code == 1 and report["status"] == "failed", name
    assert report["summary"]["obligations"] == 2 and report["summary"]["proven"] == 1, name
    assert [(row["kind"], row["name"]) for row in report["findings"]] == [("ensure-unproven", name)]

assert require_current_product(BIN, PROVER) == product, "proof product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
if hashes_before != hashes_after:
    raise SystemExit("comparison predicate proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "signed, unsigned, and floating LLVM predicate classification",
    "positive_obligations": positive_obligations,
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
