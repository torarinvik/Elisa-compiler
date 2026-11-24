"""IR shapes for the AArch64 float constant pool, shared by its test.

Each case is (IR, CPU, FEATURES): the pass needs a target machine whose CPU fuses literal
loads (`+fuse-literals`). An expensive constant is a normal double needing three or more
16-bit move-immediate chunks.
"""

MAC = 'arm64-apple-macosx14.0.0'
LINUX = 'aarch64-unknown-linux-gnu'
X86 = 'x86_64-apple-macosx14.0.0'
FUSING = ('apple-m1', '')


def expensive(index):
    """A distinct double whose four 16-bit chunks are neither zero nor all ones."""
    return f'0x4009{0x21F9 + index:04X}F01B{0x866E + index:04X}'


def straight(constants, attributes='nounwind', triple=MAC, filler=0, opcode='fmul', uses=None):
    """`x * constant` for each constant (or each slot in USES), summed, then FILLER adds."""
    slots = uses if uses is not None else list(range(len(constants)))
    lines = [f' %m{k} = {opcode} double %x, {constants[slot]}' for k, slot in enumerate(slots)]
    total = '%m0'
    for k in range(1, len(slots)):
        lines.append(f' %s{k} = fadd double {total}, %m{k}')
        total = f'%s{k}'
    for k in range(filler):
        lines.append(f' %f{k} = fadd double {total}, %y')
        total = f'%f{k}'
    body = '\n'.join(lines)
    return f'''target triple = "{triple}"
define double @f(double %x, double %y) {attributes} {{
entry:
{body}
 ret double {total}
}}
'''


def tiny_select(constant=None, kind='double'):
    """`select c, constant, 1.0` returned: a two-instruction function."""
    value = constant or expensive(0)
    return f'''target triple = "{MAC}"
define {kind} @f(i1 %c) nounwind {{
entry:
 %r = select i1 %c, {kind} {value}, {kind} 1.0
 ret {kind} %r
}}
'''


def comparison_and_return(fill=0):
    """One expensive comparison literal and one returned on a branching edge."""
    extra = ''.join(f' %p{k} = fadd double %x, %x\n' for k in range(fill))
    return f'''target triple = "{MAC}"
define double @f(double %x) nounwind {{
entry:
{extra} %c = fcmp olt double %x, {expensive(0)}
 br i1 %c, label %exit, label %other
other:
 %y = fadd double %x, 1.0
 br label %exit
exit:
 %r = phi double [{expensive(1)}, %entry], [%y, %other]
 ret double %r
}}
'''


def return_edges(count=3):
    """A return phi taking an expensive constant from each of COUNT unconditional edges."""
    blocks = ''.join(f'b{k}:\n br label %exit\n' for k in range(count))
    cases = ''.join(f' i32 {k}, label %b{k}' for k in range(count))
    entries = ', '.join(f'[{expensive(k)}, %b{k}]' for k in range(count))
    return f'''target triple = "{MAC}"
define double @f(i32 %k, double %x) nounwind {{
entry:
 switch i32 %k, label %other [{cases} ]
{blocks}other:
 br label %exit
exit:
 %r = phi double {entries}, [%x, %other]
 ret double %r
}}
'''


def switch_edge():
    """A return phi whose constant arrives straight from a switch: not a branch edge."""
    return f'''target triple = "{MAC}"
define double @f(i32 %k, double %x) nounwind {{
entry:
 switch i32 %k, label %other [ i32 0, label %exit ]
other:
 br label %exit
exit:
 %r = phi double [{expensive(0)}, %entry], [%x, %other]
 ret double %r
}}
'''


def shared_edge():
    """Both successors of one conditional branch are the return block."""
    return f'''target triple = "{MAC}"
define double @f(i1 %c, double %x) nounwind {{
entry:
 br i1 %c, label %exit, label %exit
exit:
 %r = phi double [{expensive(0)}, %entry], [{expensive(0)}, %entry]
 ret double %r
}}
'''


def looping():
    """Four expensive multiplies in a loop body: the function has a cycle."""
    products = ''.join(f' %m{k} = fmul double %a, {expensive(k)}\n' for k in range(4))
    return f'''target triple = "{MAC}"
define double @f(double %x, i64 %n) nounwind {{
entry:
 br label %loop
loop:
 %i = phi i64 [0, %entry], [%next, %loop]
 %a = phi double [%x, %entry], [%s3, %loop]
{products} %s1 = fadd double %m0, %m1
 %s2 = fadd double %s1, %m2
 %s3 = fadd double %s2, %m3
 %next = add i64 %i, 1
 %done = icmp eq i64 %next, %n
 br i1 %done, label %exit, label %loop
exit:
 ret double %s3
}}
'''


def debug_located():
    """Four expensive multiplies carrying debug locations."""
    products = ''.join(f' %m{k} = fmul double %x, {expensive(k)}, !dbg !{10 + k}\n' for k in range(4))
    locations = ''.join(f'!{10 + k} = !DILocation(line: {k + 2}, column: 3, scope: !4)\n' for k in range(4))
    return f'''target triple = "{MAC}"
define double @f(double %x) nounwind !dbg !4 {{
entry:
{products} %s1 = fadd double %m0, %m1
 %s2 = fadd double %s1, %m2
 %s3 = fadd double %s2, %m3
 ret double %s3
}}
!llvm.dbg.cu = !{{!0}}
!llvm.module.flags = !{{!2, !3}}
!0 = distinct !DICompileUnit(language: DW_LANG_C, file: !1, emissionKind: FullDebug)
!1 = !DIFile(filename: "f.elisa", directory: "/")
!2 = !{{i32 2, !"Debug Info Version", i32 3}}
!3 = !{{i32 7, !"Dwarf Version", i32 4}}
!4 = distinct !DISubprogram(name: "f", scope: !1, file: !1, line: 1, type: !5, unit: !0, spFlags: DISPFlagDefinition)
!5 = !DISubroutineType(types: !{{}})
{locations}'''


def four(**options):
    return straight([expensive(k) for k in range(4)], **options)


CASES = {
    'tiny_select': (tiny_select(), *FUSING),
    'tiny_select_cheap': (tiny_select('1.5'), *FUSING),
    'tiny_select_float': (tiny_select('0x400921FA00000000', 'float'), *FUSING),
    'tiny_select_infinity': (tiny_select('0x7FF0000000000000'), *FUSING),
    'tiny_select_nan': (tiny_select('0x7FF8123456789ABC'), *FUSING),
    'tiny_select_denormal': (tiny_select('0x000F123456789ABC'), *FUSING),
    'tiny_select_ones': (tiny_select('0xBFFFFFFFFFFF1234'), *FUSING),
    'four_products': (four(), *FUSING),
    'four_products_linux': (four(triple=LINUX), *FUSING),
    'four_products_generic': (four(), 'generic', ''),
    'four_products_feature': (four(), 'generic', '+fuse-literals'),
    'four_products_x86': (four(triple=X86), 'generic', ''),
    'four_products_no_target': (four(), None, None),
    'four_products_target_cpu': (four(attributes='nounwind "target-cpu"="apple-m1"'), *FUSING),
    'four_products_target_features': (four(attributes='nounwind "target-features"="+neon"'), *FUSING),
    'four_products_optnone': (four(attributes='nounwind noinline optnone'), *FUSING),
    'two_products_large': (straight([expensive(0), expensive(1)], filler=30), *FUSING),
    'two_products_short': (straight([expensive(0), expensive(1)], filler=2), *FUSING),
    'three_products_short_table': (straight([expensive(k) for k in range(3)], filler=10), *FUSING),
    'three_subtractions_short': (straight([expensive(k) for k in range(3)], filler=10, opcode='fsub'), *FUSING),
    'three_subtractions_long': (straight([expensive(k) for k in range(3)], filler=20, opcode='fsub'), *FUSING),
    'three_additions': (straight([expensive(k) for k in range(3)], filler=2, opcode='fadd'), *FUSING),
    'shared_six': (straight([expensive(k) for k in range(3)], uses=[0, 1, 2, 0, 1, 2]), *FUSING),
    'shared_five': (straight([expensive(k) for k in range(3)], uses=[0, 1, 2, 0, 1]), *FUSING),
    'shared_thirteen': (straight([expensive(k) for k in range(3)], uses=[0, 1, 2] * 4 + [0]), *FUSING),
    'nine_products': (straight([expensive(k) for k in range(9)]), *FUSING),
    'dense_twelve': (straight([expensive(k) for k in range(12)], filler=50), *FUSING),
    'dense_twenty_four': (straight([expensive(k) for k in range(24)], filler=10), *FUSING),
    'dense_twenty_five': (straight([expensive(k) for k in range(25)], filler=10), *FUSING),
    'too_many_instructions': (straight([expensive(k) for k in range(12)], filler=140), *FUSING),
    'comparison_and_return': (comparison_and_return(), *FUSING),
    'comparison_and_return_long': (comparison_and_return(fill=10), *FUSING),
    'return_edges': (return_edges(), *FUSING),
    'return_edges_five': (return_edges(5), *FUSING),
    'switch_edge': (switch_edge(), *FUSING),
    'shared_edge': (shared_edge(), *FUSING),
    'looping': (looping(), *FUSING),
    'debug_located': (debug_located(), *FUSING),
}
