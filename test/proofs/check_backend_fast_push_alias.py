"""Ensure counted DArray pre-reserve cannot relocate a backing with observable aliases."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "src/backend"


def function(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}(?:\[[^\n]*?\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected one {name} declaration")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\n]*?\])?\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def struct(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)struct {re.escape(name)}:", source))
    if len(matches) != 1:
        raise SystemExit(f"expected one {name} declaration")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}struct [A-Za-z_][A-Za-z0-9_]*:", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


scope = (BACKEND / "codegen_emit_state.elisa").read_text()
cleanup = (BACKEND / "codegen_cleanup.elisa").read_text()
locals_source = (BACKEND / "codegen_locals.elisa").read_text()
prereserve_source = (BACKEND / "codegen_loop_prereserve.elisa").read_text()
statements = (BACKEND / "codegen_condition.elisa").read_text()
loops_source = (BACKEND / "codegen_stmt_loops.elisa").read_text()
fixture = (ROOT / "test/proofs/backend_fast_push_alias.elisa").read_text()

scope_decl = compact(struct(scope, "Scope"))
deferred_decl = compact(struct(scope, "DeferredAction"))
if "local_darray_backing_unaliased:mutabledarray[bool]=[]" not in scope_decl:
    raise SystemExit("Scope must keep exact-local DArray backing provenance")
if "local_darray_backing_unaliased" in deferred_decl:
    raise SystemExit("deferred actions must not retain stale outer-backing uniqueness")
declare = compact(function(locals_source, "declare_local"))
if "local_darray_backing_unaliased<-local_scope.local_darray_backing_unaliased.push(false)" not in declare:
    raise SystemExit("new locals must start without a backing-uniqueness proof")
restore = compact(function(locals_source, "scope_restore"))
if "local_scope.local_darray_backing_unaliased.pop()" not in restore:
    raise SystemExit("scope restore must discard backing-uniqueness facts with their locals")
if "captured.local_darray_backing_unaliased.push(false)" not in compact(cleanup):
    raise SystemExit("deferred scopes must start captured outer locals with false provenance")

update = compact(function(prereserve_source, "update_prereserve_unaliased_facts"))
for required in (
    "status!=EmitStatus.Open",
    "local_scope.names.count>local_count_before",
    "notprereserve_unaliased_fact_survives(statement,local_name,local_scope)",
    "statementisStmt.VarDecl(name,_,Expr.Array(_, _),_)",
    "local_scope.names[local_scope.names.count-1.usize()]==name",
    "local_scope.types[local_scope.types.count-1.usize()].kind==TypeKind.DArray",
    "mark_last_local_darray_backing_unaliased(local_scope)",
):
    if compact(required) not in update:
        raise SystemExit(f"backing provenance update lost a required guard: {required}")

survives = compact(function(prereserve_source, "prereserve_unaliased_fact_survives"))
for required in (
    "argument_names.count!=1",
    "argument_names[0]!=\"\"",
    "not(arguments[0]isExpr.IntLit(_,_))",
    "lookup_type(local_scope,receiver).kind==TypeKind.DArray",
    "receiver==nameandmethod==\"reserve\"",
):
    if required not in survives:
        raise SystemExit(f"only a positional literal reserve on the tracked DArray can preserve freshness: {required}")
if compact("return value is Expr.IntLit(_, _) or value is Expr.FloatLit(_, _) or value is Expr.BoolLit(_, _) or value is Expr.CharLit(_, _)") not in survives:
    raise SystemExit("only side-effect-free scalar literal declarations may preserve the fact")
if "returnfalseifdeclared_name==name" not in survives:
    raise SystemExit("a same-name declaration must invalidate the tracked binding before shadowing")

emit_loop = compact(function(prereserve_source, "emit_loop_prereserve"))
if "notlocal_darray_backing_is_unaliased(local_scope,receiver)" not in emit_loop:
    raise SystemExit("the pre-reserve path must require an unaliased backing")
prepare = compact(function(prereserve_source, "prepare_prereserve_unaliased_facts"))
if "statementisStmt.For(bind,_,_,_,_)" not in prepare or "returnifbind==\"\"" not in prepare:
    raise SystemExit("a direct loop must retain its fact only through its own reserve proof")
if "notprereserve_unaliased_fact_survives(statement,local_name,local_scope)" not in prepare:
    raise SystemExit("other statements must clear provenance before nested lowering")

emit_statements = compact(function(statements, "emit_statements_value"))
if "prepare_prereserve_unaliased_facts(statement,local_scope)" not in emit_statements:
    raise SystemExit("statement lowering must prepare the direct-loop fact before emitting nested control flow")
if "update_prereserve_unaliased_facts(statement,EmitStatus.Declined,local_scope.names.count,local_scope)" not in emit_statements:
    raise SystemExit("skipped statements must invalidate backing provenance")
if "update_prereserve_unaliased_facts(statement,status,statement_local_count,local_scope)" not in emit_statements:
    raise SystemExit("emitted statements must update backing provenance after lowering")
prepare_position = emit_statements.find("prepare_prereserve_unaliased_facts(statement,local_scope)")
helper_position = emit_statements.find("memory_emit_helper(statement")
if min(prepare_position, helper_position) < 0 or prepare_position > helper_position:
    raise SystemExit("provenance must be prepared before a statement can emit nested control flow")
statement_count_capture = emit_statements.find("statement_local_count:usize=local_scope.names.count")
statement_emission = emit_statements.find("status<-emit_statement(statement", statement_count_capture)
fact_update = emit_statements.find("update_prereserve_unaliased_facts(statement,status,statement_local_count,local_scope)", statement_emission)
if min(statement_count_capture, prepare_position, statement_emission, fact_update) < 0 or not (statement_count_capture < prepare_position < statement_emission < fact_update):
    raise SystemExit("backing facts must update after each emitted statement using its pre-emission local count")

calls_source = (BACKEND / "codegen_stmt_expr_calls.elisa").read_text()
statement_calls = compact(function(calls_source, "emit_statement_expr_calls"))
for required in (
    "push_type:ValueType=darray_type_behind_expr(push_object,local_scope,structs)",
    "ifpush_type.kind==TypeKind.DArrayandpush_method==\"reserve\"andpush_arguments.count==1:",
    "emit_darray_reserve(reserve_slot,push_type,reserve_n,structs,reserve_runtime,m,ctx,builder)",
):
    if required not in statement_calls:
        raise SystemExit(f"preserved reserve must stay on the builtin DArray lowering path: {required}")

type_place_source = (BACKEND / "codegen_expression_type_place.elisa").read_text()
type_place = compact(function(type_place_source, "expression_type_of_place"))
if "unmodeled_type()returnifobject_type.kind!=TypeKind.Struct" not in type_place:
    raise SystemExit("DArray method-shaped fields must not become an arbitrary callable that shadows builtin reserve")
callable_check = statement_calls.find("statement_callee_callable")
darray_dispatch = statement_calls.find("push_type:ValueType=darray_type_behind_expr(push_object,local_scope,structs)")
darray_reserve = statement_calls.find("ifpush_type.kind==TypeKind.DArrayandpush_method==\"reserve\"andpush_arguments.count==1", darray_dispatch)
builtin_reserve = statement_calls.find("emit_darray_reserve(reserve_slot,push_type,reserve_n,structs,reserve_runtime,m,ctx,builder)", darray_reserve)
if min(callable_check, darray_dispatch, darray_reserve, builtin_reserve) < 0 or not (callable_check < darray_dispatch < darray_reserve < builtin_reserve):
    raise SystemExit("the DArray reserve builtin dispatch must follow the non-callable field check")

loop_emitter = compact(function(loops_source, "emit_statement_loops"))
loop_reserve = loop_emitter.find("emit_loop_prereserve(for_variables,for_iterable,for_body")
loop_clear = loop_emitter.find("clear_local_darray_backing_unaliased(local_scope)", loop_reserve)
loop_body = loop_emitter.find("emit_statement_for_iterable_shapes(for_bind,for_variables,for_iterable,for_body", loop_clear)
if min(loop_reserve, loop_clear, loop_body) < 0 or not (loop_reserve < loop_clear < loop_body):
    raise SystemExit("nested loop lowering must not inherit the outer loop's pre-reserve proof")

fixture_steps = (
    "xs: mutable darray[i64] = [10, 11, 12, 13]",
    "alias: mutable darray[i64] = xs",
    "alias.push(99)",
    "alias.count <- 4",
    "xs <- for i in 0..<300 |xs| -> xs:",
    "xs.push(100 + i)",
    "return 1 if alias[4] != 100",
)
fixture_cursor = 0
for expected in fixture_steps:
    fixture_position = fixture.find(expected, fixture_cursor)
    if fixture_position < 0:
        raise SystemExit(f"copied-header regression witness lost or reordered step: {expected}")
    fixture_cursor = fixture_position + len(expected)

# Bind the fixture's capacity assumption to the literal emitter. Empty literals
# are null headers; every non-empty literal reserves the fixed 256-element seed.
aggregates = (BACKEND / "codegen_expr_aggregates.elisa").read_text()
array_literal = compact(function(aggregates, "emit_expression_aggregate_literals"))
if "ifarray_elements.count==0:returnLLVMConstNull(darray_llvm_type(structs,ctx))" not in array_literal:
    raise SystemExit("empty DArray literals must remain zero-capacity in the alias witness model")
if "literal_initial_capacity:LLVMValueRef=LLVMConstInt(LLVMInt64TypeInContext(ctx),256,0)" not in array_literal:
    raise SystemExit("non-empty DArray literals must retain their observable initial capacity of 256")
if "emit_darray_reserve(temporary,expected,literal_initial_capacity" not in array_literal:
    raise SystemExit("non-empty DArray literals must reserve their 256-element initial capacity")

benchmark = (ROOT / "test/bench/codegen_perf/darray_count_sum.elisa").read_text()
benchmark_tokens = (
    "xs: mutable darray[i64] = []",
    "xs.reserve(4000000)",
    "s: mutable u64 = 12345",
    "xs <- for i in 0..<4000000 |xs, s| -> xs:",
)
benchmark_cursor = 0
for token in benchmark_tokens:
    benchmark_position = benchmark.find(token, benchmark_cursor)
    if benchmark_position < 0:
        raise SystemExit(f"runtime fill benchmark no longer keeps the unique-header setup sequence: {token}")
    benchmark_cursor = benchmark_position + len(token)

# Abstract shallow-copy control: with N=4, C=256, and K=304, ordinary pushes
# first write into shared spare slots, while eager reserve detaches before the
# first write. The source checks bind C to the literal emitter; this model does
# not execute Elisa or prove arena allocation behavior.
n, capacity, required = 4, 256, 304
assert n < capacity < required
ordinary_alias = [10, 11, 12, 13, 99] + [0] * (capacity - 5)
ordinary_receiver = ordinary_alias
eager_alias = [10, 11, 12, 13, 99] + [0] * (capacity - 5)
eager_receiver = eager_alias.copy() + [0] * (required - capacity)  # eager reserve detaches before the first push
for index in range(n, required):
    if index >= len(ordinary_receiver):
        ordinary_receiver = ordinary_receiver.copy() + [0] * len(ordinary_receiver)
    ordinary_receiver[index] = 100 + index - n
    eager_receiver[index] = 100 + index - n
assert ordinary_alias[4] == 100 and eager_alias[4] == 99

print("counted-fill alias checker: provenance source shape and abstract shallow-copy control verified")
