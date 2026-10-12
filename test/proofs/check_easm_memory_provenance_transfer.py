"""Admit the EASM register provenance transfer lemmas against the production verifier."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "easm_memory_provenance_transfer.elisa"
NEGATIVE = HERE / "easm_memory_provenance_transfer_rejected.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
MODEL = HERE / "easm_memory_provenance_transfer.elisa"

POSITIVE_NAMES = {
    "pseudo_instruction_preserves_destination_provenance",
    "pseudo_instruction_preserves_source_provenance",
    "non_exchange_without_a_destination_is_a_state_noop",
    "move_cannot_create_provenance_from_an_untracked_source",
    "move_copies_a_tracked_source_provenance_component",
    "move_from_a_nonregister_clears_the_old_destination_provenance",
    "lea_cannot_create_provenance_from_an_untracked_base",
    "lea_copies_a_tracked_base_provenance_component",
    "lea_without_a_parsed_base_clears_old_destination_provenance",
    "pointer_arithmetic_preserves_destination_provenance",
    "every_other_register_write_kills_stale_destination_provenance",
    "xchg_swaps_destination_provenance",
    "xchg_swaps_source_provenance",
    "xchg_with_one_unparsed_operand_clears_the_surviving_register",
}
MODEL_NAMES = {
    "provenance_destination_after",
    "provenance_source_after",
}
NEGATIVE_NAMES = {
    "false_claim_move_invents_provenance_from_an_untracked_source",
    "false_claim_unknown_write_preserves_stale_provenance",
    "false_claim_arithmetic_destroys_valid_pointer_provenance",
    "false_claim_xchg_without_destination_preserves_the_source",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join(source.split())


def code_only(source: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():])
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def declared_functions(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


memory = compact(code_only(function_section(MEMORY.read_text(), "easm_update_memory_provenance")))
required_order = (
    "if instruction.pseudo:return",
    'if easm_starts(instruction.op,"xchg"):',
    'if source!=""anddestination!="":',
    "source_type:sview=easm_provenance_type(states,source)",
    "source_parameter:sview=easm_provenance_parameter(states,source)",
    "destination_type:sview=easm_provenance_type(states,destination)",
    "destination_parameter:sview=easm_provenance_parameter(states,destination)",
    "easm_provenance_set_parameter(states,source,destination_type,destination_parameter)",
    "easm_provenance_set_parameter(states,destination,source_type,source_parameter)",
    'easm_provenance_set_parameter(states,source,"","")ifsource!=""',
    'easm_provenance_set_parameter(states,destination,"","")ifdestination!=""',
    'if destination=="":return',
    'if easm_starts(op,"mov"):',
    "inherited<-easm_provenance_type(states,source)",
    "inherited_parameter<-easm_provenance_parameter(states,source)",
    'elif easm_starts(op,"lea"):',
    "source_register:sview=easm_memory_base_register(source_operand)",
    "inherited<-easm_provenance_type(states,source_register)",
    "inherited_parameter<-easm_provenance_parameter(states,source_register)",
    'elif easm_starts(op,"add")oreasm_starts(op,"sub")oreasm_starts(op,"inc")oreasm_starts(op,"dec"):',
    "inherited<-easm_provenance_type(states,destination)",
    "inherited_parameter<-easm_provenance_parameter(states,destination)",
    "easm_provenance_set_parameter(states,destination,inherited,inherited_parameter)",
)
positions = [memory.find(compact(fragment)) for fragment in required_order]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("production provenance transfer no longer matches the proved preservation and clobber cases")
if memory.count('easm_provenance_set_parameter(states,destination,inherited,inherited_parameter)') != 1:
    raise SystemExit("every non-pseudo destination write must finish through the single fact-replacement step")
if memory.count('easm_provenance_set_parameter(states,source,destination_type,destination_parameter)') != 1 or \
        memory.count('easm_provenance_set_parameter(states,destination,source_type,source_parameter)') != 1:
    raise SystemExit("xchg must snapshot both provenance components before replacing either register")
destination_guard = memory.find('ifdestination=="":return')
if destination_guard < 6 or memory[destination_guard - 6:destination_guard] != "return":
    raise SystemExit("xchg handling must return before the ordinary destination-write transfer")
dispatch_start = memory.find("op:sview=instruction.op")
dispatch_end = memory.find("easm_provenance_set_parameter(states,destination,inherited,inherited_parameter)", dispatch_start)
if dispatch_start < 0 or dispatch_end < 0:
    raise SystemExit("could not isolate the ordinary register-write transfer")
dispatch = memory[dispatch_start:dispatch_end]
classified_prefixes = re.findall(r'easm_starts\(op,"([^"]+)"\)', dispatch)
if classified_prefixes != ["mov", "lea", "add", "sub", "inc", "dec"]:
    raise SystemExit("provenance-preserving opcode classes changed; revise the proof model before admission")

proof_text = code_only(POSITIVE.read_text())
if declared_functions(POSITIVE) != POSITIVE_NAMES | MODEL_NAMES:
    raise SystemExit("positive EASM provenance proof inventory is incomplete or contains extras")
if declared_functions(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("negative EASM provenance proof inventory is incomplete or contains extras")
for fact in (
    "const PROV_CLOBBER: i64 = 0",
    "const PROV_MOVE: i64 = 1",
    "const PROV_LEA: i64 = 2",
    "const PROV_ADD: i64 = 3",
    "const PROV_SUB: i64 = 4",
    "const PROV_INC: i64 = 5",
    "const PROV_DEC: i64 = 6",
    "const PROV_XCHG: i64 = 7",
):
    if compact(fact) not in compact(proof_text):
        raise SystemExit(f"proof model is missing transfer class: {fact}")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("EASM provenance proofs require a strict proof build")

inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    Path(__file__),
    HERE / "proof_product_gate.py",
    MEMORY,
    POSITIVE,
    NEGATIVE,
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
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES | MODEL_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "no-fabrication, stale-fact clearing, arithmetic preservation, pseudo no-op, and xchg swap for EASM type and parameter provenance",
    "positive_obligations": positive["summary"]["proven"],
    "unsafe_simplifications_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
