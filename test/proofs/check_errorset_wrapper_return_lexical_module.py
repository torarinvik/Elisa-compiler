from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EWR = (ROOT / "src/semantic/check_errorset_wrapper_return.elisa").read_text()
FIXTURE = (ROOT / "test/repro/errorset_wrapper_return_static_if_lexical_module.elisa").read_text()
SMOKE = (ROOT / "test/parity/errorset_wrapper_return_static_if_lexical_module_smoke.sh").read_text()

selector_start = EWR.index("def ewr_static_if_row_selection(")
selector_end = EWR.find("\n        def ", selector_start + 1)
selector = EWR[selector_start:selector_end]
if not all(fragment in selector for fragment in (
        "row >= file.static_if_modules.count",
        "condition_module: sview = file.static_if_modules[row]",
        "ewr_static_if_condition_value(file.static_if_conds[row], condition_module, file, table")):
    raise SystemExit("EWR must fold each static-if condition in the module recorded for that row")

if not all(fragment in FIXTURE for fragment in (
        "const PICK_A: bool = true",
        "static if PICK_A:",
        "module Client:",
        "const PICK_A: bool = false",
        "using ProviderA as Selected",
        "return Selected::wrap(Selected::origin())")):
    raise SystemExit("EWR lexical-module fixture must place a shadowed import beneath the outer condition")

if not all(fragment in SMOKE for fragment in (
        "errorset_wrapper_return_static_if_lexical_module.elisa",
        "return type expects",
        "cannot propagate.*FaultA")):
    raise SystemExit("EWR lexical-module smoke must require matching Stage0 and Stage1 family selection")

print("EWR static-if lexical-module source binding passed")
