"""Require strict source-linked replay for exact cache option-key equality."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product

root = Path(__file__).resolve().parents[2]
prover = Path(os.environ.get("ELISA_PROOF_ROOT", str(root.parent / "elisa-proof"))).resolve(strict=True)
binary = Path(os.environ.get("ELISA_PROOF_BIN", str(prover / "build/elisa-proof"))).resolve(strict=True)
if not __debug__:
    raise SystemExit("run without Python -O")
try:
    product_manifest = require_current_product(binary, prover)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
compiler_head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

here = Path(__file__).resolve().parent
manifest = binary.with_name(binary.name + ".manifest.json")
manifest_checksum = manifest.with_name(manifest.name + ".sha256")
token_source = root / "src/lexer/tokens.elisa"
view_source = root / "src/lexer/source_view.elisa"
parser_source = root / "src/parser/parser.elisa"
options_source = root / "src/semantic/incremental_semantic_options.elisa"
facts_source = root / "src/semantic/incremental_function_facts.elisa"
codec_source = root / "src/semantic/incremental_snapshot_codec.elisa"
semantic_source = root / "src/semantic/semantic.elisa"
driver_source = root / "src/driver/elisac_incremental_cache.elisa"
source_probes_source = root / "src/driver/elisac_source_probes.elisa"
control_source = root / "test/parity/incremental_codec_integrity_control.elisa"
positive_source = here / "incremental_semantic_options_key.elisa"
negative_source = here / "incremental_semantic_options_key_rejected.elisa"

def included_sources(seeds):
    discovered = set()
    pending = list(seeds)
    while pending:
        source = pending.pop().resolve(strict=True)
        if source in discovered:
            continue
        if source.suffix != ".elisa" or not source.is_relative_to(root):
            raise SystemExit(f"proof include escapes compiler source tree: {source}")
        discovered.add(source)
        source_text = source.read_text()
        for match in re.finditer(r'^\s*include\s+"([^"]+)"', source_text, re.MULTILINE):
            dependency = (source.parent / match.group(1)).resolve()
            if dependency.exists() and dependency.suffix == ".elisa":
                pending.append(dependency)
    return discovered

elisa_sources = included_sources([positive_source, negative_source])
inputs = [binary, manifest, manifest_checksum, prover / "ELISA_COMPILER_REV",
          here / "proof_product_gate.py", Path(__file__), token_source, view_source, parser_source,
          options_source, facts_source, codec_source, semantic_source, driver_source,
          source_probes_source, control_source, *sorted(elisa_sources)]
hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}

options_text = options_source.read_text()
facts_text = facts_source.read_text()
codec_text = codec_source.read_text()
semantic_text = semantic_source.read_text()
driver_text = driver_source.read_text()
source_probes_text = source_probes_source.read_text()
control_text = control_source.read_text()
positive_text = positive_source.read_text()
negative_text = negative_source.read_text()

assert "const INCREMENTAL_SEMANTIC_OPTIONS_KEY_LENGTH: usize = 26" in options_text
assert "def incremental_semantic_options_key_valid(" in options_text
assert "def incremental_semantic_options_key_equal(" in options_text
assert "def incremental_semantic_options_key_fingerprint(" in options_text
assert "return incremental_semantic_options_key_fingerprint(key)" in options_text
assert "options_key: mutable darray[u8]" in facts_text
assert "incremental_semantic_options_key_equal(previous.options_key, current.options_key)" in facts_text
assert "const INCREMENTAL_FUNCTION_FACTS_SCHEMA: u32 = 2" in facts_text
assert "const INCREMENTAL_SNAPSHOT_CODEC_VERSION: u64 = 2" in codec_text
assert "incremental_semantic_options_key_valid(snapshot.options_key)" in codec_text
assert "bytes.extend(snapshot.options_key)" in codec_text
assert "encoded.bytes[112 + key_index] == options_key[key_index]" in control_text
assert "146 + snapshot.bytes.count.u64()" in codec_text
assert "for key_index in 0..<INCREMENTAL_SEMANTIC_OPTIONS_KEY_LENGTH" in codec_text
assert "key_byte != options_key[key_index]" in codec_text
assert "146 + byte_count + function_count * 72" in codec_text
assert 'include "./incremental_semantic_options.elisa"' in semantic_text
assert "incremental_semantic_options_encode(options, &options_key)" in driver_text
assert "incremental_semantic_options_key_fingerprint(options_key)" in driver_text
assert "if cache_directory.count > 0:\n        options_key_valid <- Semantic::incremental_semantic_options_encode(options, &options_key)" in driver_text
assert "options: Semantic::IncrementalSemanticOptions = stage1_semantic_options(policy_source, policy_length)" in driver_text
assert "and options_fingerprint != 0" not in driver_text
assert "def stage1_semantic_options(" in source_probes_text
assert "incremental_decode_snapshot(stored.bytes, semantic_fingerprint, options_fingerprint, options_key)" in driver_text
assert "incremental_collect_function_facts(file, analyzed_source, analyzed_length, tokens, source_path, semantic_fingerprint, options_fingerprint, options_key, previous, has_previous)" in driver_text
assert "changed_options: IncrementalSemanticSnapshot = incremental_collect_function_facts" in control_text
assert ", 17, 29, changed_options_key, decoded.snapshot, true)" in control_text
assert "assert not changed_options.surface_compatible" in control_text
assert "wrong_colliding_options: IncrementalSnapshotDecodeResult = incremental_decode_snapshot(encoded.bytes, 17, 29, changed_options_key)" in control_text
assert 'include "../../src/parser/parser.elisa"' in positive_text
assert 'include "../../src/semantic/incremental_semantic_options.elisa"' in positive_text
assert 'include "../../src/semantic/incremental_function_facts.elisa"' in positive_text
assert 'include "../../src/semantic/incremental_snapshot_codec.elisa"' in positive_text
assert "Semantic::incremental_semantic_options_key_equal(key, key)" in positive_text
assert "Semantic::incremental_semantic_options_key_equal(original, changed)" in positive_text
assert "Semantic::incremental_encode_snapshot(snapshot)" in positive_text
assert "Semantic::incremental_decode_snapshot(encoded.bytes, 17, snapshot.options_fingerprint, changed)" in positive_text
assert "Semantic::incremental_semantic_options_key_equal(original, changed)" in negative_text
assert "Semantic::incremental_decode_snapshot(encoded.bytes, 17, snapshot.options_fingerprint, changed)" in negative_text


def run(path):
    process = subprocess.run([str(binary), "--json", str(path)],
                             capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(positive_source)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 7
assert not positive["findings"]
assert positive == run(positive_source)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {"schema_shaped_option_key_is_valid", "valid_option_key_compares_equal_to_itself",
        "changed_flag_key_compares_unequal", "option_key_fingerprint_matches_fixed_wire_key",
        "invalid_option_key_has_no_fingerprint", "exact_option_key_survives_snapshot_codec",
        "changed_exact_key_is_rejected_with_same_prefilter"} <= verified

code, negative = run(negative_source)
false_claims = {"distinct_valid_option_keys_compare_equal",
                "changed_exact_key_is_accepted_with_same_prefilter"}
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(false_claims) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == false_claims
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not false_claims & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(binary, prover) == product_manifest, "proof product or source tree changed during replay"
assert subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                      check=True, capture_output=True, text=True).stdout.strip() == compiler_head
print(json.dumps({"admitted": True,
                  "scope": "exact options-key identity through snapshot encode, decode, and reuse",
                  "producer_proven": positive["summary"]["proven"],
                  "independently_replayed": positive["replay"]["replayed"],
                  "false_claims_rejected": sorted(false_claims),
                  "same_fingerprint_changed_key_rejected_by_decode_and_reuse": True,
                  "sources_sha256": hashes}, sort_keys=True))
