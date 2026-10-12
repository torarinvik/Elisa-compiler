"""Admit the EASM control-flow meet proof against a strict Elisa-proof product."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_flow_join.elisa"
NEGATIVE = HERE / "easm_flow_join_rejected.elisa"
MASKS = ROOT / "src/backend/easm_register_masks.elisa"
MODEL = ROOT / "src/backend/easm_model.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
VERIFY_FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"
REGISTER_NAMES = ("RAX", "RCX", "RDX", "RBX", "RSI", "RDI", "RBP", "RSP", "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15")
EXPECTED_MASKS = {name: 1 << bit for bit, name in enumerate(REGISTER_NAMES)}

EXPECTED_DECLARATIONS = {
    "model_join_fact",
    "both_predecessors_keep_a_fact",
    "a_missing_left_fact_is_dropped",
    "a_missing_right_fact_is_dropped",
    "the_join_is_exactly_the_common_fact",
    "the_join_is_commutative",
    "a_true_right_predecessor_reduces_the_join_to_left",
    "a_true_left_predecessor_reduces_the_join_to_right",
    "the_join_is_associative",
    "the_join_is_idempotent",
    "a_join_is_below_its_left_predecessor",
    "a_join_is_below_its_right_predecessor",
    "every_common_lower_fact_is_below_the_join",
    "the_join_is_monotone",
    "flag_facts_merge_by_the_same_common_fact_rule",
    "stack_alignment_is_known_only_when_both_predecessors_agree",
    "an_unknown_or_conflicting_alignment_is_dropped",
    "equal_stack_deltas_are_preserved",
    "unequal_stack_deltas_reset_to_zero",
}
FALSE_CLAIMS = {"one_sided_fact_survives_a_join"}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(value: str) -> str:
    return " ".join(value.split())


def source_body(source: str, signature: str) -> str:
    if signature not in source:
        raise SystemExit(f"missing production function: {signature}")
    return source.split(signature, 1)[1].split("\n        def ", 1)[0]


def proof_body(source: str, name: str) -> str:
    signature = f"def {name}("
    if signature not in source:
        raise SystemExit(f"missing proof function: {name}")
    return source.split(signature, 1)[1].split("\ndef ", 1)[0].split(":\n", 1)[1]


def returned_expression(source: str, name: str) -> str:
    body = proof_body(source, name)
    if "return " not in body:
        raise SystemExit(f"proof function has no return expression: {name}")
    return compact(body.split("return ", 1)[1])


positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
model_body = proof_body(positive_text, "model_join_fact")
if compact(model_body) != compact("ensure result == (left and right)\n    return left and right"):
    raise SystemExit("Boolean meet model must state and compute the conjunction of predecessor facts")
if compact(proof_body(positive_text, "flag_facts_merge_by_the_same_common_fact_rule")) != compact(
    "ensure result == (left and right)\n    return left and right"
):
    raise SystemExit("flag meet model must state and compute conjunction")

expected_returns = {
    "both_predecessors_keep_a_fact": "left and right",
    "a_missing_left_fact_is_dropped": "not (left and right)",
    "a_missing_right_fact_is_dropped": "not (left and right)",
    "the_join_is_exactly_the_common_fact": "(left and right) == (not (not left or not right))",
    "the_join_is_commutative": "(left and right) == (right and left)",
    "a_true_right_predecessor_reduces_the_join_to_left": "(not left or (left and right)) and (not (left and right) or left)",
    "a_true_left_predecessor_reduces_the_join_to_right": "(not right or (left and right)) and (not (left and right) or right)",
    "the_join_is_associative": "((first and second) and third) == (first and (second and third))",
    "a_join_is_below_its_left_predecessor": "not (left and right) or left",
    "a_join_is_below_its_right_predecessor": "not (left and right) or right",
    "every_common_lower_fact_is_below_the_join": "not lower or (left and right)",
    "the_join_is_monotone": "not (first and second) or (larger_first and larger_second)",
    "an_unknown_or_conflicting_alignment_is_dropped": "not (left_known and right_known and same_alignment)",
}
for theorem, expected in expected_returns.items():
    if returned_expression(positive_text, theorem) != compact(expected):
        raise SystemExit(f"join theorem changed: {theorem}")
if compact(proof_body(positive_text, "the_join_is_idempotent")) != compact(
    "ensure result == true\n    return model_join_fact(fact, fact) == fact"
):
    raise SystemExit("idempotence proof must apply the verified meet model to equal predecessor facts")
if compact(proof_body(positive_text, "stack_alignment_is_known_only_when_both_predecessors_agree")) != compact(
    "ensure result == (left_known and right_known and same_alignment)\n    return left_known and right_known and same_alignment"
):
    raise SystemExit("stack alignment join must require both known predecessor facts and equal alignment")
if compact(proof_body(positive_text, "equal_stack_deltas_are_preserved")) != compact(
    "requires left == right\n    ensure result == true\n    return (left if left == right else 0) == left"
):
    raise SystemExit("equal stack deltas must be retained by the join")
if compact(proof_body(positive_text, "unequal_stack_deltas_reset_to_zero")) != compact(
    "requires left != right\n    ensure result == true\n    return (left if left == right else 0) == 0"
):
    raise SystemExit("unequal stack deltas must be reset by the join")
for theorem, required in (
    ("both_predecessors_keep_a_fact", "requires left and right"),
    ("a_missing_left_fact_is_dropped", "requires not left"),
    ("a_missing_right_fact_is_dropped", "requires not right"),
    ("every_common_lower_fact_is_below_the_join", "requires (not lower or left) and (not lower or right)"),
    ("the_join_is_monotone", "requires (not first or larger_first) and (not second or larger_second)"),
    ("a_true_right_predecessor_reduces_the_join_to_left", "requires right"),
    ("a_true_left_predecessor_reduces_the_join_to_right", "requires left"),
    ("an_unknown_or_conflicting_alignment_is_dropped", "requires not left_known or not right_known or not same_alignment"),
    ("equal_stack_deltas_are_preserved", "requires left == right"),
    ("unequal_stack_deltas_reset_to_zero", "requires left != right"),
):
    if compact(required) not in compact(proof_body(positive_text, theorem)):
        raise SystemExit(f"join theorem lost its premise: {theorem}")
if compact(proof_body(negative_text, "one_sided_fact_survives_a_join")) != compact(
    "requires not left and right\n    ensure result == true\n    return left"
):
    raise SystemExit("negative one-sided predecessor control changed")

mask_source = MASKS.read_text()
register_masks = {
    name: int(value)
    for name, value in re.findall(r"(?m)^        const (R(?:AX|CX|DX|BX|SI|DI|BP|SP|[0-9]+)): i64 = ([0-9]+)$", mask_source)
}
if register_masks != EXPECTED_MASKS:
    raise SystemExit("flow-join proof requires the exact, distinct canonical 16-bit register fact domain")

model_source = MODEL.read_text()
propagate = source_body(
    model_source,
    "def easm_propagate_flow(target: i64, incoming: FlowState, entries: mutable darray[FlowState]&, meets: mutable darray[i64]&, counts: mutable darray[i64]&) -> bool:",
)
expected_propagate = """
if target < 0 or target >= entries.count.i64():
    return false
changed: mutable bool = false
if counts[target.usize()] == 0:
    meets[target.usize()] <- incoming.live
    counts[target.usize()] <- 1
else:
    new_meet: i64 = meets[target.usize()] & incoming.live
    changed <- true if new_meet != meets[target.usize()]
    meets[target.usize()] <- new_meet
    counts[target.usize()] <- counts[target.usize()] + 1
if not entries[target.usize()].valid:
    entries[target.usize()] <- incoming
    return true
current: FlowState = entries[target.usize()]
joined: FlowState = current
joined.live <- current.live & incoming.live
joined.flags_live <- current.flags_live and incoming.flags_live
joined.stack_known <- current.stack_known and incoming.stack_known and current.stack_mod16 == incoming.stack_mod16
joined.stack_mod16 <- current.stack_mod16 if joined.stack_known else 0
joined.stack_delta <- current.stack_delta if current.stack_delta == incoming.stack_delta else 0
changed <- true if not easm_flow_equal(current, joined)
entries[target.usize()] <- joined
return changed
"""
if compact(propagate) != compact(expected_propagate):
    raise SystemExit("flow propagation changed; recheck first-predecessor handling and common-fact meet placement")

flow_equal = source_body(model_source, "def easm_flow_equal(a: FlowState, b: FlowState) -> bool:")
expected_flow_equal = "return a.valid == b.valid and a.live == b.live and a.stack_delta == b.stack_delta and a.stack_mod16 == b.stack_mod16 and a.stack_known == b.stack_known and a.flags_live == b.flags_live"
if compact(flow_equal) != compact(expected_flow_equal):
    raise SystemExit("flow fixed-point equality must observe both merged fact fields")

provenance_source = PROVENANCE.read_text()
verify_merges = source_body(
    provenance_source,
    "def verify_control_flow_merges(fn: Function, issues: mutable darray[Issue]&) -> void:",
)
iteration_start = "for round_index in 0..<(count + 1)"
post_iteration = "for index in 0..<count |index, entries, meets, incoming_counts, fn, issues|:"
if iteration_start not in verify_merges or post_iteration not in verify_merges:
    raise SystemExit("control-flow verifier no longer has a bounded propagation loop and merge-consumer pass")
iteration = verify_merges.split(iteration_start, 1)[1].split(post_iteration, 1)[0]
expected_iteration = """
for round_index in 0..<(count + 1) |round_index, entries, meets, incoming_counts, fn, issues|:
    changed: mutable bool = false
    for index in 0..<count |index, entries, meets, incoming_counts, fn, issues, changed|:
        continue if not entries[index].valid
        instruction: Instruction = fn.instructions[index]
        state: FlowState = easm_flow_transfer(instruction, entries[index])
        if easm_starts(instruction.op, "j"):
            target: sview = easm_last_operand(instruction.text)
            if sview_len(target) > 0 and sview_at(target, 0) != 37:
                changed <- easm_propagate_flow(easm_label_index(fn.instructions, target), state, entries, meets, incoming_counts) or changed
            if easm_is_terminator(instruction.op):
                continue
        if not easm_is_terminator(instruction.op) and index + 1 < count:
            changed <- easm_propagate_flow(index.i64() + 1, state, entries, meets, incoming_counts) or changed
    break if not changed
"""
if compact(iteration_start + iteration) != compact(expected_iteration):
    raise SystemExit("fixed-point traversal must propagate branch targets and fallthrough through the proved join before convergence")
if "continue if fn.instructions[index].op != \"label\" or incoming_counts[index] == 0" not in verify_merges:
    raise SystemExit("post-fixpoint liveness validation must inspect every reachable label block")
expected_missing_check = """
missing: i64 = demanded & (~meets[index])
if missing != 0:
    issues.push(Issue{severity: Severity.Error, code: "merge-state-unsound", line: fn.instructions[index].line, message: "merge label carries a register that is not established on every incoming edge; declare a labels contract or write the register on every edge"})
"""
if compact(expected_missing_check) not in compact(verify_merges):
    raise SystemExit("merge validation must check demanded registers against the all-predecessor meet")

verify_function_source = VERIFY_FUNCTION.read_text()
function_compositions = source_body(
    verify_function_source,
    "def verify_function_compositions(fn: Function, fragments: darray[Function]&, issues: mutable darray[Issue]&):",
)
if compact(function_compositions).count("verify_control_flow_merges(fn, issues)") != 1:
    raise SystemExit("function verification must invoke the source-bound control-flow merge analysis exactly once")
module_compositions = source_body(
    verify_function_source,
    "def verify_module_compositions(module: Module, issues: mutable darray[Issue]&):",
)
expected_module_compositions = """
for fn in module.functions |module, issues|:
    verify_function_compositions(fn, module.fragments, issues)
"""
if compact(module_compositions) != compact(expected_module_compositions):
    raise SystemExit("module verification must apply the merge checker to every function")
module_verify = source_body(
    verify_function_source,
    "def verify_module(module: Module) -> darray[Issue]:",
)
module_verify_positions = [
    compact(module_verify).find(compact(fragment))
    for fragment in (
        "verify_module_fragments(module, issues)",
        "verify_module_compositions(module, issues)",
        "return issues",
    )
]
if any(position < 0 for position in module_verify_positions) or module_verify_positions != sorted(module_verify_positions):
    raise SystemExit("module verification must reach the per-function control-flow merge check before returning issues")

actual_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text))
if actual_declarations != EXPECTED_DECLARATIONS:
    raise SystemExit("positive flow-join proof declarations changed")
negative_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text))
if negative_declarations != FALSE_CLAIMS:
    raise SystemExit("flow-join false-claim control changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM flow-join proof requires a strict proof build")
stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, MASKS, MODEL, PROVENANCE, VERIFY_FUNCTION,
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


positive_code, positive = run(POSITIVE)
assert positive_code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "flow-join report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == EXPECTED_DECLARATIONS

negative_code, negative = run(NEGATIVE)
assert negative_code == 1 and negative["status"] == "failed"
assert negative["summary"]["unproven"] == 1
assert negative == run(NEGATIVE)[1], "flow-join false-claim report changed across repeated runs"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "one_sided_fact_survives_a_join")
]
one_sided_finding = negative["findings"][0]
assert one_sided_finding["status"] == "disproved"
assert one_sided_finding["counterexample_found"]
counterexample = one_sided_finding["counterexample"]
assert len(counterexample) == 2

def matches_boolean_input(condition: dict, name: str, value: bool) -> bool:
    return (
        condition.get("kind") == "binary"
        and condition.get("operator") == "=="
        and condition.get("left", {}).get("kind") == "ident"
        and condition.get("left", {}).get("name") == name
        and condition.get("right", {}).get("kind") == "bool"
        and condition.get("right", {}).get("value") is value
    )

assert matches_boolean_input(counterexample[0], "left", False)
assert matches_boolean_input(counterexample[1], "right", True), \
    "one-sided-fact control must expose left=false and right=true"
assert "one_sided_fact_survives_a_join" not in {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "register liveness, flag facts, stack alignment, and stack deltas at EASM control-flow joins",
    "positive_obligations": positive["summary"]["proven"],
    "false_claim_rejected_with_counterexample": "one_sided_fact_survives_a_join",
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
