"""Bind set-element spelling proofs to semantic diagnostics and type extraction."""
from __future__ import annotations

import argparse
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
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/set_membership_element_policy.elisa"
CONSUMER = ROOT / "src/semantic/check_set_membership_element.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
SEMANTIC_PASSES = ROOT / "src/semantic/semantic_parallel_passes.elisa"
POSITIVE = HERE / "set_membership_element_policy.elisa"
NEGATIVE = HERE / "set_membership_element_policy_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}(?:\[[^\]\n]*\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\]\n]*\])?\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


policy_text = POLICY.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
semantic_passes_text = SEMANTIC_PASSES.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_classifier = '''
def is_unsupported_spelling(element_spelling: sview) -> bool:
    ensure result == (
        element_spelling == "sview" or element_spelling == "dstr" or
        element_spelling == "f32" or element_spelling == "f64"
    )
    return match element_spelling:
        "sview" | "dstr" | "f32" | "f64": true
        _: false
'''
expected_display = '''
def diagnostic_spelling(declared_spelling: sview) -> sview:
    ensure result == ("darray[u8]" if declared_spelling == "dstr" else declared_spelling)
    return "darray[u8]" if declared_spelling == "dstr" else declared_spelling
'''
if "moduleSemanticSetMembershipElementPolicy:" not in compact(policy_text):
    raise SystemExit("set membership element policy module is missing")
if compact(function_section(policy_text, "is_unsupported_spelling")) != compact(expected_classifier):
    raise SystemExit("unsupported set element classifier changed without updating its proof")
if compact(function_section(policy_text, "diagnostic_spelling")) != compact(expected_display):
    raise SystemExit("diagnostic spelling conversion changed without updating its proof")
if consumer_text.count('include "./set_membership_element_policy.elisa"') != 1:
    raise SystemExit("set membership checker must include the proved policy exactly once")
if semantic_text.count('include "./check_set_membership_element.elisa"') != 1:
    raise SystemExit("semantic root must include the set membership checker exactly once")
pass_dispatch = compact(function_section(semantic_passes_text, "par_pass_call"))
if "ifpass_id==94:table<-check_set_membership_element(loop_view.top_decls,table)" not in pass_dispatch:
    raise SystemExit("semantic pass dispatcher no longer invokes the proved set-element checker")

if compact(function_section(consumer_text, "set_element_spelling_unsupported")) != compact('''
def set_element_spelling_unsupported(element_spelling: sview) -> bool:
    can Abort.Panic:
        return SemanticSetMembershipElementPolicy::is_unsupported_spelling(element_spelling)
'''):
    raise SystemExit("set type extraction no longer delegates its spelling decision to the proved policy")
if compact(function_section(consumer_text, "set_element_reported_spelling")) != compact('''
def set_element_reported_spelling(declared_spelling: sview) -> sview:
    can Abort.Panic:
        return SemanticSetMembershipElementPolicy::diagnostic_spelling(declared_spelling)
'''):
    raise SystemExit("set diagnostic no longer delegates type spelling to the proved policy")
extractor = compact(function_section(consumer_text, "set_unsupported_element_of"))
extractor_fragments = (
    'Expr.Index(head,argument,index_line)',
    'returnelementifident_name_of(head)=="set"andset_element_spelling_unsupported(element)elsesview("",0,0)',
    'Expr.IndexN(head,arguments,index_n_line)',
    'returnelement_nifident_name_of(head)=="set"andset_element_spelling_unsupported(element_n)elsesview("",0,0)',
    'Expr.Unary(operator,operand,unary_line):returnset_unsupported_element_of(operand)',
    'Expr.Paren(inner,paren_line):returnset_unsupported_element_of(inner)',
)
if any(fragment not in extractor for fragment in extractor_fragments):
    raise SystemExit("proved spelling policy is no longer applied to both set type AST shapes and wrappers")
report = compact(function_section(consumer_text, "set_element_report"))
if any(fragment not in report for fragment in (
    'returnifelement_spelling==""',
    'actual:set_element_reported_spelling(element_spelling)',
    'kind:DiagnosticKind.SetElementUnsupported',
)):
    raise SystemExit("set-element diagnostic must use the proved displayed spelling and suppress empty cases")

expression_walk = compact(function_section(consumer_text, "set_element_check_expression"))
expression_fragments = (
    'Expr.Binary(left,operator,right,line)',
    'set_element_report(parallel_lookup_first(names,elements,ident_name_of(right)),Ast::pos_at_line(line.line),table)ifoperator==TokenKind.In',
    'Expr.Field(method_object,method_name,method_line)',
    'set_element_report(parallel_lookup_first(names,elements,ident_name_of(method_object)),Ast::pos_at_line(call_line.line),table)',
    'forargumentinarguments|table|->table:table<-set_element_check_expression(argument,names,elements,table)',
    'Expr.Unary(operator,operand,unary_line):table<-set_element_check_expression(operand,names,elements,table)',
    'Expr.Paren(inner,paren_line):table<-set_element_check_expression(inner,names,elements,table)',
)
if any(fragment not in expression_walk for fragment in expression_fragments):
    raise SystemExit("set-element proof is disconnected from membership or method-use reporting")

statement_walk = compact(function_section(consumer_text, "set_element_check_statements"))
statement_fragments = (
    'Stmt.VarDecl(name,type_expression,value,line)',
    'declared_element:sview=set_unsupported_element_of(type_expression)',
    'ifdeclared_element!="":names.push(name)elements.push(declared_element)table<-set_element_report(declared_element,Ast::expr_pos(value),table)',
    'table<-set_element_check_expression(value,names,elements,table)',
    'Stmt.Expr(expression,line):table<-set_element_check_expression(expression,names,elements,table)',
    'Stmt.Assign(target,operator,value,line):table<-set_element_check_expression(value,names,elements,table)',
    'Stmt.Contract(kind,expression,line):table<-set_element_check_expression(expression,names,elements,table)',
    'Stmt.If(condition,then_body,else_body,line)',
    'Stmt.While(condition,body,line)',
    'Stmt.For(bind,variables,iterable,body,line)',
    'Stmt.Block(block_kind,clause,binding,body,line)',
    'Stmt.Match(scrutinee,arms,line)',
)
if any(fragment not in statement_walk for fragment in statement_fragments):
    raise SystemExit("set-element declaration/use proof no longer matches the statement traversal")

declaration_walk = compact(function_section(consumer_text, "check_set_membership_element_decls"))
declaration_fragments = (
    'Decl.Func(name,params,return_type,body,effects,decorators,line)',
    'param_element:sview=set_unsupported_element_of(param.type_expression)',
    'ifparam_element!="":names.push(param.name)elements.push(param_element)',
    'table<-set_element_check_statements(body,names,elements,table)',
    'Decl.Module(module_name,body,line):table<-check_set_membership_element_decls(body,table)',
    'Decl.Scoped(body,line):table<-check_set_membership_element_decls(body,table)',
)
if any(fragment not in declaration_walk for fragment in declaration_fragments):
    raise SystemExit("set-element proof no longer covers parameter tracking and nested declarations")
checker_entry = compact(function_section(consumer_text, "check_set_membership_element"))
if "table<-check_set_membership_element_decls(declarations,table)" not in checker_entry:
    raise SystemExit("semantic set-element entry point no longer invokes its proved traversal")

if 'include "../../src/semantic/set_membership_element_policy.elisa"' not in positive_text or \
        'include "./set_membership_element_policy.elisa"' not in negative_text:
    raise SystemExit("set-element proof fixtures must import the production policy")
positive_names = {
    "unsupported_element_classifier_is_exact",
    "diagnostic_spelling_is_exact_for_every_input",
    "measured_rejected_and_accepted_element_spellings_are_distinguished",
    "dstr_uses_its_lowered_type_in_the_diagnostic",
}
negative_names = {
    "false_claim_cstr_is_an_unsupported_set_element",
    "false_claim_i64_is_an_unsupported_set_element",
    "false_claim_dstr_keeps_its_declared_diagnostic_spelling",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("set-element proof inventory changed")

positive_claims = {
    "unsupported_element_classifier_is_exact": 'SemanticSetMembershipElementPolicy::is_unsupported_spelling(spelling)==(spelling=="sview"orspelling=="dstr"orspelling=="f32"orspelling=="f64")',
    "diagnostic_spelling_is_exact_for_every_input": 'SemanticSetMembershipElementPolicy::diagnostic_spelling(spelling)==("darray[u8]"ifspelling=="dstr"elsespelling)',
    "measured_rejected_and_accepted_element_spellings_are_distinguished": 'SemanticSetMembershipElementPolicy::is_unsupported_spelling("sview")andSemanticSetMembershipElementPolicy::is_unsupported_spelling("dstr")andSemanticSetMembershipElementPolicy::is_unsupported_spelling("f32")andSemanticSetMembershipElementPolicy::is_unsupported_spelling("f64")',
    "dstr_uses_its_lowered_type_in_the_diagnostic": 'SemanticSetMembershipElementPolicy::diagnostic_spelling("dstr")=="darray[u8]"andSemanticSetMembershipElementPolicy::diagnostic_spelling("sview")=="sview"andSemanticSetMembershipElementPolicy::diagnostic_spelling("f64")=="f64"',
}
for name, claim in positive_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive proof {name} no longer establishes its source-bound claim")
expected_negative_claims = {
    "false_claim_cstr_is_an_unsupported_set_element": 'SemanticSetMembershipElementPolicy::is_unsupported_spelling("cstr")',
    "false_claim_i64_is_an_unsupported_set_element": 'SemanticSetMembershipElementPolicy::is_unsupported_spelling("i64")',
    "false_claim_dstr_keeps_its_declared_diagnostic_spelling": 'SemanticSetMembershipElementPolicy::diagnostic_spelling("dstr")=="dstr"',
}
for name, claim in expected_negative_claims.items():
    section = compact(function_section(negative_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"false-claim control {name} no longer asserts the rejected claim")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("set-element spelling proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POLICY, CONSUMER,
    SEMANTIC, SEMANTIC_PASSES, POSITIVE, NEGATIVE, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "set-element policy proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "set-element proof inputs changed during admission"
