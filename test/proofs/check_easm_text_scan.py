"""Admit the source-linked EASM first-whitespace scan proof."""
import argparse
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
argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check production and proof source bindings without running Elisa-Proof")
ARGS = argument_parser.parse_args()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/backend/easm_text_scan.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
PARSER = ROOT / "src/backend/easm_verify_function.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
EASM_PARSE = ROOT / "src/backend/easm_parse.elisa"
POSITIVE = HERE / "easm_text_scan.elisa"
NEGATIVE = HERE / "easm_text_scan_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    for line in source.splitlines():
        for character in line:
            if in_string:
                output.append(character)
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == "#":
                break
            if character == '"':
                in_string = True
                output.append(character)
            elif not character.isspace():
                output.append(character)
    return "".join(output)


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


source_text = SOURCE.read_text()
source_compact = compact(source_text)
environment_text = ENV.read_text()
trim_bounds_spec = compact(function_section(source_text, "trim_bounds_spec"))
if not all(fragment in trim_bounds_spec for fragment in (
    "ghostdeftrim_bounds_spec(text:sview)",
    "ensureresult.start<=result.end",
    "ensureresult.end<=text.len",
    "returntrim_bounds_spec_from(text,trim_start_spec(text,0))",
)):
    raise SystemExit("ghost trim bounds no longer returns its ordered in-range span from the recursive trim specs")
trim_bounds_spec_from = compact(function_section(source_text, "trim_bounds_spec_from"))
if not all(fragment in trim_bounds_spec_from for fragment in (
    "ghostdeftrim_bounds_spec_from(text:sview,first:usize)",
    "requiresfirst<=text.len",
    "ensureresult.start<=result.end",
    "ensureresult.end<=text.len",
    "return(first,trim_end_spec(text,first,text.len))",
)):
    raise SystemExit("ghost trim bounds helper no longer shares the leading-trim endpoint")
for spec_name in ("find_from_spec", "find_spec"):
    if "ensureresult<=text.len" not in compact(function_section(source_text, spec_name)):
        raise SystemExit(f"ghost {spec_name} no longer exposes the bounded search-result fact")
if 'include "easm_text_scan.elisa"' not in environment_text:
    raise SystemExit("backend environment does not import the verified EASM text scanner")
if environment_text.index('include "easm_text_scan.elisa"') > environment_text.index('include "easm_verify_provenance.elisa"'):
    raise SystemExit("backend environment imports the EASM trim wrapper before its verified scanner")
if "returnEasmTextScan::first_space(text).usize()" not in compact(function_section(PARSER.read_text(), "easm_first_space")):
    raise SystemExit("production EASM whitespace helper no longer delegates to the verified scanner")
if "returnEasmTextScan::trim(text)" not in compact(function_section(PROVENANCE.read_text(), "easm_trim")):
    raise SystemExit("production EASM trim helper no longer delegates to the verified trim scanner")
for caller in (PARSER.read_text(), EASM_PARSE.read_text()):
    if "easm_first_space(" not in caller:
        raise SystemExit("an EASM parser source lost its use of the verified whitespace helper")
for caller in (PARSER.read_text(), PROVENANCE.read_text(), EASM_PARSE.read_text()):
    if "easm_find(" not in caller:
        raise SystemExit("an EASM parser source lost its use of the verified substring helper")
required_source = (
    "constASCII_SPACE:u8=32",
    "constASCII_TAB:u8=9",
    "constBYTE_INDEX_STEP:usize=1",
    "constSIGNED_INDEX_STEP:i64=1",
    "ensureresult>=0",
    "ensuretext.len<0impliesresult==0",
    "ensuretext.len>=0impliesresult<=text.len",
    "text.len<0orresult==text.lenor(result<text.lenand(text[result]==ASCII_SPACEortext[result]==ASCII_TAB))",
    "ensure(forallprefix_indexin0..<result:text.len<0orprefix_index>=text.lenor(text[prefix_index]!=ASCII_SPACEandtext[prefix_index]!=ASCII_TAB))",
    "whileindex<text.len|index,text|",
    "decreasestext.len-index",
    "invariantindex>=0",
    "invarianttext.len<0impliesindex==0",
    "invarianttext.len>=0impliesindex<=text.len",
    "invariantforallprefix_indexin0..<index:text.len<0orprefix_index>=text.lenor(text[prefix_index]!=ASCII_SPACEandtext[prefix_index]!=ASCII_TAB)",
    "returnindexiftext[index]==ASCII_SPACEortext[index]==ASCII_TAB",
    "index<-index+SIGNED_INDEX_STEP",
    "deftrim_bounds(text:sview)->(start:usize,end:usize):",
    "ensureresult.start<=result.end",
    "ensureresult.end<=text.len",
    "forallprefix_indexin0..<result.start:text[prefix_index]==ASCII_SPACEortext[prefix_index]==ASCII_TAB",
    "forallsuffix_indexinresult.end..<text.len:text[suffix_index]==ASCII_SPACEortext[suffix_index]==ASCII_TAB",
    "result.start==result.endor(",
    "ensureresult.start!=result.endorresult.start==text.len",
    "whilefirst<lastand(text[first]==ASCII_SPACEortext[first]==ASCII_TAB)",
    "decreaseslast-first",
    "invariantfirst<=last",
    "invariantlast<=text_length",
    "invariantfirst==0or(forallprefix_indexin0..<first:text[prefix_index]==ASCII_SPACEortext[prefix_index]==ASCII_TAB)",
    "assertfirst==lastor(text[first]!=ASCII_SPACEandtext[first]!=ASCII_TAB)",
    "whilelast>firstand(text[last-BYTE_INDEX_STEP]==ASCII_SPACEortext[last-BYTE_INDEX_STEP]==ASCII_TAB)",
    "invariantlast==text_lengthor(forallsuffix_indexinlast..<text_length:text[suffix_index]==ASCII_SPACEortext[suffix_index]==ASCII_TAB)",
    "assertlast==firstor(text[last-BYTE_INDEX_STEP]!=ASCII_SPACEandtext[last-BYTE_INDEX_STEP]!=ASCII_TAB)",
    "return(first,last)",
    "defstarts_with(text:sview,prefix:sview)->bool:",
    "ensureresultimpliesprefix.len<=text.len",
    "forallprefix_indexin0..<prefix.len:prefix_index>=text.lenortext[prefix_index]==prefix[prefix_index]",
    "(prefix.len<=text.lenand(forallprefix_indexin0..<prefix.len:",
    "text_length:usize=text.len",
    "prefix_length:usize=prefix.len",
    "returnfalseifprefix_length>text_length",
    "whileindex<prefix_length|index,text,prefix,prefix_length|",
    "decreasesprefix_length-index",
    "invariantindex<=prefix_length",
    "invariantforallmatched_indexin0..<index:text[matched_index]==prefix[matched_index]",
    "returnfalseiftext[index]!=prefix[index]",
    "returntrue",
    "defequal(a:sview,b:sview)->bool:",
    "ensureresultimpliesa.len==b.len",
    "forallindexin0..<a.len:index>=b.lenora[index]==b[index]",
    "(a.len==b.lenand(forallindexin0..<a.len:",
    "returna.len==b.lenandstarts_with(a,b)",
    "deftrim(text:sview)->sview:",
    "bounds:(start:usize,end:usize)=trim_bounds(text)",
    "returntext[bounds.start:bounds.end]",
)
if not all(fragment in source_compact for fragment in required_source):
    raise SystemExit("production EASM scanner lost a source contract or loop invariant")
expected_find = """
def find(text: sview, needle: sview) -> usize:
    ensure result <= text.len
    ensure (needle.len == 0 or text.len < needle.len) implies result == text.len
    ensure result < text.len implies (
        needle.len > 0 and
        needle.len <= text.len and
        result <= text.len - needle.len and
        text[result:result + needle.len] == needle
    )
    ensure (forall candidate in 0..<result:
        needle.len == 0 or
        needle.len > text.len - candidate or
        text[candidate:candidate + needle.len] != needle
    )
    text_length: usize = text.len
    needle_length: usize = needle.len
    assert text_length == text.len
    assert needle_length == needle.len
    if needle.len == 0:
        assert (forall candidate in 0..<text.len:
            needle.len == 0 or
            needle.len > text.len - candidate or
            text[candidate:candidate + needle.len] != needle
        )
        return text.len
    if text.len < needle.len:
        assert (forall candidate in 0..<text.len:
            needle.len == 0 or
            needle.len > text.len - candidate or
            text[candidate:candidate + needle.len] != needle
        )
        return text.len
    assert needle.len > 0 and needle.len <= text.len
    assert needle_length > 0 and needle_length <= text_length
    search_limit: usize = text_length - needle_length + BYTE_INDEX_STEP
    assert search_limit <= text_length
    index: mutable usize = 0
    while index < search_limit |index, search_limit, text, needle, needle_length, text_length|:
        decreases search_limit - index
        invariant index <= search_limit
        invariant index == 0 or (forall candidate in 0..<index:
            candidate <= text_length - needle_length and
            needle_length <= text_length - candidate and
            text[candidate:candidate + needle_length] != needle
        )
        assert index <= text_length - needle_length
        assert index <= text.len - needle.len
        if text[index:index + needle_length] == needle:
            assert needle.len > 0 and needle.len <= text.len
            assert needle_length > 0 and needle_length <= text_length
            assert index <= text.len - needle.len
            return index
        index <- index + BYTE_INDEX_STEP
    assert index == search_limit
    assert (forall candidate in 0..<text.len:
        needle.len == 0 or
        needle.len > text.len - candidate or
        text[candidate:candidate + needle.len] != needle
    )
    return text.len
"""
if compact(function_section(source_text, "find")) != compact(expected_find):
    raise SystemExit("production EASM substring search no longer implements the verified first-match scan")
expected_memory_delimiter = """
def contains_memory_address_delimiter(has_parenthesis: bool, has_square_bracket: bool) -> bool:
    ensure result == (has_parenthesis or has_square_bracket)
    return has_parenthesis or has_square_bracket
"""
if compact(function_section(source_text, "contains_memory_address_delimiter")) != compact(expected_memory_delimiter):
    raise SystemExit("production EASM memory-delimiter classifier no longer matches its proved boolean policy")
expected_trim = """
def trim(text: sview) -> sview:
    bounds: (start: usize, end: usize) = trim_bounds(text)
    return text[bounds.start:bounds.end]
"""
if compact(function_section(source_text, "trim")) != compact(expected_trim):
    raise SystemExit("production EASM trim no longer returns exactly the verified half-open span")
expected_easm_trim = """
def easm_trim(text: sview) -> sview:
    ensure result == EasmTextScan::trim(text)
    return EasmTextScan::trim(text)
"""
if compact(function_section(PROVENANCE.read_text(), "easm_trim")) != compact(expected_easm_trim):
    raise SystemExit("production EASM trim wrapper no longer delegates to the source-linked implementation")
expected_easm_starts = """
def easm_starts(text: sview, prefix: sview) -> bool:
    ensure result == EasmTextScan::starts_with(text, prefix)
    return EasmTextScan::starts_with(text, prefix)
"""
if compact(function_section(PROVENANCE.read_text(), "easm_starts")) != compact(expected_easm_starts):
    raise SystemExit("production EASM prefix helper no longer delegates to the source-linked scanner")
expected_easm_equal = """
def easm_equal(a: sview, b: sview) -> bool:
    ensure result == EasmTextScan::equal(a, b)
    return EasmTextScan::equal(a, b)
"""
if compact(function_section(PROVENANCE.read_text(), "easm_equal")) != compact(expected_easm_equal):
    raise SystemExit("production EASM equality helper no longer delegates to the source-linked scanner")
if 'include "../../src/backend/easm_text_scan.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer includes the production EASM scanner")
if "returnEasmTextScan::find(text,needle)" not in compact(function_section(PARSER.read_text(), "easm_find")):
    raise SystemExit("production EASM substring search wrapper no longer uses the verified scanner")
expected_memory_operand = """
def easm_memory_operand(operand: sview) -> bool:
    return EasmTextScan::contains_memory_address_delimiter(
        easm_find(operand, "(") < operand.len,
        easm_find(operand, "[") < operand.len
    )
"""
if compact(function_section(PROVENANCE.read_text(), "easm_memory_operand")) != compact(expected_memory_operand):
    raise SystemExit("production memory-operand classifier no longer delegates delimiter presence to the proved scan policy")
positive_compact = compact(POSITIVE.read_text())
positive_names = {
    "memory_operand_classification_matches_delimiter_presence",
    "parenthesized_memory_operand_delimiter_is_found",
    "bracketed_memory_operand_delimiter_is_found",
    "find_contract_holds",
    "find_returns_the_first_duplicate_match",
    "find_returns_text_length_when_absent",
    "find_returns_text_length_for_an_empty_needle",
    "find_accepts_a_match_at_the_last_legal_start",
    "starts_with_contract_holds",
    "starts_with_accepts_an_exact_prefix",
    "starts_with_accepts_an_exact_full_view",
    "starts_with_accepts_the_empty_prefix",
    "starts_with_rejects_a_longer_prefix",
    "starts_with_rejects_a_late_byte_mismatch",
    "equal_contract_holds",
    "equal_accepts_identical_instruction_text",
    "equal_accepts_two_empty_views",
    "equal_rejects_a_different_same_length_mnemonic",
    "equal_rejects_a_shared_prefix_with_different_tail",
    "equal_rejects_a_proper_prefix",
    "first_space_contract_holds",
    "trim_bounds_contract_holds",
    "trim_returns_the_exact_maximal_source_span",
    "trim_removes_only_outer_spaces_and_tabs",
    "trimming_all_whitespace_returns_the_empty_end_span",
    "trimming_a_clean_view_preserves_the_whole_span",
}
negative_names = {
    "false_claim_scanner_skips_the_first_separator",
    "false_claim_nonprefix_matches",
    "false_claim_longer_prefix_matches",
    "false_claim_late_prefix_mismatch_is_ignored",
    "false_claim_empty_prefix_does_not_match",
    "false_claim_different_mnemonics_are_equal",
    "false_claim_a_proper_prefix_is_equal",
    "false_claim_equal_length_text_ignores_the_last_byte",
    "false_claim_find_returns_a_later_duplicate_match",
    "false_claim_missing_needle_returns_zero",
    "false_claim_empty_needle_returns_zero",
    "false_claim_delimiter_free_operand_is_memory",
    "false_claim_trim_keeps_a_leading_space",
    "false_claim_trim_keeps_a_trailing_tab",
    "false_claim_trim_discards_internal_whitespace",
    "false_claim_trim_all_whitespace_returns_start",
}
if set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", POSITIVE.read_text())) != positive_names:
    raise SystemExit("positive EASM scanner proof inventory changed")
if set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", NEGATIVE.read_text())) != negative_names:
    raise SystemExit("negative EASM scanner proof inventory changed")
required_positive_claims = (
    "defmemory_operand_classification_matches_delimiter_presence(has_parenthesis:bool,has_square_bracket:bool)->bool:",
    "returnEasmTextScan::contains_memory_address_delimiter(has_parenthesis,has_square_bracket)==(has_parenthesisorhas_square_bracket)",
    'returnEasmTextScan::find("8(%rax)","(")==1',
    'returnEasmTextScan::find("[rax+8]","[")==0',
    "deffind_contract_holds(text:sview,needle:sview)->bool:",
    "position:usize=EasmTextScan::find(text,needle)",
    "needle_length==0orneedle_length>text_length-candidateortext[candidate:candidate+needle_length]!=needle",
    'returnEasmTextScan::find("ababa","ba")==1',
    'returnEasmTextScan::find("abc","z")==3',
    'returnEasmTextScan::find("abc","")==3',
    'returnEasmTextScan::find("ab","b")==1',
    "defstarts_with_contract_holds(text:sview,prefix:sview)->bool:",
    "matches:bool=EasmTextScan::starts_with(text,prefix)",
    "matchesimpliesprefix_length<=text_length",
    "matchesimplies(forallprefix_indexin0..<prefix_length:",
    "prefix_length<=text_lengthand(forallprefix_indexin0..<prefix_length:",
    'returnEasmTextScan::starts_with("movq %rax, %rbx","mov")',
    'returnEasmTextScan::starts_with("ret","ret")',
    'returnEasmTextScan::starts_with("ret","")',
    'returnnotEasmTextScan::starts_with("x","xyz")',
    'returnnotEasmTextScan::starts_with("movq","movx")',
    "defequal_contract_holds(a:sview,b:sview)->bool:",
    "matches:bool=EasmTextScan::equal(a,b)",
    "matchesimpliesa_length==b_length",
    "matchesimplies(forallindexin0..<a_length:",
    "a_length==b_lengthand(forallindexin0..<a_length:",
    'returnEasmTextScan::equal("movq %rax, %rbx","movq %rax, %rbx")',
    'returnEasmTextScan::equal("","")',
    'returnnotEasmTextScan::equal("movq","addq")',
    'returnnotEasmTextScan::equal("movq","movx")',
    'returnnotEasmTextScan::equal("mov","movq")',
    "deffirst_space_contract_holds(text:sview)->bool:",
    "ensureresult==true",
    "position:i64=EasmTextScan::first_space(text)",
    "position>=0",
    "text.len<0orposition==0",
    "text.len<0orposition<=text.len",
    "text.len<0orposition==text.lenor(",
    "forallprefix_indexin0..<position:text.len<0orprefix_index>=text.lenor(text[prefix_index]!=EasmTextScan::ASCII_SPACEandtext[prefix_index]!=EasmTextScan::ASCII_TAB)",
    "deftrim_bounds_contract_holds(text:sview)->bool:",
    "bounds:(start:usize,end:usize)=EasmTextScan::trim_bounds(text)",
    "bounds.start<=bounds.endandbounds.end<=text_length",
    "forallprefix_indexin0..<bounds.start:",
    "forallsuffix_indexinbounds.end..<text_length:",
    "bounds.start!=bounds.endorbounds.start==text_length",
    "deftrim_returns_the_exact_maximal_source_span(text:sview)->bool:",
    "trimmed==text[bounds.start:bounds.end]",
    "deftrim_removes_only_outer_spaces_and_tabs()->bool:",
    'bounds.start==2andbounds.end==12andtrimmed=="left right"',
    "deftrimming_all_whitespace_returns_the_empty_end_span()->bool:",
    'EasmTextScan::trim(text)==""',
    "deftrimming_a_clean_view_preserves_the_whole_span()->bool:",
    "bounds.start==0andbounds.end==text.lenandEasmTextScan::trim(text)==text",
)
if not all(fragment in positive_compact for fragment in required_positive_claims):
    raise SystemExit("positive proof no longer states the production scanner's complete postcondition")
if 'include "./easm_text_scan.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer includes the positive EASM scanner proof")
if "EasmTextScan::first_space(\"a b\")" not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer challenges first-separator behavior")
negative_compact = compact(NEGATIVE.read_text())
required_negative_claims = (
    'returnEasmTextScan::find("ababa","ba")==3',
    'returnEasmTextScan::find("abc","z")==0',
    'returnEasmTextScan::find("abc","")==0',
    "returnEasmTextScan::contains_memory_address_delimiter(false,false)",
    'returnEasmTextScan::starts_with("add","mov")',
    'returnEasmTextScan::starts_with("x","xyz")',
    'returnEasmTextScan::starts_with("movq","movx")',
    'EasmTextScan::starts_with("ret","")==false',
    'returnEasmTextScan::equal("movq","addq")',
    'returnEasmTextScan::equal("mov","movq")',
    'returnEasmTextScan::equal("movq","movx")',
    'trimmed:sview=EasmTextScan::trim(" x ")',
    "trimmed[0]==EasmTextScan::ASCII_SPACE",
    'trimmed:sview=EasmTextScan::trim("x\\t")',
    "trimmed[trimmed.len-1.usize()]==EasmTextScan::ASCII_TAB",
    'EasmTextScan::trim("left right")=="leftright"',
    'bounds:(start:usize,end:usize)=EasmTextScan::trim_bounds(" \\t ")',
    "returnbounds.start==0andbounds.end==0",
)
if not all(fragment in negative_compact for fragment in required_negative_claims):
    raise SystemExit("negative controls no longer cover scanner prefix, search, or trim boundaries")

if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive_claims": len(positive_names),
                      "false_claim_controls": len(negative_names)}))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("EASM scanner proof requires a strict proof build")

inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    SOURCE,
    ENV,
    PARSER,
    PROVENANCE,
    EASM_PARSE,
]
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs.extend((stage1_product, stage1_provenance))
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
assert positive == run(POSITIVE)[1], "EASM scanner proof report changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["semantic_errors"] == 0
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {finding["name"] for finding in negative["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert not negative_names & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof-product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "production EASM first-match search, exact prefix and byte equality, whitespace scan, and maximal ASCII trim span",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
