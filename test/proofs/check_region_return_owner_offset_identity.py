"""Keep tied-return parameter metadata owned by the exact function declaration."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BARE_RETURN = (ROOT / "src/semantic/check_region_param_bare_return.elisa").read_text()
TIED_RETURN = (ROOT / "src/semantic/check_region_tied_return_walk.elisa").read_text()
LOCAL_VIEW_RETURN = (ROOT / "src/semantic/check_local_view_return_escape_lambdas.elisa").read_text()
FIXTURE = (ROOT / "test/repro/region_return_owner_offset.elisa").read_text()
LOCAL_VIEW_FIXTURE = (ROOT / "test/repro/local_view_return_region_owner_offset.elisa").read_text()
SMOKE = (ROOT / "test/parity/region_scope_smoke.sh").read_text()


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


bare_return = compact(BARE_RETURN)
tied_return = compact(TIED_RETURN)
local_view_return = compact(LOCAL_VIEW_RETURN)

if "rpbr_tied_region(annotations,parameter.name,line.line,line.offset)" not in bare_return:
    raise SystemExit("bare-return region lookup no longer receives the function's source offset")
if "annotation.owner_offset!=function_offset" not in bare_return or \
        'annotation.name=="__region_return"' not in bare_return or \
        'annotation.name=="__region_param"' not in bare_return or \
        "annotation.owner_offset==function_offset" not in bare_return:
    raise SystemExit("bare-return checks must match parameter and return ties to one function owner")
if not all(fragment in tied_return for fragment in (
    'annotation.name=="__region_return"andannotation.line==line.lineandannotation.owner_offset==line.offset',
    'annotation.name==parameter.nameandannotation.line==line.lineandannotation.owner_offset==line.offset',
)):
    raise SystemExit("tied-return checks must match return/parameter annotations to the function offset")

if "lvre_function(line.line,line.offset," not in local_view_return or \
        "function_line:u32,function_offset:u32" not in local_view_return or \
        "lvre_returns_caller_region_container(value,escape.name,names,name_lines,name_values,writes,write_lines,annotations,enum_annotations,function_line,function_offset)" not in local_view_return or \
        'annotation.name=="__region_return"andannotation.line==function_lineandannotation.owner_offset==function_offset' not in local_view_return or \
        'parameter_region.name=="__region_param"andparameter_region.line==function_lineandparameter_region.owner_offset==function_offset' not in local_view_return:
    raise SystemExit("local-view return ties must match the exact function declaration offset")
if "annotation.owner_offset>function_offsetandannotation.owner_offset<=use_offset" not in local_view_return or \
        "annotation.end_offset==0oruse_offset<annotation.end_offset" not in local_view_return:
    raise SystemExit("local-view return local annotations must be selected within the function's source interval")

if FIXTURE.count("#line 0 region-return-owner.elisa") != 2:
    raise SystemExit("regression fixture must put both functions on the same logical line")
for fragment in (
    "def tied[@r](value: i64& @r) -> void:",
    "def ordinary(value: i64&) -> i64&:",
    "return value",
):
    if fragment not in FIXTURE:
        raise SystemExit(f"region-return regression fixture lost a required source shape: {fragment}")
if 'python3 "$REPO_ROOT/test/proofs/check_region_return_owner_offset_identity.py"' not in SMOKE or \
        'clean "$(cat "$REPO_ROOT/test/repro/region_return_owner_offset.elisa")"' not in SMOKE:
    raise SystemExit("region-scope smoke no longer runs the owner-offset proof and regression")
if LOCAL_VIEW_FIXTURE.count("#line 0 local-view-return-owner.elisa") != 2 or \
        "def tied[@r]() -> mutable darray[i64] @r:" not in LOCAL_VIEW_FIXTURE or \
        "def ordinary() -> mutable darray[i64]:" not in LOCAL_VIEW_FIXTURE or \
        "out: mutable darray[i64] = []" not in LOCAL_VIEW_FIXTURE or \
        'local_view_return_region_owner_offset.elisa' not in SMOKE:
    raise SystemExit("local-view regression must pair same-line tied and ordinary container returns in region-scope smoke")

print("region-return owner offset source checks passed")
