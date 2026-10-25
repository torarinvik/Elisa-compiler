from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/backend/codegen_static_if.elisa").read_text()
FIXTURE = (ROOT / "test/repro/static_if_condition_lexical_module.elisa").read_text()
BACKEND_FIXTURE = (ROOT / "test/repro/static_if_backend_lexical_module.elisa").read_text()
SMOKE = (ROOT / "test/parity/static_if_condition_lexical_module_smoke.sh").read_text()

match = re.search(
    r"(?ms)^        def selected_static_if_rows\(.*?(?=^        def |^    public:|\Z)",
    SOURCE,
)
if match is None:
    raise SystemExit("backend static-if row selector is missing")
selector = match.group(0)
ordered = (
    "condition_ok: mutable bool = row < file.static_if_conds.count and row < file.static_if_modules.count",
    "condition_value: mutable i64 = 0",
    "previous_owner: sview = structs.visibility.current_owner",
    "structs.visibility.current_owner <- file.static_if_modules[row]",
    "condition_value <- fold_const_expr(file.static_if_conds[row], structs, condition_ok)",
    "structs.visibility.current_owner <- previous_owner",
    "continue if not StaticIfPolicy::condition_selects_branch(condition_ok, condition_value)",
)
positions = [selector.find(fragment) for fragment in ordered]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("backend static-if folding must use the row module, restore the prior owner, and keep missing rows unknown")

if not all(fragment in FIXTURE for fragment in (
        "module Outer:",
        "const FEATURE: bool = true",
        "static if FEATURE:",
        "module Inner:",
        "const FEATURE: bool = false",
        "static def compile_time_helper()",
        "return compile_time_helper()")) or not all(fragment in SMOKE for fragment in (
        "static_if_condition_lexical_module.elisa",
        'static function "compile_time_helper" can only be called from a static context')):
    raise SystemExit("backend lexical-module smoke must distinguish Outer::FEATURE from Outer::Inner::FEATURE")

if not all(fragment in BACKEND_FIXTURE for fragment in (
        "const FEATURE: bool = false",
        "module Outer:",
        "const FEATURE: bool = true",
        "static if FEATURE:",
        "const SELECTED: i64 = 1",
        "static else:",
        "const SELECTED: i64 = 2",
        "return Outer::selected() - 1")) or not all(fragment in SMOKE for fragment in (
        "static_if_backend_lexical_module.elisa",
        '"$S1" -emit exe -O0',
        '"$WORK/stage1-backend"')):
    raise SystemExit("backend row-owner regression must execute the module-selected branch against a shadowing root constant")

print("backend static-if lexical-module source binding passed")
