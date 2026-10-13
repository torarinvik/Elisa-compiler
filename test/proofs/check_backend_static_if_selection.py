"""Admit the source-linked static-if branch-selection policy proof."""
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
BRANCH_TAGS = ROOT / "src/parser/static_if_branch.elisa"
PARSER_FACADE = ROOT / "src/parser/parser.elisa"
PARSER_CORE = ROOT / "src/parser/parser_core.elisa"
PARSER_TOKENS = ROOT / "src/parser/parser_tokens.elisa"
PARSER_DECL = ROOT / "src/parser/parser_decl.elisa"
PARSER_DECL_IMPL = ROOT / "src/parser/parser_decl_impl.elisa"
PARSER_STMT = ROOT / "src/parser/parser_stmt.elisa"
PARSER_TYPES_ENTRY = ROOT / "src/parser/parser_types_entry.elisa"
BACKEND_FACADE = ROOT / "src/backend/codegen_struct_reg.elisa"
POLICY = ROOT / "src/backend/codegen_static_if_policy.elisa"
SELECTOR = ROOT / "src/backend/codegen_static_if.elisa"
POSITIVE = HERE / "backend_static_if_selection.elisa"
NEGATIVE = HERE / "backend_static_if_selection_rejected.elisa"

PROOF_PROCESS_TIMEOUT_SECONDS = 60
ELISA_INDENT_WIDTH = 4
POSITIVE_NAMES = {
    "every_branch_kind_has_its_exact_action",
    "a_chain_head_starts_fresh_even_after_a_selected_outer_arm",
    "an_unsatisfied_chain_continuation_evaluates_its_condition",
    "an_unsatisfied_fallback_is_selected_without_folding_a_condition",
    "a_satisfied_chain_skips_a_continuation",
    "a_satisfied_chain_skips_its_fallback",
    "condition_selection_matches_foldability_and_truth",
    "an_unfoldable_condition_is_not_selected",
    "a_zero_condition_is_not_selected",
}
NEGATIVE_NAMES = {
    "false_claim_chain_head_is_suppressed_by_a_prior_selection",
    "false_claim_unsatisfied_continuation_is_skipped",
    "false_claim_unsatisfied_fallback_is_skipped",
    "false_claim_satisfied_fallback_is_selected",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def source_code(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def compact(text: str) -> str:
    return "".join(source_code(text).split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def direct_children(lines: list[str], parent_index: int, parent_indent: int) -> list[str]:
    children: list[str] = []
    for line in lines[parent_index + 1:]:
        content = line.lstrip(" \t")
        if not content or content.startswith("#"):
            continue
        indent = len(line) - len(content)
        if indent <= parent_indent:
            break
        if indent == parent_indent + ELISA_INDENT_WIDTH:
            children.append(content)
    return children


def require_branch_kind_contract() -> None:
    branch_text = compact(BRANCH_TAGS.read_text())
    expected = (
        "moduleStaticIfBranch:public:constenumKindofu32:ChainHead"
        "ChainContinuationFallbackconstTOP_LEVEL_DEPTH:u32=0"
        "constNESTING_LEVEL_STEP:u32=1constCONDITION_FALSE_VALUE:i64=0"
    )
    if expected not in branch_text:
        raise SystemExit("shared static-if branch tags or named depth/false constants changed")
    parser_facade = compact(PARSER_FACADE.read_text())
    backend_facade = compact(BACKEND_FACADE.read_text())
    if 'include"./static_if_branch.elisa"' not in parser_facade:
        raise SystemExit("parser no longer includes the shared static-if branch tags")
    backend_order = [
        backend_facade.find('include"./codegen_static_if_policy.elisa"'),
        backend_facade.find('include"./codegen_static_if.elisa"'),
    ]
    if any(position < 0 for position in backend_order) or backend_order != sorted(backend_order):
        raise SystemExit("backend must include the policy before the selector; branch tags come through Parser")


def require_parser_emission() -> None:
    declaration = compact(function_section(PARSER_DECL.read_text(), "capture_static_if_condition"))
    expected = (
        "branch_kind:StaticIfBranch::Kind=matchis_chain_head:true:StaticIfBranch::Kind.ChainHead"
        "false:StaticIfBranch::Kind.ChainContinuation"
        "parser.static_if_kinds<-parser.static_if_kinds.push(branch_kind)"
    )
    if expected not in declaration:
        raise SystemExit("parser must pattern-match static-if and static-elif row tags")
    fallback = compact(function_section(PARSER_DECL.read_text(), "record_static_else"))
    if "StaticIfBranch::Kind.Fallback" not in fallback or "push(2)" in fallback:
        raise SystemExit("parser fallback rows must use the shared named branch kind")
    if "StaticIfBranch::TOP_LEVEL_DEPTH" not in compact(PARSER_CORE.read_text()):
        raise SystemExit("parser static-if nesting must start at the named top-level depth")
    for path in (PARSER_DECL_IMPL, PARSER_STMT):
        text = compact(path.read_text())
        if "static_if_depth<-parser.static_if_depth+StaticIfBranch::NESTING_LEVEL_STEP" not in text:
            raise SystemExit(f"{path.name} must use the named static-if nesting increment")
        if "static_if_depth<-parser.static_if_depth-StaticIfBranch::NESTING_LEVEL_STEP" not in text:
            raise SystemExit(f"{path.name} must use the named static-if nesting decrement")


def require_static_if_row_alignment() -> None:
    columns = ("static_if_conds", "static_if_lines", "static_if_kinds", "static_if_depths")
    append_values = {
        "capture_static_if_condition": ("condition_expr", "branch_line", "branch_kind", "parser.static_if_depth"),
        "record_static_else": ("(Ast::Expr.Absent)", "branch_line", "StaticIfBranch::Kind.Fallback", "parser.static_if_depth"),
    }
    for function_name, values in append_values.items():
        section = compact(function_section(PARSER_DECL.read_text(), function_name))
        fragments = [f"parser.{column}<-parser.{column}.push({value})" for column, value in zip(columns, values)]
        positions = [section.find(fragment) for fragment in fragments]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            raise SystemExit(f"{function_name} must append all four static-if row columns in lockstep")
        if any(section.count(fragment) != 1 for fragment in fragments):
            raise SystemExit(f"{function_name} must append each static-if row column exactly once")
    core = compact(PARSER_CORE.read_text())
    for column in columns:
        if core.count(f"{column}:[]") != 1:
            raise SystemExit(f"parser constructor must initialize the {column} row column exactly once")
    if "static_if_kinds:mutabledarray[StaticIfBranch::Kind]" not in core:
        raise SystemExit("parser must keep static-if tags in the closed branch-kind enum")
    token_types = compact(PARSER_TOKENS.read_text())
    if "static_if_kinds:darray[StaticIfBranch::Kind]" not in token_types:
        raise SystemExit("Ast::File must keep static-if tags in the closed branch-kind enum")
    entry = compact(function_section(PARSER_TYPES_ENTRY.read_text(), "parse_file_seeded"))
    positions = [entry.find(f"{column}:parser.{column}") for column in columns]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("Ast::File construction must transfer all static-if row columns in lockstep")
    if any(entry.count(f"{column}:parser.{column}") != 1 for column in columns):
        raise SystemExit("Ast::File construction must transfer each static-if row column exactly once")


def require_policy_source() -> None:
    policy_text = compact(POLICY.read_text())
    declarations = (
        "constenumActionofu8:SkipSelectFallbackEvaluateCondition",
        "defrow_action(kind:StaticIfBranch::Kind,previously_satisfied:bool)->Action:",
        "ensurekind==StaticIfBranch::Kind.ChainHeadimpliesresult==Action.EvaluateCondition",
        "ensurekind==StaticIfBranch::Kind.ChainContinuationandnotpreviously_satisfiedimpliesresult==Action.EvaluateCondition",
        "ensurekind==StaticIfBranch::Kind.Fallbackandnotpreviously_satisfiedimpliesresult==Action.SelectFallback",
        "ensurepreviously_satisfiedandkind!=StaticIfBranch::Kind.ChainHeadimpliesresult==Action.Skip",
        "starts_new_chain:bool=matchkind:StaticIfBranch::Kind.ChainHead:true_:false",
        "chain_satisfied:bool=falseifstarts_new_chainelsepreviously_satisfied",
        "returnAction.Skipifchain_satisfied",
        "returnmatchkind:",
        "StaticIfBranch::Kind.ChainHead:Action.EvaluateCondition",
        "StaticIfBranch::Kind.ChainContinuation:Action.EvaluateCondition",
        "StaticIfBranch::Kind.Fallback:Action.SelectFallback",
        "_:Action.Skip",
        "defcondition_selects_branch(condition_ok:bool,condition_value:i64)->bool:",
        "returncondition_okandcondition_value!=StaticIfBranch::CONDITION_FALSE_VALUE",
    )
    if any(fragment not in policy_text for fragment in declarations):
        raise SystemExit("shared static-if policy must reset heads, skip satisfied chains, and match every row kind")
    if "kind==0" in policy_text or "kind==1" in policy_text or "kind==2" in policy_text:
        raise SystemExit("static-if policy reintroduced numeric branch tags")


def require_selector_layout() -> None:
    section = function_section(SELECTOR.read_text(), "selected_static_if_lines")
    section_code = source_code(section)
    body = compact(section_code)
    ordered_fragments = (
        "forrowin0..<file.static_if_lines.count|taken,satisfied_by_depth,file,structs|:",
        "branch_kind:StaticIfBranch::Kind=file.static_if_kinds[row]",
        "row_depth:usize=file.static_if_depths[row].usize()ifrow<file.static_if_depths.countelseStaticIfBranch::TOP_LEVEL_DEPTH.usize()",
        "whilesatisfied_by_depth.count<=row_depth|satisfied_by_depth|:",
        "satisfied_by_depth.push(false)",
        "starts_new_chain:bool=matchbranch_kind:StaticIfBranch::Kind.ChainHead:true_:false",
        "satisfied_by_depth[row_depth]<-falseifstarts_new_chain",
        "action:StaticIfPolicy::Action=StaticIfPolicy::row_action(branch_kind,satisfied_by_depth[row_depth])",
        "matchaction:",
        "condition_ok:mutablebool=true",
        "condition_value:i64=fold_const_expr(file.static_if_conds[row],structs,condition_ok)",
        "continueifnotStaticIfPolicy::condition_selects_branch(condition_ok,condition_value)",
    )
    positions = [body.find(fragment) for fragment in ordered_fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("static-if selector no longer resets each chain at its own depth before applying policy")
    if body.count("taken.push(file.static_if_lines[row])") != 2:
        raise SystemExit("fallback and true-condition arms must each append exactly their selected branch")
    if body.count("satisfied_by_depth[row_depth]<-true") != 2:
        raise SystemExit("both selected fallback and selected condition arms must satisfy only their depth")
    lines = section_code.splitlines()
    loop_index = next((index for index, line in enumerate(lines)
                       if "for row in 0..<file.static_if_lines.count" in line), None)
    if loop_index is None:
        raise SystemExit("static-if source-order row loop is missing")
    loop_indent = len(lines[loop_index]) - len(lines[loop_index].lstrip(" \t"))
    expected_loop_children = [
        "branch_kind: StaticIfBranch::Kind = file.static_if_kinds[row]",
        "row_depth: usize = file.static_if_depths[row].usize() if row < file.static_if_depths.count else StaticIfBranch::TOP_LEVEL_DEPTH.usize()",
        "while satisfied_by_depth.count <= row_depth |satisfied_by_depth|:",
        "starts_new_chain: bool = match branch_kind:",
        "satisfied_by_depth[row_depth] <- false if starts_new_chain",
        "action: StaticIfPolicy::Action = StaticIfPolicy::row_action(branch_kind, satisfied_by_depth[row_depth])",
        "match action:",
    ]
    if direct_children(lines, loop_index, loop_indent) != expected_loop_children:
        raise SystemExit("depth growth, chain reset, policy call, and action match must be direct row-loop steps")
    action_index = next((index for index, line in enumerate(lines)
                         if line.strip() == "match action:"), None)
    if action_index is None:
        raise SystemExit("static-if action match is missing")
    action_indent = len(lines[action_index]) - len(lines[action_index].lstrip(" \t"))
    expected_arms = [
        "StaticIfPolicy::Action::Skip:",
        "StaticIfPolicy::Action::SelectFallback:",
        "StaticIfPolicy::Action::EvaluateCondition:",
    ]
    if direct_children(lines, action_index, action_indent) != expected_arms:
        raise SystemExit("static-if action match must handle skip, fallback, and condition evaluation explicitly")
    arm_children = {}
    for arm in expected_arms:
        arm_index = next(index for index, line in enumerate(lines) if line.strip() == arm)
        arm_indent = len(lines[arm_index]) - len(lines[arm_index].lstrip(" \t"))
        arm_children[arm] = direct_children(lines, arm_index, arm_indent)
    if arm_children[expected_arms[0]] != ["continue"]:
        raise SystemExit("a previously satisfied static-if chain must continue to the next source row")
    if arm_children[expected_arms[1]] != [
        "taken.push(file.static_if_lines[row])",
        "satisfied_by_depth[row_depth] <- true",
    ]:
        raise SystemExit("fallback selection must append its own line and satisfy only its depth without folding")
    if arm_children[expected_arms[2]] != [
        "condition_ok: mutable bool = true",
        "condition_value: i64 = fold_const_expr(file.static_if_conds[row], structs, condition_ok)",
        "continue if not StaticIfPolicy::condition_selects_branch(condition_ok, condition_value)",
        "taken.push(file.static_if_lines[row])",
        "satisfied_by_depth[row_depth] <- true",
    ]:
        raise SystemExit("condition branches must fold from a true initial status and update selection only on success")


def require_static_if_callers() -> None:
    declaration = compact(function_section(PARSER_DECL_IMPL.read_text(), "static_if_declaration"))
    declaration_steps = (
        "matched_head:bool=parser.peek()==TokenKind.Iforparser.peek()==TokenKind.Elif",
        "is_chain_head:bool=parser.peek()==TokenKind.If",
        "parser<-parser.advance_if(matched_head)",
        "parser<-parser.capture_static_if_condition(head.line,is_chain_head)canGlobal{Read,Write}ifmatched_head",
        "parser<-parser.record_static_else(head.line)ifnotmatched_head",
        "parser<-parser.accept_if(TokenKind.Else,notmatched_head)",
        "parser.static_if_depth<-parser.static_if_depth+StaticIfBranch::NESTING_LEVEL_STEP",
        "parser<-parser.parse_scoped_block(out,head)canGlobal{Read,Write}",
        "parser.static_if_depth<-parser.static_if_depth-StaticIfBranch::NESTING_LEVEL_STEP",
        "has_continuation<-parser.peek()==TokenKind.Staticand(parser.peek_at(1)==TokenKind.Eliforparser.peek_at(1)==TokenKind.Else)",
    )
    positions = [declaration.find(fragment) for fragment in declaration_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("declaration static-if caller must classify head/continuation/fallback and bracket nested depth")
    statement = compact(function_section(PARSER_STMT.read_text(), "statement_inner"))
    statement_steps = (
        "ifkind==TokenKind.Static:",
        "ifparser.peek_at(1)==TokenKind.Iforparser.peek_at(1)==TokenKind.Eliforparser.peek_at(1)==TokenKind.Else:",
        "static_chain_head:bool=parser.peek()==TokenKind.If",
        "static_matched_head:bool=parser.peek()==TokenKind.Iforparser.peek()==TokenKind.Elif",
        "parser<-parser.advance_if(static_matched_head)",
        "parser<-parser.capture_static_if_condition(static_head.line,static_chain_head)canGlobal{Read,Write}ifstatic_matched_head",
        "parser<-parser.record_static_else(static_head.line)ifnotstatic_matched_head",
        "parser<-parser.accept_if(TokenKind.Else,notstatic_matched_head)",
        "parser.static_if_depth<-parser.static_if_depth+StaticIfBranch::NESTING_LEVEL_STEP",
        "parser=parser.parse_block()",
        "parser.static_if_depth<-parser.static_if_depth-StaticIfBranch::NESTING_LEVEL_STEP",
    )
    positions = [statement.find(fragment) for fragment in statement_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("statement static-if caller must classify its branch and bracket the parsed nested depth")
    for source, name in ((declaration, "declaration"), (statement, "statement")):
        if source.count("parser.static_if_depth<-parser.static_if_depth+StaticIfBranch::NESTING_LEVEL_STEP") != 1:
            raise SystemExit(f"{name} static-if caller must increment its nesting depth once")
        if source.count("parser.static_if_depth<-parser.static_if_depth-StaticIfBranch::NESTING_LEVEL_STEP") != 1:
            raise SystemExit(f"{name} static-if caller must decrement its nesting depth once")


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_proof_shapes() -> None:
    if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
        raise SystemExit("static-if proof declaration inventory changed")
    if 'include "../../src/parser/static_if_branch.elisa"' not in POSITIVE.read_text():
        raise SystemExit("positive proof must include the parser's exact branch-tag source")
    if 'include "../../src/backend/codegen_static_if_policy.elisa"' not in POSITIVE.read_text():
        raise SystemExit("positive proof must include the backend's exact policy source")
    if POSITIVE.read_text().splitlines()[:3] != [
        "# Proofs include and verify the exact branch policy consumed by the backend.",
        'include "../../src/parser/static_if_branch.elisa"',
        'include "../../src/backend/codegen_static_if_policy.elisa"',
    ]:
        raise SystemExit("positive proof source-link includes must remain first and direct")


require_branch_kind_contract()
require_parser_emission()
require_static_if_row_alignment()
require_policy_source()
require_selector_layout()
require_static_if_callers()
require_proof_shapes()

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("static-if policy proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    BRANCH_TAGS,
    PARSER_FACADE,
    PARSER_CORE,
    PARSER_TOKENS,
    PARSER_DECL,
    PARSER_DECL_IMPL,
    PARSER_STMT,
    PARSER_TYPES_ENTRY,
    BACKEND_FACADE,
    POLICY,
    SELECTOR,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_PROCESS_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES
assert not positive["findings"]

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(NEGATIVE_NAMES)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "source-linked static-if kind/action policy, fold-failure behavior, and depth-local chain reset",
    "positive_declarations": sorted(POSITIVE_NAMES),
    "negative_controls_refused": sorted(NEGATIVE_NAMES),
    "replayed_certificates": positive["replay"]["replayed"],
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
