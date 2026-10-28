#!/usr/bin/env python3
"""Generate verified modules testing clone admission without huge committed fixtures."""
from pathlib import Path
import sys
kind=sys.argv[1]
base=Path("test/parity/stage1_table_unroll_fixture.ll").read_text()
start=base.index("define i64 @positive()")
end=base.index("\ndefine i64 @trip2()",start)
header=base[:start]
function=base[start:end]
if kind=="debug":
    Path("test/parity/stage1_table_unroll_clone_budget_fixture.ll").write_text(Path("test/parity/stage1_table_unroll_debug_fixture.ll").read_text())
    raise SystemExit(0)
if kind=="globals":
    extra="".join(f"@budget_global_{i} = external global i8\n" for i in range(1025))
elif kind=="functions":
    extra="".join(f"declare void @budget_function_{i}()\n" for i in range(2049))
elif kind=="constant":
    extra='@budget_data = private constant [4097 x i8] c"'+('a'*4097)+'"\n'
elif kind=="metadata":
    extra="!budget.node = !{!0}\n!0 = !{}\n"
elif kind=="integer":
    extra="@budget_bigint = private constant i4096 42\n"
elif kind=="longname":
    extra='@"'+('a'*1025)+'" = external global i8\n'
elif kind=="stringattr":
    extra='declare void @budget_attr() #0\nattributes #0 = { "budget_key"="budget_value" }\n'
elif kind=="alias":
    extra='@budget_alias = alias [48 x i64], ptr @table\n'
else:
    raise SystemExit("unknown fixture")
Path("test/parity/stage1_table_unroll_clone_budget_fixture.ll").write_text(header+extra+function+"\n")
