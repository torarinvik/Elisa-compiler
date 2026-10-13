"""Replay NameSet load-bound proofs against the production growth and insert paths."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
HELPER = ROOT / "src/semantic/name_set.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "name_set_growth_capacity.elisa"
NEGATIVE = HERE / "name_set_growth_capacity_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


def compact(text: str) -> str:
    return "".join(text.split())


helper_text = HELPER.read_text()
semantic_text = SEMANTIC.read_text()
if 'include "./name_set.elisa"' not in semantic_text:
    raise SystemExit("semantic pass no longer includes the NameSet implementation")

grow = compact(function_section(helper_text, "name_set_grow"))
expected_grow_fragments = (
    "capacity:mutableusize=16",
    "whilecapacity<(set.names.count+1)*2|capacity,set|:",
    "capacity<-capacity*2",
    "set.slots.truncate(0)",
    "set.slots.reserve(capacity)",
    "for slot_index in 0..<capacity|set|:",
    "set.slots.push(NAME_SET_SLOT_EMPTY)",
    "forrowin0..<set.names.count|set|:",
    "slot:usize=name_set_slot(set,set.names[row])",
    "set.slots[slot]<-row.u32()",
)
if any(compact(fragment) not in grow for fragment in expected_grow_fragments):
    raise SystemExit("NameSet growth no longer establishes the checked capacity threshold before rehash")

add = compact(function_section(helper_text, "name_set_add"))
expected_add_fragments = (
    "name_set_grow(set)ifset.slots.count<(set.names.count+1)*2",
    "slot:usize=name_set_slot(set,name)",
    "returnifset.slots[slot]!=NAME_SET_SLOT_EMPTY",
    "set.slots[slot]<-set.names.count.u32()",
    "set.names.push(name)",
)
if any(compact(fragment) not in add for fragment in expected_add_fragments):
    raise SystemExit("NameSet insertion no longer grows before a fresh insertion and preserves duplicate count")

slot = compact(function_section(helper_text, "name_set_slot"))
expected_slot_fragments = (
    "mask:usize=set.slots.count-1",
    "slot:mutableusize=name_hash(name).usize()&mask",
    "while set.slots[slot]!=NAME_SET_SLOT_EMPTY",
    "return slot if set.names[set.slots[slot].usize()]==name",
    "slot<-(slot+1)&mask",
)
if any(compact(fragment) not in slot for fragment in expected_slot_fragments):
    raise SystemExit("NameSet probing no longer follows the checked linear-probe path")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
positive_names = {
    "initial_capacity_covers_small_sets",
    "add_preserves_count_for_duplicate_name",
    "a_fresh_name_increments_the_count_once",
    "name_set_capacity_stays_initial_through_eighth_entry",
    "name_set_ninth_entry_doubles_initial_capacity",
    "name_set_probe_step_stays_in_initial_table",
    "ninth_name_rehash_keeps_twenty_three_slots_empty",
    "name_set_capacity_thirty_two_covers_next_eight_insertions",
    "name_set_seventeenth_entry_doubles_capacity",
    "name_set_capacity_sixty_four_covers_next_sixteen_insertions",
    "name_set_thirty_third_entry_doubles_capacity",
    "name_set_capacity_one_twenty_eight_covers_next_thirty_two_insertions",
    "name_set_sixty_fifth_entry_doubles_capacity",
    "seventeenth_name_rehash_keeps_forty_seven_slots_empty",
    "thirty_third_name_rehash_keeps_ninety_five_slots_empty",
    "sixty_fifth_name_rehash_keeps_one_hundred_ninety_one_slots_empty",
    "name_set_one_hundred_twenty_ninth_entry_doubles_capacity",
    "one_hundred_twenty_ninth_name_rehash_keeps_three_hundred_eighty_three_slots_empty",
    "name_set_two_hundred_fifty_seventh_entry_doubles_capacity",
    "two_hundred_fifty_seventh_name_rehash_keeps_seven_hundred_sixty_seven_slots_empty",
    "name_set_five_hundred_thirteenth_entry_doubles_capacity",
    "five_hundred_thirteenth_name_rehash_keeps_one_thousand_five_hundred_thirty_five_slots_empty",
}
if not positive_names <= set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text)):
    raise SystemExit("NameSet capacity proof is missing a required theorem")
proof_hashes = {
    "name_set_capacity_stays_initial_through_eighth_entry": "96c3a518f6499846828e4905264d8d4126f08ec6b25f82523cf2e8189c5d133a",
    "name_set_ninth_entry_doubles_initial_capacity": "f7505f7756bafc685ad212b1823e241d1338fb5f09c6150da2e68f606f9290f2",
    "name_set_probe_step_stays_in_initial_table": "cb109ff96e03081d270b95df01a018c02b3aa312781fc7ee82aa3af59baae7fc",
    "ninth_name_rehash_keeps_twenty_three_slots_empty": "977a1b5a2ff790412df624818a49e0919269c5c0a7ba04a7e23afa6ce2f096b8",
    "name_set_capacity_thirty_two_covers_next_eight_insertions": "9e7d801dfaf2613754d0e4adaf0925443db97779fa422a582f1ca9c74d4265ae",
    "name_set_seventeenth_entry_doubles_capacity": "fe204ac4f29a11c577b8c790617bad6df5bb1a88f57b471d966707e96faaead6",
    "name_set_capacity_sixty_four_covers_next_sixteen_insertions": "3e863519090c0833b9b4fc941be8b516051d3e79ed547e6d27707e2a7bfa35f9",
    "name_set_thirty_third_entry_doubles_capacity": "16c60f25282b8cdac575f6193068a5fd441afe44e3875e2020884fb5a1fb1e30",
    "name_set_capacity_one_twenty_eight_covers_next_thirty_two_insertions": "857956bf7e7cfcd1cdf059d73288fc9ee81915f398a0986bdcb1d0ef766a58a5",
    "name_set_sixty_fifth_entry_doubles_capacity": "1f13244f88296fa413b134bc8d5a743816c346a85ca040cff027c36a610d6a26",
    "seventeenth_name_rehash_keeps_forty_seven_slots_empty": "c596217c3b900e8b69ca7fd27e74e9de09537c7f30bc2362652e7d387c960709",
    "thirty_third_name_rehash_keeps_ninety_five_slots_empty": "eddba8882643781b6106ead93090f857425042bc6d0c002cc386dab5a93a3758",
    "sixty_fifth_name_rehash_keeps_one_hundred_ninety_one_slots_empty": "0f2879c8ac3cb39312fc9d0f16d3844b796d1a698f3bffd295fcff1ba64cc63f",
    "name_set_one_hundred_twenty_ninth_entry_doubles_capacity": "bcd37e78b9e2c30acb4b43201a986c8032e95fabf53e5bafbc35731d2bffd031",
    "one_hundred_twenty_ninth_name_rehash_keeps_three_hundred_eighty_three_slots_empty": "b1b90006db928b677cb279e4cd74cba7e362a18dff8d001fe826bbce212b8fb4",
    "name_set_two_hundred_fifty_seventh_entry_doubles_capacity": "eb68e53ba6dedc41449a92cd235f2750490b504fb576047f807c4a0e82764040",
    "two_hundred_fifty_seventh_name_rehash_keeps_seven_hundred_sixty_seven_slots_empty": "5a6e9b0bbf73aa36a8fb00fd72e619b9cfa938a7bb0b546bb0063701864618a1",
    "name_set_five_hundred_thirteenth_entry_doubles_capacity": "a68ae2043927cef1436601a62b1d9af6fcf1092ef42ed4af9a44ce2b05195b43",
    "five_hundred_thirteenth_name_rehash_keeps_one_thousand_five_hundred_thirty_five_slots_empty": "34d8b3c6d6f9dde3f6f089617645de417bdf6fcd390b197f109a66a0de5577a4",
}
for proof_name, expected_hash in proof_hashes.items():
    digest = hashlib.sha256(compact(function_section(positive_text, proof_name)).encode()).hexdigest()
    if digest != expected_hash:
        raise SystemExit(f"NameSet boundary theorem {proof_name} changed since source binding")
negative_names = {
    "exact_growth_threshold_leaves_an_extra_empty_slot": "broad existing boundary control",
    "false_thirty_two_slots_cover_the_seventeenth_entry": "a full 32-slot table must grow before insertion",
    "false_sixty_four_slots_cover_the_thirty_third_entry": "a full 64-slot table must grow before insertion",
    "false_one_twenty_eight_slots_cover_the_sixty_fifth_entry": "a full 128-slot table must grow before insertion",
    "false_five_hundred_twelve_slots_cover_the_two_hundred_fifty_seventh_entry": "a full 512-slot table must grow before insertion",
    "false_one_thousand_twenty_four_slots_cover_the_five_hundred_thirteenth_entry": "a full 1024-slot table must grow before insertion",
}
for false_name in negative_names:
    if f"def {false_name}(" not in negative_text:
        raise SystemExit(f"NameSet boundary counterexample is missing: {false_name}")
false_hash = hashlib.sha256(compact(function_section(negative_text, "false_thirty_two_slots_cover_the_seventeenth_entry")).encode()).hexdigest()
if false_hash != "a74cbcf77dd791e53f4b9ccb160f0034cfe8e3311c8c5200fba63812f4f756c0":
    raise SystemExit("seventeenth-entry false control changed since source binding")
false_hash = hashlib.sha256(compact(function_section(negative_text, "false_sixty_four_slots_cover_the_thirty_third_entry")).encode()).hexdigest()
if false_hash != "be81f35295393a021866fbb968fc8b9b3f7768fe6d2906c82144518860d32735":
    raise SystemExit("thirty-third-entry false control changed since source binding")
false_hash = hashlib.sha256(compact(function_section(negative_text, "false_one_twenty_eight_slots_cover_the_sixty_fifth_entry")).encode()).hexdigest()
if false_hash != "b48248d7544ad56a9367ecd15df8a57fb88c595170703b66af00f18a9ca5d97e":
    raise SystemExit("sixty-fifth-entry false control changed since source binding")
false_hash = hashlib.sha256(compact(function_section(negative_text, "false_five_hundred_twelve_slots_cover_the_two_hundred_fifty_seventh_entry")).encode()).hexdigest()
if false_hash != "050fb5c6f6403a2801ded70a97c6cdccfffd1f4c638cc04922660f55f23ced16":
    raise SystemExit("two-hundred-fifty-seventh-entry false control changed since source binding")
false_hash = hashlib.sha256(compact(function_section(negative_text, "false_one_thousand_twenty_four_slots_cover_the_five_hundred_thirteenth_entry")).encode()).hexdigest()
if false_hash != "95ec63f59f07b6106c29200ee15e3b282322986ae5c82c0a8cc59904fb78c617":
    raise SystemExit("five-hundred-thirteenth-entry false control changed since source binding")
if "name_count <= 7" not in positive_text:
    raise SystemExit("initial-capacity theorem no longer covers the exact eight-entry range")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("NameSet capacity proof requires a strict proof build")

inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, Path(__file__), HELPER, SEMANTIC, POSITIVE, NEGATIVE]
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
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names <= verified
assert positive == run(POSITIVE)[1], "NameSet capacity proof changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "exact_growth_threshold_leaves_an_extra_empty_slot"),
    ("ensure-unproven", "false_thirty_two_slots_cover_the_seventeenth_entry"),
    ("ensure-unproven", "false_sixty_four_slots_cover_the_thirty_third_entry"),
    ("ensure-unproven", "false_one_twenty_eight_slots_cover_the_sixty_fifth_entry"),
    ("ensure-unproven", "false_five_hundred_twelve_slots_cover_the_two_hundred_fifty_seventh_entry"),
    ("ensure-unproven", "false_one_thousand_twenty_four_slots_cover_the_five_hundred_thirteenth_entry"),
]

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "NameSet growth thresholds through the sixty-fifth insertion and initial-table probe-step bounds",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claim_rejected": negative["findings"][0]["name"],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
