"""IR shapes for the paired index-bound fold, shared by its test.

The base function rejects `a < 0 or b < 0` in its entry block and `a >= n or b >= n` in
the single successor, both to one `invalid` block, for a bound `n = raw & 63`. Variants
change one fact the fold depends on; the loop variants add a loop after the checks to
exercise the Darwin AArch64 leaf-loop alignment.
"""

LINUX = 'aarch64-unknown-linux-gnu'
MAC = 'arm64-apple-macosx14.0.0'

BASE = '''target triple = "TRIPLE"
declare void @observable()
define T @validate(T %a, T %b, T noundef %raw) ATTRIBUTES {
entry:
 %n = and T %raw, 63
 %an = icmp slt T %a, 0
 %bn = icmp slt T %b, 0
 %negative = select i1 %an, i1 true, i1 %bn
 br i1 %negative, label %invalid, label %upper
upper:
 %au = icmp sge T %a, %n
 %bu = icmp sge T %b, %n
 %outside = select i1 %au, i1 true, i1 %bu
 br i1 %outside, label %invalid, label %valid
valid:
 ret T 7
invalid:
 %result = phi T [ -1, %entry ], [ -1, %upper ]
 ret T %result
}
'''


def validation(triple=LINUX, integer='i64', attributes=''):
    text = BASE.replace('TRIPLE', triple).replace('ATTRIBUTES', attributes)
    return text.replace(' T ', f' {integer} ').replace('(T ', f'({integer} ').replace('define T', f'define {integer}').replace(', T ', f', {integer} ')


LOOP = ('valid:\n br label %loop\nloop:\n %i = phi i64 [ 0, %valid ], [ %next, %loop ]\nBODY %next = add i64 %i, 1\n'
        ' %done = icmp eq i64 %next, 16\n br i1 %done, label %finished, label %loopSUFFIX\nfinished:\n ret i64 7')
NESTED = ('valid:\n br label %outer\nouter:\n %o = phi i64 [ 0, %valid ], [ %onext, %olatch ]\n br label %inner\n'
          'inner:\n %i = phi i64 [ 0, %outer ], [ %next, %inner ]\n %next = add i64 %i, 1\n %done = icmp eq i64 %next, 16\n'
          ' br i1 %done, label %olatch, label %inner\nolatch:\n %onext = add i64 %o, 1\n %odone = icmp eq i64 %onext, 4\n'
          ' br i1 %odone, label %finished, label %outer\nfinished:\n ret i64 7')
FOUR_BLOCKS = ('valid:\n br label %loop\nloop:\n %i = phi i64 [ 0, %valid ], [ %next, %join ]\n %pick = icmp eq i64 %i, 3\n'
               ' br i1 %pick, label %left, label %right\nleft:\n br label %join\nright:\n br label %join\njoin:\n'
               ' %next = add i64 %i, 1\n %done = icmp eq i64 %next, 16\n br i1 %done, label %finished, label %loop\nfinished:\n ret i64 7')
TWO_LATCHES = ('valid:\n br label %loop\nloop:\n %i = phi i64 [ 0, %valid ], [ %next, %loop ], [ %next, %side ]\n'
               ' %next = add i64 %i, 1\n %early = icmp eq i64 %next, 3\n br i1 %early, label %side, label %loop\nside:\n'
               ' %done = icmp eq i64 %next, 16\n br i1 %done, label %finished, label %loop\nfinished:\n ret i64 7')
DEBUG_INFO = ('!llvm.dbg.cu = !{!0}\n!llvm.module.flags = !{!3}\n!0 = distinct !DICompileUnit(language: DW_LANG_C99, file: !1, '
              'producer: "x", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, enums: !2)\n'
              '!1 = !DIFile(filename: "a.c", directory: "/")\n!2 = !{}\n!3 = !{i32 2, !"Debug Info Version", i32 3}\n')
WEIGHTS = '!0 = !{!"branch_weights", i32 1, i32 9}\n'


def with_valid(text, replacement):
    return text.replace('valid:\n ret i64 7', replacement, 1)


def with_loop(text, suffix='', body=''):
    return with_valid(text, LOOP.replace('BODY', body).replace('SUFFIX', suffix))


def single_block(triple=LINUX, combine='select', extra=''):
    joint = ' %any = or i1 %negative, %outside\n' if combine == 'or' else ' %any = select i1 %negative, i1 true, i1 %outside\n'
    if extra:
        joint = ' %extra = icmp eq i64 %a, 5\n %more = or i1 %outside, %extra\n %any = select i1 %negative, i1 true, i1 %more\n'
    return (f'target triple = "{triple}"\ndefine i64 @validate(i64 %a, i64 %b, i64 noundef %raw) {{\nentry:\n'
            ' %n = and i64 %raw, 63\n %an = icmp slt i64 %a, 0\n %bn = icmp slt i64 %b, 0\n %negative = or i1 %an, %bn\n'
            ' %au = icmp uge i64 %a, %n\n %bu = icmp sge i64 %b, %n\n %outside = or i1 %au, %bu\n'
            f'{joint} br i1 %any, label %invalid, label %valid\nvalid:\n ret i64 7\ninvalid:\n ret i64 -1\n}}\n')


def build_cases():
    """name -> (IR, functions rewritten, `llvm.loop.align` 16 properties added)."""
    base = validation()
    darwin = validation(triple=MAC)
    second_function = base.split('\n', 2)[2].replace('@validate', '@validate_again').replace('declare void @observable()\n', '')
    return {
        'paired': (base, 1, 0),
        'different_error': (base.replace('[ -1, %upper ]', '[ -2, %upper ]'), 0, 0),
        'observable': (base.replace('upper:\n', 'upper:\n call void @observable()\n'), 0, 0),
        'unknown_bound': (base.replace('%n = and i64 %raw, 63', '%n = add i64 %raw, 0'), 0, 0),
        'negative_bound': (base.replace('%n = and i64 %raw, 63', '%n = or i64 %raw, -64'), 0, 0),
        'wrapped_bound': (base.replace(' %n = and i64 %raw, 63', ' %low = and i64 %raw, 63\n %n = add i64 %low, -10'), 0, 0),
        'continue_phi': (base.replace('valid:\n', 'valid:\n %seen = phi i64 [ 1, %upper ]\n', 1), 0, 0),
        'asan': (validation(attributes='sanitize_address'), 0, 0),
        'msan': (validation(attributes='sanitize_memory'), 0, 0),
        'tsan': (validation(attributes='sanitize_thread'), 0, 0),
        'hwasan': (validation(attributes='sanitize_hwaddress'), 0, 0),
        'memtag': (validation(attributes='sanitize_memtag'), 1, 0),
        'optsize': (validation(attributes='optsize'), 0, 0),
        'minsize': (validation(attributes='minsize'), 0, 0),
        'optnone': (validation(attributes='noinline optnone'), 0, 0),
        'i32': (validation(integer='i32'), 1, 0),
        'i2': (validation(integer='i2').replace('and i2 %raw, 63', 'and i2 %raw, 1').replace('ret i2 7', 'ret i2 1'), 1, 0),
        'i1': (validation(integer='i1').replace('and i1 %raw, 63', 'and i1 %raw, 0').replace('ret i1 7', 'ret i1 0'), 0, 0),
        'i100': (validation(integer='i100'), 1, 0),
        'i128': (validation(integer='i128'), 1, 0),
        'swapped_uses': (base.replace('%au = icmp sge i64 %a, %n', '%au = icmp sge i64 %b, %n').replace('%bu = icmp sge i64 %b, %n', '%bu = icmp sge i64 %a, %n'), 1, 0),
        'unsigned_upper': (base.replace('%au = icmp sge', '%au = icmp uge').replace('%bu = icmp sge', '%bu = icmp uge'), 1, 0),
        'greater_upper': (base.replace('%au = icmp sge', '%au = icmp sgt'), 0, 0),
        'same_index': (base.replace('%bn = icmp slt i64 %b, 0', '%bn = icmp slt i64 %a, 0').replace('%bu = icmp sge i64 %b, %n', '%bu = icmp sge i64 %a, %n'), 0, 0),
        'two_bounds': (base.replace('%bu = icmp sge i64 %b, %n', '%bu = icmp sge i64 %b, %raw'), 0, 0),
        'nonzero_negative': (base.replace('%an = icmp slt i64 %a, 0', '%an = icmp slt i64 %a, 1'), 0, 0),
        'and_select': (base.replace('%negative = select i1 %an, i1 true, i1 %bn', '%negative = select i1 %an, i1 %bn, i1 false'), 0, 0),
        'constant_bound': (base.replace('%au = icmp sge i64 %a, %n', '%au = icmp sge i64 %a, 10').replace('%bu = icmp sge i64 %b, %n', '%bu = icmp sge i64 %b, 10'), 1, 0),
        'single_bound_maybe_poison': (base.replace('i64 noundef %raw', 'i64 %raw').replace('%n = and i64 %raw, 63', '%n = and i64 %raw, 0'), 0, 0),
        'single_bound_noundef': (base.replace('%n = and i64 %raw, 63', '%n = and i64 %raw, 0'), 1, 0),
        'maybe_poison_range': (base.replace('i64 noundef %raw', 'i64 %raw'), 1, 0),
        'bound_in_upper': (base.replace(' %n = and i64 %raw, 63\n', '').replace('upper:\n', 'upper:\n %n = and i64 %raw, 63\n'), 0, 0),
        'branch_metadata': (base.replace('label %invalid, label %upper', 'label %invalid, label %upper, !prof !0') + WEIGHTS, 0, 0),
        'second_branch_metadata': (base.replace('label %invalid, label %valid', 'label %invalid, label %valid, !prof !0') + WEIGHTS, 0, 0),
        'compare_metadata': (base.replace('%au = icmp sge i64 %a, %n', '%au = icmp sge i64 %a, %n, !note !0') + '!0 = !{}\n', 0, 0),
        'used_outside': (with_valid(base, 'valid:\n %z = zext i1 %au to i64\n ret i64 %z'), 0, 0),
        'other_exit': (base.replace('label %invalid, label %valid', 'label %other, label %valid').replace('\nvalid:\n', '\nother:\n ret i64 -1\nvalid:\n', 1).replace('[ -1, %entry ], [ -1, %upper ]', '[ -1, %entry ]'), 0, 0),
        'shared_upper': (base.replace(' %an = icmp slt', ' br i1 %flag, label %start, label %upper\nstart:\n %an = icmp slt', 1).replace('%raw) ', '%raw, i1 %flag) ', 1).replace('[ -1, %entry ]', '[ -1, %start ]'), 0, 0),
        'single_block': (single_block(), 1, 0),
        'single_block_or': (single_block(combine='or'), 1, 0),
        'single_block_darwin': (single_block(triple=MAC), 1, 0),
        'too_many_leaves': (single_block(extra=True), 0, 0),
        'debug_module': (base + DEBUG_INFO, 0, 0),
        'two_functions': (base + second_function, 2, 0),
        'darwin_loop': (with_loop(darwin), 1, 1),
        'linux_loop': (with_loop(base), 1, 0),
        'explicit_align': (with_loop(darwin, ', !llvm.loop !0') + '!0 = distinct !{!0, !1}\n!1 = !{!"llvm.loop.align", i32 8}\n', 1, 0),
        'other_property': (with_loop(darwin, ', !llvm.loop !0') + '!0 = distinct !{!0, !1}\n!1 = !{!"llvm.loop.unroll.disable"}\n', 1, 1),
        'empty_property': (with_loop(darwin, ', !llvm.loop !0') + '!0 = distinct !{!0, !1, !2}\n!1 = !{!"llvm.loop.mustprogress"}\n!2 = !{}\n', 1, 1),
        'big_loop': (with_loop(darwin, body=''.join(f' %f{index} = add i64 %i, {index}\n' for index in range(30))), 1, 0),
        'call_loop': (with_loop(darwin, body=' call void @observable()\n'), 1, 0),
        'nested_loop': (with_valid(darwin, NESTED), 1, 1),
        'four_block_loop': (with_valid(darwin, FOUR_BLOCKS), 1, 0),
        'two_latch_loop': (with_valid(darwin, TWO_LATCHES), 1, 0),
        'many_instructions': (with_valid(base, 'valid:\n' + ''.join(f' %g{index} = add i64 %a, {index}\n' for index in range(2500)) + ' ret i64 7'), 0, 0),
    }


CASES = build_cases()
