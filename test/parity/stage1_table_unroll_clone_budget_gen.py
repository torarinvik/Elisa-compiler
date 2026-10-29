#!/usr/bin/env python3
"""Generate verified modules testing clone admission without huge committed fixtures."""
from pathlib import Path
import re
import sys
kind=sys.argv[1]
base=Path("test/parity/stage1_table_unroll_fixture.ll").read_text()
positive=re.search(r"^define\b[^\n]*@positive\(\)[^\n]*\{\n", base, re.M)
if not positive:
    raise SystemExit("positive fixture function not found")
start=positive.start()
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
elif kind=="instruction_metadata":
    extra=('define void @budget_instruction_metadata(i1 %c) {\n'
           'entry:\n'
           '  br i1 %c, label %yes, label %no, !prof !0\n'
           'yes:\n  ret void\n'
           'no:\n  ret void\n'
           '}\n'
           '!0 = !{!"branch_weights", i32 1, i32 1}\n')
elif kind=="integer":
    extra="@budget_bigint = private constant i4096 42\n"
elif kind=="longname":
    extra='@"'+('a'*1025)+'" = external global i8\n'
elif kind=="stringattr":
    extra='declare void @budget_attr() #0\nattributes #0 = { "budget_key"="budget_value" }\n'
elif kind=="alias":
    extra='@budget_alias = alias [48 x i64], ptr @table\n'
elif kind=="shuffle":
    extra="define void @budget_shuffle(<8192 x i8> %a) {\nentry:\n"
    extra+="".join(f"  %s{i} = shufflevector <8192 x i8> %a, <8192 x i8> %a, <8192 x i32> zeroinitializer\n" for i in range(9))
    extra+="  ret void\n}\n"
elif kind=="rangelist":
    ranges=", ".join(f"({i*2}, {i*2+1})" for i in range(257))
    extra=f"declare void @budget_rangelist(ptr initializes({ranges}) %p)\n"
elif kind=="control":
    extra='declare void @budget_expect_attempt()\n'
elif kind=="edges":
    # Keep each PHI at or below the per-instruction operand cap even if LLVM
    # exposes both incoming values and blocks through LLVMGetNumOperands.
    predecessors=128
    phis=513
    lines=["define i32 @budget_phi_edges(i1 %c, i32 %v) {", "entry:", "  br i1 %c, label %p0, label %p1"]
    for i in range(predecessors):
        lines.append(f"p{i}:")
        if i == predecessors-1:
            lines.append("  br label %join")
        else:
            lines.append(f"  br i1 %c, label %join, label %p{i+1}")
    lines.append("join:")
    incoming=", ".join(f"[ %v, %p{i} ]" for i in range(predecessors))
    lines.extend(f"  %edge_phi_{i} = phi i32 {incoming}" for i in range(phis))
    lines.extend(["  ret i32 %edge_phi_0", "}"])
    extra="\n".join(lines)+"\n"
elif kind=="section_global":
    section="s"*1025
    extra=f'@budget_section_global = private global i8 0, section "{section}"\n'
elif kind=="section_function":
    section="s"*1025
    extra=f'define void @budget_section_function() section "{section}" {{ ret void }}\n'
elif kind=="comdat":
    extra='$budget_group = comdat any\n@budget_comdat_global = linkonce_odr global i8 0, comdat($budget_group)\n'
elif kind=="comdat_function":
    extra='$budget_group = comdat any\ndefine linkonce_odr void @budget_comdat_function() comdat($budget_group) { ret void }\n'
elif kind=="gc":
    strategy="g"*1025
    extra=f'define void @budget_gc() gc "{strategy}" {{ ret void }}\n'
elif kind=="personality":
    extra='declare i32 @budget_personality(...)\ndefine void @budget_personality_owner() personality ptr @budget_personality { ret void }\n'
elif kind=="prefix":
    extra='define void @budget_prefix() prefix i8 0 { ret void }\n'
elif kind=="prologue":
    extra='define void @budget_prologue() prologue i8 0 { ret void }\n'
else:
    raise SystemExit("unknown fixture")
Path("test/parity/stage1_table_unroll_clone_budget_fixture.ll").write_text(header+extra+function+"\n")
