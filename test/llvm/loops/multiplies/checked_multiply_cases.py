"""IR cases for the checked-multiply folds, shared by their test and parity checks."""
import os

ARM64 = 'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "arm64-apple-macosx14.0.0"\n'
X86 = 'target datalayout = "e-m:e-i64:64-i128:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'
DECLARATIONS = '''declare { i64, i1 } @llvm.smul.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare void @llvm.trap()
'''
TRAP = 'trap:\n  call void @llvm.trap()\n  unreachable\n'


def checked(name, op, left, right):
    return (f'  %{name}.pair = call {{ i64, i1 }} @llvm.{op}.with.overflow.i64(i64 {left}, i64 {right})\n'
            f'  %{name} = extractvalue {{ i64, i1 }} %{name}.pair, 0\n'
            f'  %{name}.flag = extractvalue {{ i64, i1 }} %{name}.pair, 1\n')


def module(body, target=ARM64, extra=''):
    return target + DECLARATIONS + body + extra


# A product of loaded values: nothing bounds it, so it is versioned.
def loaded_product(right='%x', flag_uses=1):
    extra_use = '  %again = zext i1 %low.flag to i64\n' if flag_uses > 1 else ''
    return f'''define i64 @product(ptr %p, i64 %n) {{
entry:
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %exit, label %loop
loop:
  %i = phi i64 [ 0, %entry ], [ %next, %continue ]
  %acc = phi i64 [ 1, %entry ], [ %low, %continue ]
  %slot = getelementptr i64, ptr %p, i64 %i
  %x = load i64, ptr %slot, align 8
{checked('low', 'smul', '%acc', right)}{extra_use}  br i1 %low.flag, label %trap, label %continue
continue:
  %next = add i64 %i, 1
  %done = icmp eq i64 %next, %n
  br i1 %done, label %exit, label %loop
{TRAP}exit:
  %r = phi i64 [ 1, %entry ], [ %low, %continue ]
  ret i64 %r
}}
'''


# i * (i + 3) summed over a cursor whose limit the entry guard keeps at most LIMIT.
def cursor_sum(limit=1000, noundef=''):
    return f'''define i64 @squares(i64 {noundef}%n) {{
entry:
  %big = icmp ugt i64 %n, {limit}
  br i1 %big, label %exit, label %loop
loop:
  %i = phi i64 [ 0, %entry ], [ %next, %latch ]
  %sum = phi i64 [ 0, %entry ], [ %total, %latch ]
  %offset = add i64 %i, 3
{checked('square', 'smul', '%i', '%offset')}  br i1 %square.flag, label %trap, label %add
add:
{checked('total', 'sadd', '%sum', '%square')}  br i1 %total.flag, label %trap, label %latch
latch:
  %next = add i64 %i, 1
  %done = icmp eq i64 %i, %n
  br i1 %done, label %exit, label %loop
{TRAP}exit:
  %r = phi i64 [ -1, %entry ], [ %total, %latch ]
  ret i64 %r
}}
'''


# The outer counter's square in the header of a loop that holds another loop.
def outer_square(trips=100):
    return f'''define i64 @outer(i64 %m) {{
entry:
  br label %outer
outer:
  %i = phi i64 [ 0, %entry ], [ %inext, %outer.latch ]
  %acc = phi i64 [ 0, %entry ], [ %acc2, %outer.latch ]
{checked('sq', 'smul', '%i', '%i')}  br i1 %sq.flag, label %trap, label %inner.pre
inner.pre:
  br label %inner
inner:
  %j = phi i64 [ 0, %inner.pre ], [ %jnext, %inner ]
  %a = phi i64 [ %acc, %inner.pre ], [ %a2, %inner ]
  %a2 = add i64 %a, %sq
  %jnext = add i64 %j, 1
  %jd = icmp eq i64 %jnext, %m
  br i1 %jd, label %outer.latch, label %inner
outer.latch:
  %acc2 = phi i64 [ %a2, %inner ]
  %inext = add nuw nsw i64 %i, 1
  %od = icmp eq i64 %inext, {trips}
  br i1 %od, label %exit, label %outer
{TRAP}exit:
  ret i64 %acc2
}}
'''


# The integer square root by counting: continue while i * i <= n, n bounded by an `or`
# of biased tests as LLVM folds source bounds.
def bounded_root(limit=1000000, predicate='sgt'):
    return f'''define i64 @root(i64 noundef %n) {{
entry:
  %biased = add i64 %n, 1
  %high = icmp ugt i64 %biased, {limit + 1 if limit >= 0 else -1}
  %special = icmp eq i64 %n, 77
  %bad = or i1 %high, %special
  br i1 %bad, label %exit, label %loop
loop:
  %i = phi i64 [ 1, %entry ], [ %inext, %inc ]
{checked('sq', 'smul', '%i', '%i')}  br i1 %sq.flag, label %trap, label %test
test:
  %over = icmp {predicate} i64 %sq, %n
  br i1 %over, label %exit, label %inc
inc:
{checked('inext', 'sadd', '%i', '1')}  br i1 %inext.flag, label %trap, label %loop
{TRAP}exit:
  %r = phi i64 [ -1, %entry ], [ %i, %test ]
  ret i64 %r
}}
'''


# base^k for base in 0..BASE and k in 1..TRIPS, already versioned: the fast path
# multiplies, the slow path keeps the tagged checked multiply.
def guarded_power(trips=16, base=10, defined='noundef '):
    return f'''define i64 @power(i64 noundef %base, i64 {defined}%k) "elisa.checkedmul.versioned" {{
entry:
  %kbig = icmp ugt i64 %k, {trips}
  %kzero = icmp eq i64 %k, 0
  %kbad = or i1 %kbig, %kzero
  br i1 %kbad, label %exit, label %check.base
check.base:
  %bneg = icmp slt i64 %base, 0
  %bbig = icmp sgt i64 %base, {base}
  %bbad = or i1 %bneg, %bbig
  br i1 %bbad, label %exit, label %loop
loop:
  %i = phi i64 [ 0, %check.base ], [ %inext, %continue ]
  %p = phi i64 [ 1, %check.base ], [ %low, %continue ]
  %low = mul i64 %p, %base
  %cheap = icmp ule i64 %base, 1
  br i1 %cheap, label %continue, label %slow
slow:
  %pair = call {{ i64, i1 }} @llvm.smul.with.overflow.i64(i64 %p, i64 %base), !elisa.checkedmul.slow !0
  %flag = extractvalue {{ i64, i1 }} %pair, 1
  br i1 %flag, label %trap, label %continue
continue:
  %inext = add i64 %i, 1
  %done = icmp eq i64 %inext, %k
  br i1 %done, label %exit, label %loop
{TRAP}exit:
  %r = phi i64 [ -1, %entry ], [ -1, %check.base ], [ %low, %continue ]
  ret i64 %r
}}

!0 = !{{}}
'''


# An unchecked power loop of a single block, its trips guarded to 1..TRIPS.
def short_power(trips=8):
    return f'''define i64 @short(i64 %base, i64 %k) {{
entry:
  %big = icmp ugt i64 %k, {trips}
  br i1 %big, label %exit, label %check
check:
  %zero = icmp eq i64 %k, 0
  br i1 %zero, label %exit, label %loop
loop:
  %i = phi i64 [ 0, %check ], [ %inext, %loop ]
  %p = phi i64 [ 1, %check ], [ %m, %loop ]
  %m = mul i64 %p, %base
  %inext = add i64 %i, 1
  %done = icmp eq i64 %inext, %k
  br i1 %done, label %exit, label %loop
exit:
  %r = phi i64 [ 0, %entry ], [ 0, %check ], [ %m, %loop ]
  ret i64 %r
}}
'''


# A table of checked squares built in a private array, then read.
def initializer(length=16):
    return f'''define i64 @table(i64 %index) {{
entry:
  %a = alloca [{length} x i64], align 8
  br label %loop
loop:
  %i = phi i64 [ 0, %entry ], [ %inext, %latch ]
{checked('sq', 'smul', '%i', '%i')}  br i1 %sq.flag, label %trap, label %latch
latch:
  %slot = getelementptr inbounds [{length} x i64], ptr %a, i64 0, i64 %i
  store i64 %sq, ptr %slot, align 8
  %inext = add i64 %i, 1
  %done = icmp eq i64 %inext, {length}
  br i1 %done, label %exit, label %loop
{TRAP}exit:
  %read = getelementptr inbounds [{length} x i64], ptr %a, i64 0, i64 5
  %r = load i64, ptr %read, align 8
  ret i64 %r
}}
'''


DEBUG = '!llvm.dbg.cu = !{!0}\n!llvm.module.flags = !{!3}\n!0 = distinct !DICompileUnit(language: DW_LANG_C, file: !1, emissionKind: FullDebug)\n!1 = !DIFile(filename: "a.c", directory: "/")\n!3 = !{i32 2, !"Debug Info Version", i32 3}\n'

# name: module
CASES = {
    'versioned': module(loaded_product()),
    'versioned_x86': module(loaded_product(), target=X86),
    'versioned_debug_info': module(loaded_product(), extra=DEBUG),
    'constant_operand': module(loaded_product(right='7')),
    'flag_used_twice': module(loaded_product(flag_uses=2)),
    'cursor_sum': module(cursor_sum()),
    'cursor_sum_noundef': module(cursor_sum(noundef='noundef ')),
    'cursor_unbounded': module(cursor_sum(limit=-1)),
    'outer_square': module(outer_square()),
    'outer_square_large': module(outer_square(trips=4000000000)),
    'bounded_root': module(bounded_root()),
    'bounded_root_large_limit': module(bounded_root(limit=-1)),
    'bounded_root_signed_greater_equal': module(bounded_root(predicate='sge')),
    'guarded_power': module(guarded_power()),
    'guarded_power_seventeen': module(guarded_power(trips=17)),
    'guarded_power_large_base': module(guarded_power(base=20000)),
    'guarded_power_argument_limit': module(guarded_power(defined='')),
    'short_power': module(short_power()),
    'short_power_nine': module(short_power(trips=9)),
    'initializer': module(initializer()),
    'initializer_long': module(initializer(length=200)),
}


def write_cases(directory):
    for name, ir in CASES.items():
        with open(os.path.join(directory, name + '.ll'), 'w') as file:
            file.write(ir)
