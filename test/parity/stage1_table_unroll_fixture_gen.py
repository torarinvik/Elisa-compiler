#!/usr/bin/env python3
"""Assemble the unroll cases and generate the many-loop graph-budget module."""
from pathlib import Path
import sys

source = Path(__file__).resolve().parent
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
control = (source / "stage1_table_unroll_control_flow_cases.ll").read_text()
large_debug = (source / "stage1_table_unroll_large_and_debug_cases.ll").read_text()
callsite = (source / "stage1_table_unroll_callsite_range_case.ll").read_text()
marker = "define i64 @positive()"
assert control.count(marker) == 1
full = control.replace(marker, callsite + marker, 1) + large_debug
(output / "stage1_table_unroll_fixture.ll").write_text(full)

# The graph budget is exercised by 70 sequential loops in one function.
header = "\n".join(control.splitlines()[:3]) + "\n"
lines = [header, "define i64 @many_loops() {\nentry:\n  br label %loop0\n"]
for i in range(70):
    previous = "entry" if i == 0 else f"loop{i - 1}"
    next_block = "exit" if i == 69 else f"loop{i + 1}"
    lines.append(f"loop{i}:\n  %i{i} = phi i64 [ 0, %{previous} ], [ %next{i}, %loop{i} ]\n")
    for j in range(4):
        lines.append(f"  %ix{i}_{j} = add i64 %i{i}, {j * 12}\n")
        lines.append(f"  %p{i}_{j} = getelementptr [48 x i64], ptr @table, i64 0, i64 %ix{i}_{j}\n")
        lines.append(f"  %v{i}_{j} = load i64, ptr %p{i}_{j}, align 8\n")
    lines.append(f"  %next{i} = add nuw nsw i64 %i{i}, 1\n")
    lines.append(f"  %done{i} = icmp eq i64 %next{i}, 12\n")
    lines.append(f"  br i1 %done{i}, label %{next_block}, label %loop{i}\n")
lines.append("exit:\n  ret i64 0\n}\n")
(output / "stage1_table_unroll_graph_budget_fixture.ll").write_text("".join(lines))
