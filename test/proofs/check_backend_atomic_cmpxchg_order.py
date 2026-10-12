"""Admit source-bound proofs of atomic compare-exchange memory-order pairs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
BACKEND = ROOT / "src/backend/codegen_atomic.elisa"
RUNTIME = ROOT / "elisacore_std/collections.elisai"
VALID = HERE / "backend_atomic_cmpxchg_order.elisa"
REJECTED = HERE / "backend_atomic_cmpxchg_order_rejected.elisa"
FALSE_CLAIMS = HERE / "backend_atomic_cmpxchg_order_false_claims.elisa"
MAPPING = HERE / "backend_atomic_cmpxchg_order_mapping.elisa"
MAPPING_FALSE_CLAIMS = HERE / "backend_atomic_cmpxchg_order_mapping_false_claims.elisa"
LLVM_CONFIG = shutil.which(os.environ.get("LLVM_CONFIG", "llvm-config"))

ORDER_VARIANTS = ("Relaxed", "Acquire", "Release", "AcqRel", "SeqCst")
ORDER_INDEX = {name: index for index, name in enumerate(ORDER_VARIANTS)}
ALLOWED_FAILURES = {
    "Relaxed": {"Relaxed"},
    "Acquire": {"Relaxed", "Acquire"},
    "Release": {"Relaxed"},
    "AcqRel": {"Relaxed", "Acquire"},
    "SeqCst": {"Relaxed", "Acquire", "SeqCst"},
}
VALID_PAIRS = {
    (success, failure)
    for success, failures in ALLOWED_FAILURES.items()
    for failure in failures
}
PAIR_CODES = {
    ("Relaxed", "Relaxed"): (2, 2),
    ("Acquire", "Relaxed"): (4, 2),
    ("Acquire", "Acquire"): (4, 4),
    ("Release", "Relaxed"): (5, 2),
    ("AcqRel", "Relaxed"): (6, 2),
    ("AcqRel", "Acquire"): (6, 4),
    ("SeqCst", "Relaxed"): (7, 2),
    ("SeqCst", "Acquire"): (7, 4),
    ("SeqCst", "SeqCst"): (7, 7),
}
DYNAMIC_PAIRS = (
    ("dynamic_success_acquire_failure", -1, 1),
    ("release_success_dynamic_failure", 2, -1),
    ("both_dynamic", -1, -1),
)
FALSE_PAIR_LABELS = (
    ("release_acquire", 2, 1),
    ("relaxed_acquire", 0, 1),
    ("acquire_seqcst", 1, 4),
    ("seqcst_acqrel", 4, 3),
)
FALSE_MAPPING_CLAIMS = (
    ("release_relaxed_as_acquire", "Release", "Relaxed", 4, 2),
    ("acqrel_acquire_as_acquire", "AcqRel", "Acquire", 4, 4),
)

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return "\n".join(line for line in source[match.start():end].splitlines()
                      if not line.lstrip().startswith("#"))


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def runtime_order_variants() -> list[str]:
    lines = RUNTIME.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "enum MemoryOrder:":
            continue
        base_indent = len(line) - len(line.lstrip(" "))
        variants = []
        for variant_line in lines[index + 1:]:
            if not variant_line.strip() or variant_line.lstrip().startswith("#"):
                continue
            indent = len(variant_line) - len(variant_line.lstrip(" "))
            if indent <= base_indent:
                break
            if indent == base_indent + 4:
                variants.append(variant_line.strip())
        return variants
    raise SystemExit("runtime MemoryOrder enum was not found")


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
        raise SystemExit("llvm-config is required to bind atomic ordering IDs to LLVM")
    include_dir = subprocess.run([LLVM_CONFIG, "--includedir"], check=True,
                                 capture_output=True, text=True, timeout=15).stdout.strip()
    header = Path(include_dir) / "llvm-c/Core.h"
    if not header.is_file():
        raise SystemExit(f"LLVM C API header is missing: {header}")
    return header.resolve(strict=True)


runtime_orders = runtime_order_variants()
if runtime_orders != list(ORDER_VARIANTS):
    raise SystemExit(f"runtime MemoryOrder declaration changed: {runtime_orders}")

backend_text = BACKEND.read_text()
order_name = compact(function_section(backend_text, "atomic_order_name"))
expected_order_name = compact("""
    def atomic_order_name(expression: Expr) -> sview:
        match expression:
            Expr.Field(order_type_expr, order_variant, _):
                if order_type_expr is Expr.Ident(order_type_name, _) and order_type_name == "MemoryOrder":
                    return order_variant
            _:
                pass
        return ""
""")
if order_name != expected_order_name:
    raise SystemExit("atomic order-name extraction no longer recognizes only MemoryOrder variant fields")

policy = function_section(backend_text, "atomic_compare_exchange_order_pair_valid")
policy_code = compact(policy)
if 'returntrueifsuccess_name==""orfailure_name==""' not in policy_code:
    raise SystemExit("dynamic compare-exchange order pairs must retain their conservative acceptance path")
parsed_failures: dict[str, set[str]] = {}
for line in policy.splitlines():
    if "->" not in line or line.lstrip().startswith("def "):
        continue
    left, right = line.strip().split("->", 1)
    success_names = re.findall(r'"([A-Za-z]+)"', left)
    if left.strip() == "_":
        if right.strip() != "false":
            raise SystemExit("unrecognized MemoryOrder pairs must remain rejected")
        continue
    failure_names = set(re.findall(r'failure_name\s*==\s*"([A-Za-z]+)"', right))
    if not success_names or not failure_names:
        raise SystemExit(f"could not parse compare-exchange validity arm: {line.strip()}")
    for success in success_names:
        if success in parsed_failures:
            raise SystemExit(f"duplicate compare-exchange validity row for {success}")
        parsed_failures[success] = failure_names
if parsed_failures != ALLOWED_FAILURES:
    raise SystemExit("production compare-exchange allowed-pair table differs from the proof specification")

ordering_constants = {
    "LLVM_ATOMIC_ORDERING_MONOTONIC": 2,
    "LLVM_ATOMIC_ORDERING_ACQUIRE": 4,
    "LLVM_ATOMIC_ORDERING_RELEASE": 5,
    "LLVM_ATOMIC_ORDERING_ACQUIRE_RELEASE": 6,
    "LLVM_ATOMIC_ORDERING_SEQ_CST": 7,
}
for name, value in ordering_constants.items():
    if not re.search(rf"(?m)^\s*const {name}: i32 = {value}\s*$", backend_text):
        raise SystemExit(f"backend LLVM ordering constant {name} changed")

header = find_llvm_header()
llvm_orders = llvm_enum_values(header, "LLVMAtomicOrdering")
expected_llvm_orders = {
    "LLVMAtomicOrderingMonotonic": 2,
    "LLVMAtomicOrderingAcquire": 4,
    "LLVMAtomicOrderingRelease": 5,
    "LLVMAtomicOrderingAcquireRelease": 6,
    "LLVMAtomicOrderingSequentiallyConsistent": 7,
}
if any(llvm_orders.get(name) != value for name, value in expected_llvm_orders.items()):
    raise SystemExit("backend atomic order constants no longer match LLVM's C API enum")

pair_mapping = compact(function_section(backend_text, "atomic_compare_exchange_orderings"))
mapping_fragments = (
    "ifsuccess_name==\"Relaxed\"andfailure_name==\"Relaxed\":return(LLVM_ATOMIC_ORDERING_MONOTONIC,LLVM_ATOMIC_ORDERING_MONOTONIC)",
    "ifsuccess_name==\"Acquire\"and(failure_name==\"Relaxed\"orfailure_name==\"Acquire\"):return(LLVM_ATOMIC_ORDERING_ACQUIRE,LLVM_ATOMIC_ORDERING_MONOTONICiffailure_name==\"Relaxed\"elseLLVM_ATOMIC_ORDERING_ACQUIRE)",
    "ifsuccess_name==\"Release\"andfailure_name==\"Relaxed\":return(LLVM_ATOMIC_ORDERING_RELEASE,LLVM_ATOMIC_ORDERING_MONOTONIC)",
    "ifsuccess_name==\"AcqRel\"and(failure_name==\"Relaxed\"orfailure_name==\"Acquire\"):return(LLVM_ATOMIC_ORDERING_ACQUIRE_RELEASE,LLVM_ATOMIC_ORDERING_MONOTONICiffailure_name==\"Relaxed\"elseLLVM_ATOMIC_ORDERING_ACQUIRE)",
    "ifsuccess_name==\"SeqCst\"and(failure_name==\"Relaxed\"orfailure_name==\"Acquire\"orfailure_name==\"SeqCst\"):",
    "failure_order:i32=LLVM_ATOMIC_ORDERING_MONOTONICiffailure_name==\"Relaxed\"elseLLVM_ATOMIC_ORDERING_ACQUIREiffailure_name==\"Acquire\"elseLLVM_ATOMIC_ORDERING_SEQ_CST",
    "return(LLVM_ATOMIC_ORDERING_SEQ_CST,failure_order)",
    "return(LLVM_ATOMIC_ORDERING_SEQ_CST,LLVM_ATOMIC_ORDERING_SEQ_CST)",
)
if any(fragment not in pair_mapping for fragment in mapping_fragments):
    raise SystemExit("compare-exchange emitted ordering table or conservative fallback changed")

emitter = compact(function_section(backend_text, "emit_atomic_runtime_call"))
validate_call = 'ifname=="compare_exchange":returnnullifnotatomic_compare_exchange_order_pair_valid(arguments[3],arguments[4])'
map_call = 'orders:(success_order:i32,failure_order:i32)=atomic_compare_exchange_orderings(arguments[3],arguments[4])'
llvm_call = 'LLVMBuildAtomicCmpXchg(builder,value_pointer,atomic_expected,atomic_desired,orders.success_order,orders.failure_order,0)'
if any(piece not in emitter for piece in (validate_call, map_call, llvm_call)):
    raise SystemExit("compare-exchange must validate the order pair before passing the mapped pair to LLVM")
if not (emitter.index(validate_call) < emitter.index(map_call) < emitter.index(llvm_call)):
    raise SystemExit("compare-exchange order validation and emission order changed")

positive_names = {
    f"cmpxchg_{success.lower()}_{failure.lower()}_is_valid"
    for success, failure in VALID_PAIRS
} | {
    "cmpxchg_dynamic_success_acquire_failure_is_valid",
    "cmpxchg_release_success_dynamic_failure_is_valid",
    "cmpxchg_both_dynamic_is_valid",
}
rejected_names = {
    f"cmpxchg_{success.lower()}_{failure.lower()}_is_rejected"
    for success in ORDER_VARIANTS
    for failure in ORDER_VARIANTS
    if (success, failure) not in VALID_PAIRS
}
false_names = {f"cmpxchg_falsely_accepts_{label}" for label, _, _ in FALSE_PAIR_LABELS}
mapping_names = {
    f"cmpxchg_{success.lower()}_{failure.lower()}_maps_to_expected_llvm_orders"
    for success, failure in PAIR_CODES
}
mapping_false_names = {f"cmpxchg_{label}" for label, *_ in FALSE_MAPPING_CLAIMS}
if (declarations(VALID) != positive_names or declarations(REJECTED) != rejected_names or
        declarations(FALSE_CLAIMS) != false_names or declarations(MAPPING) != mapping_names or
        declarations(MAPPING_FALSE_CLAIMS) != mapping_false_names):
    raise SystemExit("compare-exchange order proof case inventory is incomplete or contains extras")


def check_case(path: Path, name: str, success: int, failure: int, expected: bool) -> None:
    section = compact(function_section(path.read_text(), name))
    expected_return = "success==-1orfailure==-1" if success == -1 or failure == -1 else {
        0: "failure==0",
        1: "failure==0orfailure==1",
        2: "failure==0",
        3: "failure==0orfailure==1",
        4: "failure==0orfailure==1orfailure==4",
    }[success]
    contract = f"requiressuccess=={success}andfailure=={failure}ensureresult=={'true' if expected else 'false'}return{expected_return}"
    if contract not in section:
        raise SystemExit(f"{name} no longer proves the source-selected order-pair arm")


for success, failure in VALID_PAIRS:
    name = f"cmpxchg_{success.lower()}_{failure.lower()}_is_valid"
    check_case(VALID, name, ORDER_INDEX[success], ORDER_INDEX[failure], True)
for success, failure in (("Relaxed", "Acquire"), ("Acquire", "SeqCst"),
                         ("Release", "Acquire"), ("Release", "SeqCst"),
                         ("AcqRel", "Release"), ("AcqRel", "AcqRel"),
                         ("SeqCst", "Release"), ("SeqCst", "AcqRel")):
    name = f"cmpxchg_{success.lower()}_{failure.lower()}_is_rejected"
    check_case(REJECTED, name, ORDER_INDEX[success], ORDER_INDEX[failure], False)
for name, success, failure in DYNAMIC_PAIRS:
    check_case(VALID, f"cmpxchg_{name}_is_valid", success, failure, True)
for label, success, failure in FALSE_PAIR_LABELS:
    check_case(FALSE_CLAIMS, f"cmpxchg_falsely_accepts_{label}", success, failure, True)


def check_mapping_case(path: Path, name: str, success: str, failure: str,
                       expected_success: int, expected_failure: int,
                       claimed_success: int | None = None,
                       claimed_failure: int | None = None) -> None:
    success_index = ORDER_INDEX[success]
    failure_index = ORDER_INDEX[failure]
    actual_success = expected_success if claimed_success is None else claimed_success
    actual_failure = expected_failure if claimed_failure is None else claimed_failure
    success_rhs = (str(expected_success) if expected_success == 7 else
                   f"{expected_success}ifsuccess=={success_index}andfailure=={failure_index}else7")
    failure_rhs = (str(expected_failure) if expected_failure == 7 else
                   f"{expected_failure}ifsuccess=={success_index}andfailure=={failure_index}else7")
    section = compact(function_section(path.read_text(), name))
    expected = (
        f"requiressuccess=={success_index}andfailure=={failure_index}ensureresult==true"
        f"mappedsuccess:i64={success_rhs}mappedfailure:i64={failure_rhs}"
        f"returnmappedsuccess=={actual_success}andmappedfailure=={actual_failure}"
    )
    if expected not in section:
        raise SystemExit(f"{name} no longer proves the source-selected LLVM order pair")


for (success, failure), (success_code, failure_code) in PAIR_CODES.items():
    check_mapping_case(
        MAPPING,
        f"cmpxchg_{success.lower()}_{failure.lower()}_maps_to_expected_llvm_orders",
        success, failure, success_code, failure_code,
    )
for label, success, failure, claimed_success, claimed_failure in FALSE_MAPPING_CLAIMS:
    expected_success, expected_failure = PAIR_CODES[(success, failure)]
    check_mapping_case(
        MAPPING_FALSE_CLAIMS, f"cmpxchg_{label}", success, failure,
        expected_success, expected_failure, claimed_success, claimed_failure,
    )

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("atomic compare-exchange order proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", BACKEND, RUNTIME, header,
    VALID, REJECTED, FALSE_CLAIMS, MAPPING, MAPPING_FALSE_CLAIMS,
    *source_include_closure([VALID, REJECTED, FALSE_CLAIMS, MAPPING, MAPPING_FALSE_CLAIMS]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = replay(VALID)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names
assert positive == replay(VALID)[1], "valid compare-exchange order proofs changed across repeated runs"

code, rejected = replay(REJECTED)
assert code == 0 and rejected["status"] == rejected["verification_state"] == "proved"
assert rejected["summary"]["proven"] == rejected["summary"]["obligations"]
assert {row["name"] for row in rejected["declaration_details"] if row.get("verified")} == rejected_names
assert rejected == replay(REJECTED)[1], "invalid compare-exchange order proofs changed across repeated runs"

code, false_claims = replay(FALSE_CLAIMS)
assert code == 1 and false_claims["status"] == "failed"
assert {finding["name"] for finding in false_claims["findings"]} == false_names
assert all(finding["kind"] == "ensure-unproven" for finding in false_claims["findings"])
assert false_names.isdisjoint({row["name"] for row in false_claims["declaration_details"] if row.get("verified")})

code, mapping = replay(MAPPING)
assert code == 0 and mapping["status"] == mapping["verification_state"] == "proved"
assert mapping["summary"]["proven"] == mapping["summary"]["obligations"]
assert {row["name"] for row in mapping["declaration_details"] if row.get("verified")} == mapping_names
assert mapping == replay(MAPPING)[1], "LLVM compare-exchange mapping proofs changed across repeated runs"

code, mapping_false_claims = replay(MAPPING_FALSE_CLAIMS)
assert code == 1 and mapping_false_claims["status"] == "failed"
assert {finding["name"] for finding in mapping_false_claims["findings"]} == mapping_false_names
assert all(finding["kind"] == "ensure-unproven" for finding in mapping_false_claims["findings"])
assert mapping_false_names.isdisjoint({row["name"] for row in mapping_false_claims["declaration_details"] if row.get("verified")})

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product or pinned source tree changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "all 25 static MemoryOrder pairs, dynamic fallback cases, LLVM mapping binding, and false-claim controls",
    "valid_static_pairs": len(VALID_PAIRS),
    "rejected_static_pairs": len(rejected_names),
    "dynamic_cases": len(DYNAMIC_PAIRS),
    "false_claims_rejected": sorted(false_names),
    "producer_proven": positive["summary"]["proven"] + rejected["summary"]["proven"] + mapping["summary"]["proven"],
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
}, sort_keys=True))
