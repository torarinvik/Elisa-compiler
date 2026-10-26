"""Guard early exact-row ErrorUnion status remapping for direct call capture."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CALL = (ROOT / "src/backend/codegen_call_direct.elisa").read_text()
FIXTURE = (ROOT / "test/fixtures/effects/error_union_subset_capture_cleanup.elisa").read_text()
SMOKE = (ROOT / "test/parity/error_union_subset_capture_smoke.sh").read_text()


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


call = compact(CALL)
start = call.index("defemit_direct_call_indexed_result[")
end = call.index("defemit_direct_call_indexed[", start)
body = call[start:end]
preflight = body.index("error_status_remap_supported(direct_error_family,direct_error_expected_family,structs)")
argument_emission = body.index("argument_values:mutabledarray[LLVMValueRef]=[]")
if preflight > argument_emission:
    raise SystemExit("family compatibility must be checked before argument expressions are emitted")
if "returnnullifnoterror_status_remap_supported(direct_error_family,direct_error_expected_family,structs)" not in body[:argument_emission]:
    raise SystemExit("unsupported status remaps must fail closed before any argument emission")
if "direct_error_family<-resolved_error_family(line_error_set_name(" not in body[:argument_emission]:
    raise SystemExit("actual family must come from the exact selected FnTable row before marshalling")
if "error_union_expectedisunion_expected" not in body[:argument_emission] or \
        "direct_error_expected_family<-resolved_error_family(error_union_family_of(union_expected,structs),structs)" not in body[:argument_emission]:
    raise SystemExit("expected family must be resolved from the requested ErrorUnion before marshalling")
status_call = body.index("emit_error_status_call(target,argument_values,direct_error_family")
call_attributes = body.index('add_call_type_attribute(call_result,direct_call_hidden+c_plan_position_of(fns,c_plan,direct_param_index).u32()+1,"byval"')
remap = body.index("remap_error_status(call_result,direct_error_family,direct_error_expected_family,structs,ctx,builder)")
union_build = body.index('LLVMBuildInsertValue(builder,union_value,union_status,0,"error.union.status")')
if not status_call < call_attributes < remap < union_build:
    raise SystemExit("call must retain the selected-row call handle through attrs, then remap before descriptor construction")
if "error_union_family_of(union_expected,structs)!=direct_error_family" in body:
    raise SystemExit("late family-equality decline can re-evaluate arguments through fallback")

fixture = compact(FIXTURE)
for required in (
    "errorFault:Available(enabled:bool,count:i64)Busy(code:i64)",
    "defevaluate_fail(fail:bool)->bool:",
    "canGlobal{Read,Write}:",
    "argument_count<-argument_count+1",
    "defproduce(fail:bool)->i64error[Fault{Busy}]",
    "raiseFault.Busy(9)iffail",
    "deferblock:",
    "source:i64error[Fault]=produce(evaluate_fail(fail))",
    "cleanup_count<-cleanup_count+1",
    "Fault.Busy(code):code",
    "returnsuccess+failed+cleanup_count+argument_count",
):
    if required not in fixture:
        raise SystemExit(f"subset capture fixture is missing {required!r}")
if "foroptimizationin02" not in compact(SMOKE) or \
        "expected35" not in compact(SMOKE) or \
        "elisa_run_timeout10\"$executable\"" not in compact(SMOKE):
    raise SystemExit("focused smoke must run bounded native O0/O2 checks expecting the remapped tag/payload, cleanup, and one argument evaluation")
print("backend ErrorUnion subset-capture source proof OK")
