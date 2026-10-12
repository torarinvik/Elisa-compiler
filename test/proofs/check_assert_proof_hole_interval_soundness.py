"""Replay soundness lemmas for the proof-hole interval decision rules."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROOF = HERE / "assert_proof_hole_interval_soundness.elisa"
NEGATIVE = HERE / "assert_proof_hole_interval_bad_thresholds.elisa"
UNKNOWN = HERE / "assert_proof_hole_interval_fail_closed.elisa"
BOUND_UPDATES = HERE / "assert_proof_hole_interval_bound_updates.elisa"
SOURCE = ROOT / "src/semantic/check_assert_proof_hole.elisa"
ARITH_SOURCE = ROOT / "src/semantic/check_ensure_strict.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one proof function named {name}")
    start = matches[0].start()
    following = re.search(r"^def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


proof_text = PROOF.read_text()
negative_text = NEGATIVE.read_text()
unknown_text = UNKNOWN.read_text()
bound_updates_text = BOUND_UPDATES.read_text()
source_text = SOURCE.read_text()
arithmetic_text = ARITH_SOURCE.read_text()
try:
    aph_provable = source_text.split("def aph_provable(", 1)[1].split("\n        def aph_idents(", 1)[0]
except IndexError as error:
    raise SystemExit("production assert proof-hole interval decision is missing") from error

production_rules = (
    "(min_known and min_value >= 1) return if operator == TokenKind.Gt",
    "(min_known and min_value >= 0) return if operator == TokenKind.GtEq",
    "(max_known and max_value <= (0 - 1)) return if operator == TokenKind.Lt",
    "(max_known and max_value <= 0) return if operator == TokenKind.LtEq",
    "(min_known and max_known and min_value == 0 and max_value == 0) return if operator == TokenKind.EqEq",
    "((min_known and min_value >= 1) or (max_known and max_value <= (0 - 1))) return if operator == TokenKind.BangEq",
)
observed_rules = tuple(line.strip() for line in aph_provable.splitlines() if "return if operator == TokenKind." in line)
if observed_rules != production_rules:
    raise SystemExit("production proof-hole interval comparison rules changed; review and extend the soundness model")
try:
    aph_apply_bound = source_text.split("def aph_apply_bound(", 1)[1].split("\n        def aph_collect_fact(", 1)[0]
except IndexError as error:
    raise SystemExit("production proof-hole interval bound update is missing") from error
flipped_operator_map = "effective: TokenKind = operator if not flipped else (TokenKind.Lt if operator == TokenKind.Gt else (TokenKind.LtEq if operator == TokenKind.GtEq else (TokenKind.Gt if operator == TokenKind.Lt else (TokenKind.GtEq if operator == TokenKind.LtEq else operator))))"
if flipped_operator_map not in aph_apply_bound:
    raise SystemExit("production flipped comparison map changed; review and extend its equivalence proofs")
try:
    linear_add_safe = arithmetic_text.split("def linear_add_safe(", 1)[1].split("\n        def linear_sub_safe(", 1)[0]
    linear_sub_safe = arithmetic_text.split("def linear_sub_safe(", 1)[1].split("\n        def linear_mul_safe(", 1)[0]
except IndexError as error:
    raise SystemExit("production checked integer arithmetic helpers are missing") from error
for helper, fragments in (
    (linear_add_safe, (
        "return (false, 0) if right > 0 and left > linear_i64_max() - right",
        "return (false, 0) if right < 0 and left < linear_i64_min() - right",
        "return (true, left + right)",
    )),
    (linear_sub_safe, (
        "return (false, 0) if right > 0 and left < linear_i64_min() + right",
        "return (false, 0) if right < 0 and left > linear_i64_max() + right",
        "return (true, left - right)",
    )),
):
    if tuple(line.strip() for line in helper.splitlines() if line.strip().startswith("return ")) != fragments:
        raise SystemExit("checked integer overflow guards changed; review the interval threshold proofs")
for fragment in (
    "if effective == TokenKind.Gt:\n                    successor: (known: bool, value: i64) = linear_add_safe(value, 1)",
    "new_lo <- successor.value if successor.known\n                    sets_lo <- successor.known",
    "if effective == TokenKind.GtEq:\n                    new_lo <- value\n                    sets_lo <- true",
    "if effective == TokenKind.Lt:\n                    predecessor: (known: bool, value: i64) = linear_sub_safe(value, 1)",
    "new_hi <- predecessor.value if predecessor.known\n                    sets_hi <- predecessor.known",
    "if effective == TokenKind.LtEq:\n                    new_hi <- value\n                    sets_hi <- true",
    "if sets_lo and (not had_lo or new_lo > prior_lo):\n                    has_lo[index] <- true\n                    lo[index] <- new_lo",
    "if sets_hi and (not had_hi or new_hi < prior_hi):\n                    has_hi[index] <- true\n                    hi[index] <- new_hi",
):
    if fragment not in aph_apply_bound:
        raise SystemExit("production interval bound update changed; review its soundness proof")
for fragment in (
    "if slot < 0:\n                                    min_known <- false\n                                    max_known <- false",
    "min_known <- min_product.known and min_sum.known",
    "max_known <- max_product.known and max_sum.known",
    "min_value <- min_sum.value if min_sum.known",
    "max_value <- max_sum.value if max_sum.known",
    "else:\n                                        min_known <- false",
    "else:\n                                        max_known <- false",
):
    if fragment not in aph_provable:
        raise SystemExit("unknown or overflowed interval bounds no longer fail closed")

proof_models = {
    "interval_lower_strict_gt_sound": (
        "interval_lower_strict_gt_sound(value: i64, lower: i64) -> bool:",
        ("requires value >= lower", "requires lower >= 1"),
        "return value > 0",
    ),
    "interval_lower_ge_sound": (
        "interval_lower_ge_sound(value: i64, lower: i64) -> bool:",
        ("requires value >= lower", "requires lower >= 0"),
        "return value >= 0",
    ),
    "interval_upper_strict_lt_sound": (
        "interval_upper_strict_lt_sound(value: i64, upper: i64) -> bool:",
        ("requires value <= upper", "requires upper <= -1"),
        "return value < 0",
    ),
    "interval_upper_le_sound": (
        "interval_upper_le_sound(value: i64, upper: i64) -> bool:",
        ("requires value <= upper", "requires upper <= 0"),
        "return value <= 0",
    ),
    "singleton_zero_interval_eq_sound": (
        "singleton_zero_interval_eq_sound(value: i64, lower: i64, upper: i64) -> bool:",
        ("requires value >= lower and value <= upper", "requires lower == 0 and upper == 0"),
        "return value == 0",
    ),
    "separated_interval_neq_sound": (
        "separated_interval_neq_sound(value: i64, lower: i64, upper: i64) -> bool:",
        ("requires value >= lower and value <= upper", "requires lower >= 1 or upper <= -1"),
        "return value != 0",
    ),
}
for name, (signature, requirements, conclusion) in proof_models.items():
    section = function_section(proof_text, name)
    if signature not in section:
        raise SystemExit(f"{name} has an unexpected signature")
    observed_requires = tuple(line.strip() for line in section.splitlines() if line.strip().startswith("requires "))
    if observed_requires != requirements:
        raise SystemExit(f"{name} has an unexpected assumption set")
    if "ensure result == true" not in section or conclusion not in section:
        raise SystemExit(f"{name} no longer proves its interval conclusion")
declared_functions = set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", proof_text, re.MULTILINE))
if declared_functions != set(proof_models):
    raise SystemExit("interval soundness proof contains a missing or unreviewed theorem")

unknown_models = {
    "unknown_min_gt_rejected": (
        "unknown_min_gt_rejected(min_known: bool, min_value: i64) -> bool:",
        ("requires not min_known",),
        "return min_known and min_value >= 1",
    ),
    "unknown_min_ge_rejected": (
        "unknown_min_ge_rejected(min_known: bool, min_value: i64) -> bool:",
        ("requires not min_known",),
        "return min_known and min_value >= 0",
    ),
    "unknown_max_lt_rejected": (
        "unknown_max_lt_rejected(max_known: bool, max_value: i64) -> bool:",
        ("requires not max_known",),
        "return max_known and max_value < 0",
    ),
    "unknown_max_le_rejected": (
        "unknown_max_le_rejected(max_known: bool, max_value: i64) -> bool:",
        ("requires not max_known",),
        "return max_known and max_value <= 0",
    ),
    "unknown_min_eq_rejected": (
        "unknown_min_eq_rejected(min_known: bool, max_known: bool, min_value: i64, max_value: i64) -> bool:",
        ("requires not min_known",),
        "return min_known and max_known and min_value == 0 and max_value == 0",
    ),
    "unknown_max_eq_rejected": (
        "unknown_max_eq_rejected(min_known: bool, max_known: bool, min_value: i64, max_value: i64) -> bool:",
        ("requires not max_known",),
        "return min_known and max_known and min_value == 0 and max_value == 0",
    ),
    "unknown_both_neq_rejected": (
        "unknown_both_neq_rejected(min_known: bool, max_known: bool, min_value: i64, max_value: i64) -> bool:",
        ("requires not min_known and not max_known",),
        "return (min_known and min_value >= 1) or (max_known and max_value < 0)",
    ),
    "strict_negativity_is_at_most_minus_one": (
        "strict_negativity_is_at_most_minus_one(value: i64) -> bool:",
        ("requires value < 0",),
        "return value <= (0 - 1)",
    ),
    "at_most_minus_one_is_strictly_negative": (
        "at_most_minus_one_is_strictly_negative(value: i64) -> bool:",
        ("requires value <= (0 - 1)",),
        "return value < 0",
    ),
}
for name, (signature, requirements, conclusion) in unknown_models.items():
    section = function_section(unknown_text, name)
    if signature not in section:
        raise SystemExit(f"{name} has an unexpected signature")
    observed_requires = tuple(line.strip() for line in section.splitlines() if line.strip().startswith("requires "))
    if observed_requires != requirements:
        raise SystemExit(f"{name} has an unexpected assumption set")
    expected_ensure = "ensure result == false" if name not in {
        "strict_negativity_is_at_most_minus_one", "at_most_minus_one_is_strictly_negative"
    } else "ensure result == true"
    if expected_ensure not in section or conclusion not in section:
        raise SystemExit(f"{name} no longer proves its fail-closed interval fact")
if set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", unknown_text, re.MULTILINE)) != set(unknown_models):
    raise SystemExit("unknown-bound proof contains a missing or unreviewed theorem")

bound_update_models = {
    "flipped_gt_to_lt": ("left: i64, right: i64", "left > right", "right < left"),
    "flipped_lt_to_gt": ("left: i64, right: i64", "left < right", "right > left"),
    "flipped_ge_to_le": ("left: i64, right: i64", "left >= right", "right <= left"),
    "flipped_le_to_ge": ("left: i64, right: i64", "left <= right", "right >= left"),
    "flipped_eq_to_eq": ("left: i64, right: i64", "left == right", "right == left"),
    "flipped_neq_to_neq": ("left: i64, right: i64", "left != right", "right != left"),
    "flipped_lt_to_gt_back": ("left: i64, right: i64", "right < left", "left > right"),
    "flipped_gt_to_lt_back": ("left: i64, right: i64", "right > left", "left < right"),
    "flipped_le_to_ge_back": ("left: i64, right: i64", "right <= left", "left >= right"),
    "flipped_ge_to_le_back": ("left: i64, right: i64", "right >= left", "left <= right"),
    "flipped_eq_to_eq_back": ("left: i64, right: i64", "right == left", "left == right"),
    "flipped_neq_to_neq_back": ("left: i64, right: i64", "right != left", "left != right"),
    "stronger_lower_bound_sound": (
        "value: i64, previous: i64, candidate: i64",
        "value >= previous and value >= candidate",
        "value >= (previous if previous > candidate else candidate)",
    ),
    "weaker_lower_bound_preserves_soundness": (
        "value: i64, previous: i64, candidate: i64",
        "value >= previous and candidate <= previous", "value >= candidate"
    ),
    "stronger_upper_bound_sound": (
        "value: i64, previous: i64, candidate: i64",
        "value <= previous and value <= candidate",
        "value <= (previous if previous < candidate else candidate)",
    ),
    "weaker_upper_bound_preserves_soundness": (
        "value: i64, previous: i64, candidate: i64",
        "value <= previous and candidate >= previous", "value <= candidate"
    ),
    "strict_lower_threshold_forward": (
        "value: i64, bound: i64",
        "bound < 9223372036854775807 and value > bound",
        "value >= bound + 1",
    ),
    "strict_lower_threshold_reverse": (
        "value: i64, bound: i64",
        "bound < 9223372036854775807 and value >= bound + 1",
        "value > bound",
    ),
    "strict_upper_threshold_forward": (
        "value: i64, bound: i64",
        "bound > (0 - 9223372036854775807 - 1) and value < bound",
        "value <= bound - 1",
    ),
    "strict_upper_threshold_reverse": (
        "value: i64, bound: i64",
        "bound > (0 - 9223372036854775807 - 1) and value <= bound - 1",
        "value < bound",
    ),
}
for name, (parameters, assumption, conclusion) in bound_update_models.items():
    section = function_section(bound_updates_text, name)
    if f"def {name}({parameters}) -> bool:" not in section:
        raise SystemExit(f"{name} has an unexpected signature")
    observed_requires = tuple(line.strip() for line in section.splitlines() if line.strip().startswith("requires "))
    if observed_requires != (f"requires {assumption}",):
        raise SystemExit(f"{name} has an unexpected assumption set")
    if "ensure result == true" not in section or f"return {conclusion}" not in section:
        raise SystemExit(f"{name} no longer proves its interval update law")
if set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", bound_updates_text, re.MULTILINE)) != set(bound_update_models):
    raise SystemExit("bound-update proof contains a missing or unreviewed theorem")

negative_models = {
    "lower_zero_does_not_prove_strict_gt": (
        "lower_zero_does_not_prove_strict_gt(value: i64, lower: i64) -> bool:",
        ("requires value >= lower and lower == 0 and value == 0",),
        "return value > 0",
    ),
    "negative_lower_does_not_prove_ge": (
        "negative_lower_does_not_prove_ge(value: i64, lower: i64) -> bool:",
        ("requires value >= lower and lower == -1 and value == -1",),
        "return value >= 0",
    ),
    "upper_zero_does_not_prove_strict_lt": (
        "upper_zero_does_not_prove_strict_lt(value: i64, upper: i64) -> bool:",
        ("requires value <= upper and upper == 0 and value == 0",),
        "return value < 0",
    ),
    "positive_upper_does_not_prove_le": (
        "positive_upper_does_not_prove_le(value: i64, upper: i64) -> bool:",
        ("requires value <= upper and upper == 1 and value == 1",),
        "return value <= 0",
    ),
    "nonsingleton_interval_does_not_prove_eq": (
        "nonsingleton_interval_does_not_prove_eq(value: i64, lower: i64, upper: i64) -> bool:",
        ("requires value >= lower and value <= upper and lower == 0 and upper == 1 and value == 1",),
        "return value == 0",
    ),
    "interval_containing_zero_does_not_prove_neq": (
        "interval_containing_zero_does_not_prove_neq(value: i64, lower: i64, upper: i64) -> bool:",
        ("requires value >= lower and value <= upper and lower == -1 and upper == 1 and value == 0",),
        "return value != 0",
    ),
}
for name, (signature, requirements, conclusion) in negative_models.items():
    section = function_section(negative_text, name)
    if signature not in section:
        raise SystemExit(f"{name} has an unexpected signature")
    observed_requires = tuple(line.strip() for line in section.splitlines() if line.strip().startswith("requires "))
    if observed_requires != requirements:
        raise SystemExit(f"{name} has unexpected counterexample conditions")
    if "ensure result == true" not in section or conclusion not in section:
        raise SystemExit(f"{name} no longer tests the rejected interval claim")
if set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text, re.MULTILINE)) != set(negative_models):
    raise SystemExit("interval-threshold negative controls contain a missing or unreviewed case")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("interval soundness proof requires a strict proof build")
compiler = manifest["compiler"]
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != compiler["source_revision"]:
    raise SystemExit("proof product compiler revision does not match the checked-out compiler HEAD")

stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST_CHECKSUM,
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    PROOF,
    NEGATIVE,
    UNKNOWN,
    BOUND_UPDATES,
    SOURCE,
    ARITH_SOURCE,
    *source_include_closure([PROOF, NEGATIVE, UNKNOWN, BOUND_UPDATES, SOURCE, ARITH_SOURCE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run() -> tuple[int, dict]:
    result = subprocess.run([str(BIN), "--json", str(PROOF)], capture_output=True,
                           text=True, timeout=60)
    report = json.loads(result.stdout)
    assert result.returncode == 0 and report["status"] == report["verification_state"] == "proved"
    assert report["summary"]["declarations"] == len(proof_models)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["semantic_diagnostics"]
    assert report["summary"]["obligations"] == report["summary"]["proven"] == 12
    assert report["replay"] == {"certificates": 12, "replayed": 12, "gaps": 0}
    assert not report["findings"]
    assert not report["trust"]["trusted_assumptions"]
    verified = {item["name"] for item in report["declaration_details"] if item.get("verified")}
    assert verified == set(proof_models)
    return result.returncode, report


_, first = run()
assert first == run()[1], "interval soundness proof report changed across identical runs"


def run_negative() -> dict:
    result = subprocess.run([str(BIN), "--json", str(NEGATIVE)], capture_output=True,
                            text=True, timeout=60)
    report = json.loads(result.stdout)
    assert result.returncode != 0 and report["status"] == "failed" and report["verification_state"] == "unknown"
    assert report["summary"]["declarations"] == len(negative_models)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["semantic_diagnostics"]
    assert report["summary"]["obligations"] == 12
    assert report["summary"]["proven"] == report["summary"]["failed"] == len(negative_models)
    assert report["replay"] == {"certificates": 6, "replayed": 6, "gaps": 0}
    assert not report["trust"]["trusted_assumptions"]
    assert {(item["name"], item["kind"]) for item in report["findings"]} == {
        (name, "ensure-unproven") for name in negative_models
    }
    return report


negative_first = run_negative()
assert negative_first == run_negative(), "interval-threshold rejection report changed across identical runs"


def run_unknown() -> tuple[int, dict]:
    result = subprocess.run([str(BIN), "--json", str(UNKNOWN)], capture_output=True,
                            text=True, timeout=60)
    report = json.loads(result.stdout)
    assert result.returncode == 0 and report["status"] == report["verification_state"] == "proved"
    assert report["summary"]["declarations"] == len(unknown_models)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["semantic_diagnostics"]
    assert report["summary"]["obligations"] == report["summary"]["proven"] == 18
    assert report["replay"] == {"certificates": 18, "replayed": 18, "gaps": 0}
    assert not report["findings"]
    assert not report["trust"]["trusted_assumptions"]
    verified = {item["name"] for item in report["declaration_details"] if item.get("verified")}
    assert verified == set(unknown_models)
    return result.returncode, report


_, unknown_first = run_unknown()
assert unknown_first == run_unknown()[1], "unknown-bound proof report changed across identical runs"


def run_bound_updates() -> tuple[int, dict]:
    result = subprocess.run([str(BIN), "--json", str(BOUND_UPDATES)], capture_output=True,
                            text=True, timeout=60)
    report = json.loads(result.stdout)
    assert result.returncode == 0 and report["status"] == report["verification_state"] == "proved"
    assert report["summary"]["declarations"] == len(bound_update_models)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["semantic_diagnostics"]
    assert report["summary"]["obligations"] == report["summary"]["proven"] == 40
    assert report["replay"] == {"certificates": 40, "replayed": 40, "gaps": 0}
    assert not report["findings"]
    assert not report["trust"]["trusted_assumptions"]
    verified = {item["name"] for item in report["declaration_details"] if item.get("verified")}
    assert verified == set(bound_update_models)
    return result.returncode, report


_, bound_updates_first = run_bound_updates()
assert bound_updates_first == run_bound_updates()[1], "bound-update proof report changed across identical runs"

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
if hashes_before != hashes_after:
    raise SystemExit("proof gate inputs changed while the interval soundness checker was running")
