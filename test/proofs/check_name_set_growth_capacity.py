"""Replay NameSet load-bound proofs against the production growth and insert paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="validate proof/source bindings without invoking the proof product")
ARGS = parser.parse_args()


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
HELPER = ROOT / "src/semantic/name_set.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "name_set_growth_capacity.elisa"
NEGATIVE = HERE / "name_set_growth_capacity_rejected.elisa"
POSITIVE_1025 = HERE / "name_set_growth_capacity_1025.elisa"
NEGATIVE_1025 = HERE / "name_set_growth_capacity_1025_rejected.elisa"
POSITIVE_2049 = HERE / "name_set_growth_capacity_2049.elisa"
NEGATIVE_2049 = HERE / "name_set_growth_capacity_2049_rejected.elisa"
POSITIVE_4097 = HERE / "name_set_growth_capacity_4097.elisa"
NEGATIVE_4097 = HERE / "name_set_growth_capacity_4097_rejected.elisa"
POSITIVE_8193 = HERE / "name_set_growth_capacity_8193.elisa"
NEGATIVE_8193 = HERE / "name_set_growth_capacity_8193_rejected.elisa"
POSITIVE_16385 = HERE / "name_set_growth_capacity_16385.elisa"
NEGATIVE_16385 = HERE / "name_set_growth_capacity_16385_rejected.elisa"

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
positive_1025_text = POSITIVE_1025.read_text()
negative_1025_text = NEGATIVE_1025.read_text()
positive_2049_text = POSITIVE_2049.read_text()
negative_2049_text = NEGATIVE_2049.read_text()
positive_4097_text = POSITIVE_4097.read_text()
negative_4097_text = NEGATIVE_4097.read_text()
positive_8193_text = POSITIVE_8193.read_text()
negative_8193_text = NEGATIVE_8193.read_text()
positive_16385_text = POSITIVE_16385.read_text()
negative_16385_text = NEGATIVE_16385.read_text()
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
proof_1025_hashes = {
    "name_set_capacity_two_thousand_forty_eight_covers_next_five_hundred_twelve_insertions": "a474a98f2b01acb662d6cff926dec5889919cc2e5c9c623465388019fc6735cf",
    "name_set_one_thousand_twenty_fifth_entry_doubles_capacity": "8177a8b8af6325036bd7fe6aaf1c26f9fcd61f0cbf9bf3933ba4ed52d322607b",
    "one_thousand_twenty_fifth_name_rehash_keeps_three_thousand_seventy_one_slots_empty": "accf2520a95575df20a9a9a12bdafd577bc50b1fc5aa727fdedc1ddaef5a4295",
}
for proof_name, expected_hash in proof_1025_hashes.items():
    digest = hashlib.sha256(compact(function_section(positive_1025_text, proof_name)).encode()).hexdigest()
    if digest != expected_hash:
        raise SystemExit(f"NameSet 1025th-entry theorem {proof_name} changed since source binding")
false_1025_hash = hashlib.sha256(compact(function_section(
    negative_1025_text, "false_two_thousand_forty_eight_slots_cover_the_one_thousand_twenty_fifth_entry")).encode()).hexdigest()
if false_1025_hash != "a60741b800511d82adfc5b70b054fd4b1b81138e37a146e5e04e0052c96e9edd":
    raise SystemExit("1025th-entry false control changed since source binding")
if set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_1025_text)) != set(proof_1025_hashes):
    raise SystemExit("NameSet 1025th-entry proof inventory changed")
proof_2049_hashes = {
    "name_set_capacity_four_thousand_ninety_six_covers_next_one_thousand_twenty_four_insertions": "4c618c1cda4e0520458a4ec62bc1be9f1824b992241f3eb03bb32b1a4153415f",
    "name_set_two_thousand_forty_ninth_entry_doubles_capacity": "9f255b05202c0e64ea194833d9b1efa8d8468d1290872fca5aa91c668b347301",
    "two_thousand_forty_ninth_name_rehash_keeps_six_thousand_one_hundred_forty_three_slots_empty": "ad7be2d962a028c1fe5515c0e92759474d50ba25c36ca5572d91186774600b6b",
}
for proof_name, expected_hash in proof_2049_hashes.items():
    digest = hashlib.sha256(compact(function_section(positive_2049_text, proof_name)).encode()).hexdigest()
    if digest != expected_hash:
        raise SystemExit(f"NameSet 2049th-entry theorem {proof_name} changed since source binding")
false_2049_hash = hashlib.sha256(compact(function_section(
    negative_2049_text, "false_four_thousand_ninety_six_slots_cover_the_two_thousand_forty_ninth_entry")).encode()).hexdigest()
if false_2049_hash != "81805c3b6282d204bdcacdcedddc58874b0b34dc475688c95bc4ea41d98d3843":
    raise SystemExit("2049th-entry false control changed since source binding")
if set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_2049_text)) != set(proof_2049_hashes):
    raise SystemExit("NameSet 2049th-entry proof inventory changed")
proof_4097_hashes = {
    "name_set_capacity_eight_thousand_one_hundred_ninety_two_covers_next_four_thousand_ninety_six_insertions": "d6fd8e612731c253cc98c56b16f9d6d4ff40bddb46ffd6f72a397ab2b3ea5f39",
    "name_set_four_thousand_ninety_seventh_entry_doubles_capacity": "f1aa4e176283086d84bb957536e43ef335b356558ab323f6dfdab47f23da7d97",
    "four_thousand_ninety_seventh_name_rehash_keeps_twelve_thousand_two_hundred_eighty_seven_slots_empty": "7cc04c6944a13db0e4c3a3a2ca3c582b3d5c2f5ef7895471d1ad271dd279b46d",
}
for proof_name, expected_hash in proof_4097_hashes.items():
    digest = hashlib.sha256(compact(function_section(positive_4097_text, proof_name)).encode()).hexdigest()
    if digest != expected_hash:
        raise SystemExit(f"NameSet 4097th-entry theorem {proof_name} changed since source binding")
false_4097_hash = hashlib.sha256(compact(function_section(
    negative_4097_text, "false_eight_thousand_one_hundred_ninety_two_slots_cover_the_four_thousand_ninety_seventh_entry")).encode()).hexdigest()
if false_4097_hash != "458a80fd5bede1ad23e289a70b51ee96a242d713937199e4495b717cbbf1ec46":
    raise SystemExit("4097th-entry false control changed since source binding")
if set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_4097_text)) != set(proof_4097_hashes):
    raise SystemExit("NameSet 4097th-entry proof inventory changed")
proof_8193_hashes = {
    "name_set_capacity_sixteen_thousand_three_hundred_eighty_four_covers_next_four_thousand_ninety_six_insertions": "eeb9e452b1d479115b01a835705d983b50e7c981bf996584bde856ac2af7a23c",
    "name_set_eight_thousand_one_hundred_ninety_third_entry_doubles_capacity": "40901f25b13d2499f17450d4cc5f3b13503247415e67b73cc7eebbc00d173a03",
    "eight_thousand_one_hundred_ninety_third_name_rehash_keeps_twenty_four_thousand_five_hundred_seventy_five_slots_empty": "33e3bd20bcee497bb7f30fdba42d64825843bcba42badfdf517c588d0c391f97",
}
for proof_name, expected_hash in proof_8193_hashes.items():
    digest = hashlib.sha256(compact(function_section(positive_8193_text, proof_name)).encode()).hexdigest()
    if digest != expected_hash:
        raise SystemExit(f"NameSet 8193rd-entry theorem {proof_name} changed since source binding")
false_8193_hash = hashlib.sha256(compact(function_section(
    negative_8193_text, "false_sixteen_thousand_three_hundred_eighty_four_slots_cover_the_eight_thousand_one_hundred_ninety_third_entry")).encode()).hexdigest()
if false_8193_hash != "2c930d2f49a704e3d25c918bd7b33027d7ee778bfb6b90c0d5b06c8d36165039":
    raise SystemExit("8193rd-entry false control changed since source binding")
if set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_8193_text)) != set(proof_8193_hashes):
    raise SystemExit("NameSet 8193th-entry proof inventory changed")
proof_16385_hashes = {
    "name_set_capacity_thirty_two_thousand_seven_hundred_sixty_eight_covers_next_eight_thousand_one_hundred_ninety_two_insertions": "8c85f092ec10453132a3c1a21be3bdf8b59bd78f1d39986b52ebafd4bcd1857d",
    "name_set_sixteen_thousand_three_hundred_eighty_fifth_entry_doubles_capacity": "4bf26dee7af629d21d5ad57158baf02eb999c4edb819af69505c3d2bbace3979",
    "sixteen_thousand_three_hundred_eighty_fifth_name_rehash_keeps_forty_nine_thousand_one_hundred_fifty_one_slots_empty": "e4d5edfd66b53804241d2cc41beb120bd44217df3a71320bc8c90a7b39431d27",
}
for proof_name, expected_hash in proof_16385_hashes.items():
    digest = hashlib.sha256(compact(function_section(positive_16385_text, proof_name)).encode()).hexdigest()
    if digest != expected_hash:
        raise SystemExit(f"NameSet 16385th-entry theorem {proof_name} changed since source binding")
false_16385_hash = hashlib.sha256(compact(function_section(
    negative_16385_text, "false_thirty_two_thousand_seven_hundred_sixty_eight_slots_cover_the_sixteen_thousand_three_hundred_eighty_fifth_entry")).encode()).hexdigest()
if false_16385_hash != "eb73e5ba83aefb4f3fed0dbe26991368d83347ac972af5bdc19dca34448eb5af":
    raise SystemExit("16385th-entry false control changed since source binding")
if set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_16385_text)) != set(proof_16385_hashes):
    raise SystemExit("NameSet 16385th-entry proof inventory changed")
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

if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(positive_names) + len(proof_1025_hashes) + len(proof_2049_hashes) + len(proof_4097_hashes) + len(proof_8193_hashes) + len(proof_16385_hashes),
        "false_controls": len(negative_names) + 5,
        "highest_growth_boundary": 16385,
    }, sort_keys=True))
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("NameSet capacity proof requires a strict proof build")

inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, Path(__file__), HELPER, SEMANTIC, POSITIVE, NEGATIVE,
          POSITIVE_1025, NEGATIVE_1025, POSITIVE_2049, NEGATIVE_2049,
          POSITIVE_4097, NEGATIVE_4097, POSITIVE_8193, NEGATIVE_8193,
          POSITIVE_16385, NEGATIVE_16385]
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

code, positive_1025 = run(POSITIVE_1025)
assert code == 0 and positive_1025["status"] == positive_1025["verification_state"] == "proved"
assert positive_1025["summary"]["proven"] == positive_1025["summary"]["obligations"] == 6
assert positive_1025["replay"]["gaps"] == 0 and not positive_1025["findings"]
assert {item["name"] for item in positive_1025["declaration_details"] if item.get("verified")} == set(proof_1025_hashes)

code, positive_2049 = run(POSITIVE_2049)
assert code == 0 and positive_2049["status"] == positive_2049["verification_state"] == "proved"
assert positive_2049["summary"]["proven"] == positive_2049["summary"]["obligations"] == 6
assert positive_2049["replay"]["gaps"] == 0 and not positive_2049["findings"]
assert {item["name"] for item in positive_2049["declaration_details"] if item.get("verified")} == set(proof_2049_hashes)

code, positive_4097 = run(POSITIVE_4097)
assert code == 0 and positive_4097["status"] == positive_4097["verification_state"] == "proved"
assert positive_4097["summary"]["proven"] == positive_4097["summary"]["obligations"] == 6
assert positive_4097["replay"]["gaps"] == 0 and not positive_4097["findings"]
assert {item["name"] for item in positive_4097["declaration_details"] if item.get("verified")} == set(proof_4097_hashes)

code, positive_8193 = run(POSITIVE_8193)
assert code == 0 and positive_8193["status"] == positive_8193["verification_state"] == "proved"
assert positive_8193["summary"]["proven"] == positive_8193["summary"]["obligations"] == 6
assert positive_8193["replay"]["gaps"] == 0 and not positive_8193["findings"]
assert {item["name"] for item in positive_8193["declaration_details"] if item.get("verified")} == set(proof_8193_hashes)

code, positive_16385 = run(POSITIVE_16385)
assert code == 0 and positive_16385["status"] == positive_16385["verification_state"] == "proved"
assert positive_16385["summary"]["proven"] == positive_16385["summary"]["obligations"] == 6
assert positive_16385["replay"]["gaps"] == 0 and not positive_16385["findings"]
assert {item["name"] for item in positive_16385["declaration_details"] if item.get("verified")} == set(proof_16385_hashes)

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

code, negative_1025 = run(NEGATIVE_1025)
assert code == 1 and negative_1025["status"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative_1025["findings"]] == [
    ("ensure-unproven", "false_two_thousand_forty_eight_slots_cover_the_one_thousand_twenty_fifth_entry")]

code, negative_2049 = run(NEGATIVE_2049)
assert code == 1 and negative_2049["status"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative_2049["findings"]] == [
    ("ensure-unproven", "false_four_thousand_ninety_six_slots_cover_the_two_thousand_forty_ninth_entry")]

code, negative_4097 = run(NEGATIVE_4097)
assert code == 1 and negative_4097["status"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative_4097["findings"]] == [
    ("ensure-unproven", "false_eight_thousand_one_hundred_ninety_two_slots_cover_the_four_thousand_ninety_seventh_entry")]

code, negative_8193 = run(NEGATIVE_8193)
assert code == 1 and negative_8193["status"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative_8193["findings"]] == [
    ("ensure-unproven", "false_sixteen_thousand_three_hundred_eighty_four_slots_cover_the_eight_thousand_one_hundred_ninety_third_entry")]

code, negative_16385 = run(NEGATIVE_16385)
assert code == 1 and negative_16385["status"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative_16385["findings"]] == [
    ("ensure-unproven", "false_thirty_two_thousand_seven_hundred_sixty_eight_slots_cover_the_sixteen_thousand_three_hundred_eighty_fifth_entry")]

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "NameSet growth thresholds through the sixteen-thousand-three-hundred-eighty-fifth insertion and initial-table probe-step bounds",
                  "positive_obligations": positive["summary"]["proven"] + positive_1025["summary"]["proven"] + positive_2049["summary"]["proven"] + positive_4097["summary"]["proven"] + positive_8193["summary"]["proven"] + positive_16385["summary"]["proven"],
                  "false_claims_rejected": len(negative["findings"]) + len(negative_1025["findings"]) + len(negative_2049["findings"]) + len(negative_4097["findings"]) + len(negative_8193["findings"]) + len(negative_16385["findings"]),
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
