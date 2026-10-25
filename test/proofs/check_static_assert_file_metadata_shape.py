"""Keep explicit Ast::File constructors aligned with captured static-assert metadata."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE = (ROOT / "test/repro/cpu_optional_goal_allocation_probe.elisa").read_text()

constructor_start = PROBE.find("file: Ast::File = Ast::File{")
if constructor_start < 0:
    raise SystemExit("CPU allocation probe no longer constructs an explicit Ast::File")
constructor_end = PROBE.find("\n                        }", constructor_start)
if constructor_end < 0:
    raise SystemExit("CPU allocation probe Ast::File constructor is unterminated")
constructor = PROBE[constructor_start:constructor_end]
for field in (
    "static_assert_modules: [],",
    "static_assert_branch_row_starts: [],",
    "static_assert_branch_row_counts: [],",
    "static_assert_branch_row_ids: [],",
    "static_assert_branch_rows_known: [],",
):
    if field not in constructor:
        raise SystemExit(f"explicit Ast::File constructor is missing {field.split(':')[0]}")

print("Static-assert Ast::File metadata source binding passed")
