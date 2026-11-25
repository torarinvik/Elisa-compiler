"""IR shapes for the small-recursion passes, shared by their tests.

Each case is `(mode, ir)`. `inline` runs the whole `recursive-inline` pass (literal
specialization, snapshot expansion, entry inlining, the O3 cleanup, zero versioning,
accumulator proofs and guard bias); `candidate` asks only whether `@tree` is a
recursive-inline candidate; `literals`, `zero` and `bias` run that step twice;
`accumulators` runs only the checked-accumulator rewrite. Each case's expected count
is what the C++ passes did with the same shapes (see EXPECTED).
"""
from elisa_llvm_pass import run_pass, run_pass_with_target

DARWIN = 'arm64-apple-darwin'
LINUX = 'aarch64-unknown-linux-gnu'
X86 = 'x86_64-apple-macosx14.0.0'


def tree(triple=DARWIN, attributes='nounwind', linkage='private', step_extra='', second_call=True, padding=0, tail=''):
    """A private binary recursion of about twenty instructions with an entry equality test."""
    second = '  %b = call fastcc i64 @tree(i64 %next)' if second_call else '  %b = add i64 %next, 1'
    pad = ''.join(f'  %pad{index} = add i64 %n, {index}\n' for index in range(padding))
    return f'''target triple = "{triple}"
define {linkage} fastcc i64 @tree(i64 %n) {attributes} {{
entry:
  %empty = icmp eq i64 %n, 0
  br i1 %empty, label %base, label %step
base:
  ret i64 1
step:
{step_extra}  %next = sub i64 %n, 1
  %a = call fastcc i64 @tree(i64 %next)
{second}
  %c = add i64 %a, %b
  %d = add i64 %c, %a
  %e = xor i64 %d, %b
  %f = add i64 %e, %a
  %g = xor i64 %f, %b
  %h = add i64 %g, %a
  %i = xor i64 %h, %b
  %j = add i64 %i, %a
  %k = xor i64 %j, %b
{pad}  ret i64 %k
}}
define i64 @entry(i64 %n) {{
  %r = call fastcc i64 @tree(i64 %n)
  ret i64 %r
}}
{tail}'''


def linear(triple=DARWIN, entries=1):
    """A guarded linear recursion over a view: `i < view.len` else trap, one recursive call."""
    callers = ''.join(f'''define i64 @entry{index}(ptr %data, i64 %length) {{
  %view.0 = insertvalue {{ ptr, i64 }} poison, ptr %data, 0
  %view = insertvalue {{ ptr, i64 }} %view.0, i64 %length, 1
  %r = call i64 @walk({{ ptr, i64 }} %view, i64 0)
  ret i64 %r
}}
''' for index in range(entries))
    return f'''target triple = "{triple}"
declare void @llvm.trap()
define private i64 @walk({{ ptr, i64 }} %view, i64 %i) nounwind {{
entry:
  %length = extractvalue {{ ptr, i64 }} %view, 1
  %inside = icmp ult i64 %i, %length
  br i1 %inside, label %body, label %fail
fail:
  call void @llvm.trap()
  unreachable
body:
  %data = extractvalue {{ ptr, i64 }} %view, 0
  %slot = getelementptr i64, ptr %data, i64 %i
  %value = load i64, ptr %slot, align 8
  %stop = icmp eq i64 %value, 0
  br i1 %stop, label %done, label %more
more:
  %next = add i64 %i, 1
  %rest = call i64 @walk({{ ptr, i64 }} %view, i64 %next)
  %scaled = mul i64 %value, 3
  %sum = add i64 %rest, %scaled
  ret i64 %sum
done:
  ret i64 %i
}}
{callers}'''


def literal(attributes='', other_literal=False, external=False):
    """A binary recursion whose mode argument is a literal at its outside calls."""
    linkage = '' if external else 'private '
    body = [f'target triple = "{DARWIN}"', f'define {linkage}i64 @tree(i64 %n, i64 %mode) {attributes} {{', 'entry:',
            '  %end = icmp eq i64 %n, 0', '  br i1 %end, label %base, label %step', 'base:', '  ret i64 %mode', 'step:',
            '  %next = sub i64 %n, 1', '  %nextmode = add i64 %mode, 1', '  %a = call i64 @tree(i64 %next, i64 %mode)',
            '  %b = call i64 @tree(i64 %next, i64 %nextmode)']
    previous = '%a'
    for index in range(40):
        body.append(f'  %x{index} = add i64 {previous}, %b')
        previous = f'%x{index}'
    body += [f'  ret i64 {previous}', '}',
             'define i64 @entry_one(i64 %n) {\n  %r = call i64 @tree(i64 %n, i64 1)\n  ret i64 %r\n}',
             'define i64 @entry_dynamic(i64 %n, i64 %x) {\n  %r = call i64 @tree(i64 %n, i64 %x)\n  ret i64 %r\n}']
    if other_literal:
        body.append('define i64 @entry_two(i64 %n) {\n  %r = call i64 @tree(i64 %n, i64 2)\n  ret i64 %r\n}')
    return '\n'.join(body) + '\n'


def zero_helper(attributes='', caller_attributes='', variant=False, effects=''):
    """A literal-specialized helper returning zero for a zero argument, called in a loop."""
    argument = '%i' if variant else '%n'
    return f'''target triple = "{DARWIN}"
define private i1 @helper(i64 %n, ptr %p) {attributes} "elisa.literal-specialized" {{
entry:
  %old = load {effects}i64, ptr %p, align 8
  %new = add i64 %old, 1
  store {effects}i64 %new, ptr %p, align 8
  %zero = icmp eq i64 %n, 0
  br i1 %zero, label %done, label %recurse
recurse:
  %next = sub i64 %n, 1
  %r = call i1 @helper(i64 %next, ptr %p)
  br label %done
done:
  %result = phi i1 [ false, %entry ], [ %r, %recurse ]
  ret i1 %result
}}
define i64 @entry(i64 %n, i64 %iterations) {caller_attributes} {{
entry:
  %state = alloca i64, align 8
  store i64 0, ptr %state, align 8
  br label %loop
loop:
  %i = phi i64 [ 0, %entry ], [ %inc, %loop ]
  %r = call i1 @helper(i64 {argument}, ptr %state)
  %inc = add i64 %i, 1
  %done = icmp uge i64 %inc, %iterations
  br i1 %done, label %exit, label %loop
exit:
  %out = load i64, ptr %state, align 8
  ret i64 %out
}}
'''


def guarded_call(triple=DARWIN, attributes='', profile=False, marked=True):
    """A search loop whose matching edge calls a zero-versioned helper."""
    marker = '"elisa.zero-versioned"' if marked else ''
    weights = ', !prof !0' if profile else ''
    metadata = '!0 = !{!"branch_weights", i32 9, i32 7}\n' if profile else ''
    return f'''target triple = "{triple}"
define private i64 @helper(i64 %x) {marker} {{
entry:
  %r = add i64 %x, 5
  ret i64 %r
}}
define i64 @entry(i64 %target, i64 %n) {attributes} {{
entry:
  br label %loop
loop:
  %i = phi i64 [ 0, %entry ], [ %next, %join ]
  %sum = phi i64 [ 0, %entry ], [ %v, %join ]
  %equal = icmp eq i64 %i, %target
  br i1 %equal, label %match, label %join{weights}
match:
  %called = call i64 @helper(i64 %i)
  br label %join
join:
  %v = phi i64 [ %sum, %loop ], [ %called, %match ]
  %next = add i64 %i, 1
  %done = icmp uge i64 %next, %n
  br i1 %done, label %exit, label %loop
exit:
  ret i64 %v
}}
{metadata}'''


def accumulator(operation='sadd', width='i64', invariant='%x', order='invariant-first', returns='continue', result_block='recurse',
                passed='%x', guard='', linkage='private', calls=1, base=True, extra='', triple=DARWIN):
    """`return x op f(n - 1, x)` with `op` an overflow-checked intrinsic and a trapping overflow edge.

    `returns` places the recursion's value: `continue` (Continue holds `ret`), `merged` (Continue
    branches to a shared `ret phi`), `shared` (the overflow-free edge enters the shared return).
    `guard` adds an entry bound `n <u guard` that traps otherwise, so the depth has a maximum.
    """
    pair = f'{{ {width}, i1 }}'
    operands = f'{width} {invariant}, {width} %inner' if order == 'invariant-first' else f'{width} %inner, {width} {invariant}'
    bound = f'''  %small = icmp ult i64 %n, {guard}
  br i1 %small, label %start, label %fail
start:
''' if guard else ''
    second = f'  %again = call {width} @sum(i64 %next, {width} %x)\n' if calls == 2 else ''
    value_line = f'  %value = extractvalue {pair} %pair, 0\n'
    in_recurse = value_line if result_block == 'recurse' else ''
    in_continue = value_line if result_block == 'continue' else ''
    if returns == 'continue':
        continue_block = f'continue:\n{in_continue}  ret {width} %value\n'
        exit_block = f'done:\n  ret {width} 7\n' if base else ''
        overflow_target = 'continue'
    elif returns == 'merged':
        continue_block = f'continue:\n{in_continue}  br label %exit\n'
        exit_block = f'done:\n  br label %exit\nexit:\n  %out = phi {width} [ 7, %done ], [ %value, %continue ]\n  ret {width} %out\n'
        overflow_target = 'continue'
    else:
        continue_block = ''
        exit_block = f'done:\n  br label %exit\nexit:\n  %out = phi {width} [ 7, %done ], [ %value, %recurse ]\n  ret {width} %out\n'
        overflow_target = 'exit'
    base_test = '  %base = icmp eq i64 %n, 0\n  br i1 %base, label %done, label %recurse\n' if base else '  br label %recurse\n'
    return f'''target triple = "{triple}"
declare void @llvm.trap()
declare {pair} @llvm.{operation}.with.overflow.{width}({width}, {width})
define {linkage} {width} @sum(i64 %n, {width} %x) nounwind {{
entry:
{bound}{base_test}recurse:
{extra}  %next = sub i64 %n, 1
  %inner = call {width} @sum(i64 %next, {width} {passed})
{second}  %pair = call {pair} @llvm.{operation}.with.overflow.{width}({operands})
{in_recurse}  %overflow = extractvalue {pair} %pair, 1
  br i1 %overflow, label %trap, label %{overflow_target}
trap:
  call void @llvm.trap()
  unreachable
{continue_block}{exit_block}{'fail:' + chr(10) + '  call void @llvm.trap()' + chr(10) + '  unreachable' + chr(10) if guard else ''}}}
define {width} @entry(i64 %n, {width} %x) {{
  %r = call {width} @sum(i64 %n, {width} %x)
  ret {width} %r
}}
'''


CASES = {
    'inline-binary-darwin': ('inline', tree()),
    'inline-binary-linux': ('inline', tree(triple=LINUX)),
    'inline-binary-x86': ('inline', tree(triple=X86)),
    'inline-debug-module': ('inline', tree(tail='!llvm.dbg.cu = !{}\n!llvm.module.flags = !{!0}\n!0 = !{i32 2, !"Debug Info Version", i32 3}\n')),
    'inline-linear-one-entry': ('inline', linear()),
    'inline-linear-two-entries': ('inline', linear(entries=2)),
    'inline-linear-three-entries': ('inline', linear(entries=3)),
    'inline-literal': ('inline', literal()),
    'inline-zero-helper': ('inline', zero_helper()),
    'inline-accumulator-bounded': ('inline', accumulator(operation='smul', invariant='3', guard='12')),
    'inline-accumulator-wide': ('inline', accumulator(width='i128', invariant='5', guard='20')),
    'inline-accumulator-unbounded': ('inline', accumulator()),
    'inline-accumulator-unbounded-step': ('inline', accumulator(operation='smul', guard='12')),
    'inline-accumulator-unsigned': ('inline', accumulator(operation='uadd', invariant='4', guard='12')),
    'candidate-binary': ('candidate', tree()),
    'candidate-noinline': ('candidate', tree(attributes='nounwind noinline')),
    'candidate-optsize': ('candidate', tree(attributes='nounwind optsize')),
    'candidate-sanitizer': ('candidate', tree(attributes='nounwind sanitize_address')),
    'candidate-convergent': ('candidate', tree(attributes='nounwind convergent')),
    'candidate-may-unwind': ('candidate', tree(attributes='')),
    'candidate-external': ('candidate', tree(linkage='')),
    'candidate-address-taken': ('candidate', tree(tail='@address = global ptr @tree\n')),
    'candidate-alloca': ('candidate', tree(step_extra='  %slot = alloca i64\n')),
    'candidate-external-call': ('candidate', tree(step_extra='  call void @other()\n', tail='declare void @other()\n')),
    'candidate-one-call': ('candidate', tree(second_call=False)),
    'candidate-too-large': ('candidate', tree(padding=150)),
    'literals-eligible': ('literals', literal()),
    'literals-different': ('literals', literal(other_literal=True)),
    'literals-noinline': ('literals', literal(attributes='noinline')),
    'literals-optsize': ('literals', literal(attributes='optsize')),
    'literals-sanitizer': ('literals', literal(attributes='sanitize_address')),
    'literals-noduplicate': ('literals', literal(attributes='noduplicate')),
    'literals-returns-twice': ('literals', literal(attributes='returns_twice')),
    'literals-external': ('literals', literal(external=True)),
    'zero-eligible': ('zero', zero_helper()),
    'zero-volatile': ('zero', zero_helper(effects='volatile ')),
    'zero-variant-argument': ('zero', zero_helper(variant=True)),
    'zero-callee-noinline': ('zero', zero_helper(attributes='noinline')),
    'zero-callee-sanitizer': ('zero', zero_helper(attributes='sanitize_address')),
    'zero-caller-sanitizer': ('zero', zero_helper(caller_attributes='sanitize_address')),
    'zero-callee-returns-twice': ('zero', zero_helper(attributes='returns_twice')),
    'bias-eligible': ('bias', guarded_call()),
    'bias-existing-profile': ('bias', guarded_call(profile=True)),
    'bias-unmarked-callee': ('bias', guarded_call(marked=False)),
    'bias-caller-sanitizer': ('bias', guarded_call(attributes='sanitize_address')),
    'bias-linux': ('bias', guarded_call(triple=LINUX)),
    'accumulator-add': ('accumulators', accumulator()),
    'accumulator-sub': ('accumulators', accumulator(operation='ssub')),
    'accumulator-mul-constant': ('accumulators', accumulator(operation='smul', invariant='3')),
    'accumulator-call-first': ('accumulators', accumulator(order='call-first')),
    'accumulator-merged-return': ('accumulators', accumulator(returns='merged')),
    'accumulator-shared-return': ('accumulators', accumulator(returns='shared')),
    'accumulator-result-in-continue': ('accumulators', accumulator(result_block='continue')),
    'accumulator-guarded': ('accumulators', accumulator(guard='12')),
    'accumulator-unsigned': ('accumulators', accumulator(operation='uadd')),
    'accumulator-wide': ('accumulators', accumulator(width='i128')),
    'accumulator-changed-invariant': ('accumulators', accumulator(passed='%x.next', extra='  %x.next = add i64 %x, 1\n')),
    'accumulator-two-calls': ('accumulators', accumulator(calls=2)),
    'accumulator-no-base': ('accumulators', accumulator(base=False)),
    'accumulator-alloca': ('accumulators', accumulator(extra='  %slot = alloca i64\n')),
    'accumulator-external': ('accumulators', accumulator(linkage='')),
}

# What the C++ passes did with each case: count, definitions, calls, overflow checks and
# conditional branches.
EXPECTED = {
    'inline-binary-darwin': (1, 2, 5, 0, 3),
    'inline-binary-linux': (1, 2, 5, 0, 3),
    'inline-binary-x86': (0, 2, 3, 0, 1),
    'inline-debug-module': (0, 2, 3, 0, 1),
    'inline-linear-one-entry': (1, 2, 2, 0, 16),
    'inline-linear-two-entries': (1, 3, 3, 0, 24),
    'inline-linear-three-entries': (1, 4, 4, 0, 8),
    'inline-literal': (1, 4, 6, 0, 2),
    'inline-zero-helper': (0, 2, 2, 0, 2),
    'inline-accumulator-bounded': (1, 1, 0, 0, 3),
    'inline-accumulator-wide': (1, 1, 0, 0, 1),
    'inline-accumulator-unbounded': (1, 1, 6, 5, 10),
    'inline-accumulator-unbounded-step': (1, 1, 1, 1, 4),
    'inline-accumulator-unsigned': (1, 1, 0, 0, 1),
    'candidate-binary': (1, 2, 3, 0, 1),
    'candidate-noinline': (0, 2, 3, 0, 1),
    'candidate-optsize': (0, 2, 3, 0, 1),
    'candidate-sanitizer': (0, 2, 3, 0, 1),
    'candidate-convergent': (0, 2, 3, 0, 1),
    'candidate-may-unwind': (0, 2, 3, 0, 1),
    'candidate-external': (0, 2, 3, 0, 1),
    'candidate-address-taken': (0, 2, 3, 0, 1),
    'candidate-alloca': (0, 2, 3, 0, 1),
    'candidate-external-call': (0, 2, 4, 0, 1),
    'candidate-one-call': (0, 2, 2, 0, 1),
    'candidate-too-large': (0, 2, 3, 0, 1),
    'literals-eligible': (10, 4, 6, 0, 2),
    'literals-different': (0, 4, 5, 0, 1),
    'literals-noinline': (0, 3, 4, 0, 1),
    'literals-optsize': (0, 3, 4, 0, 1),
    'literals-sanitizer': (0, 3, 4, 0, 1),
    'literals-noduplicate': (0, 3, 4, 0, 1),
    'literals-returns-twice': (0, 3, 4, 0, 1),
    'literals-external': (0, 3, 4, 0, 1),
    'zero-eligible': (10, 2, 2, 0, 3),
    'zero-volatile': (10, 2, 2, 0, 3),
    'zero-variant-argument': (0, 2, 2, 0, 2),
    'zero-callee-noinline': (0, 2, 2, 0, 2),
    'zero-callee-sanitizer': (0, 2, 2, 0, 2),
    'zero-caller-sanitizer': (0, 2, 2, 0, 2),
    'zero-callee-returns-twice': (0, 2, 2, 0, 2),
    'bias-eligible': (10, 2, 1, 0, 2),
    'bias-existing-profile': (0, 2, 1, 0, 2),
    'bias-unmarked-callee': (0, 2, 1, 0, 2),
    'bias-caller-sanitizer': (0, 2, 1, 0, 2),
    'bias-linux': (0, 2, 1, 0, 2),
    'accumulator-add': (1, 2, 2, 1, 3),
    'accumulator-sub': (1, 2, 2, 1, 3),
    'accumulator-mul-constant': (1, 2, 2, 1, 3),
    'accumulator-call-first': (1, 2, 2, 1, 3),
    'accumulator-merged-return': (1, 2, 2, 1, 3),
    'accumulator-shared-return': (1, 2, 2, 1, 3),
    'accumulator-result-in-continue': (1, 2, 2, 1, 3),
    'accumulator-guarded': (1, 2, 2, 1, 4),
    'accumulator-unsigned': (1, 2, 2, 1, 3),
    'accumulator-wide': (1, 2, 2, 1, 3),
    'accumulator-changed-invariant': (0, 2, 3, 1, 2),
    'accumulator-two-calls': (0, 2, 4, 1, 2),
    'accumulator-no-base': (0, 2, 3, 1, 1),
    'accumulator-alloca': (0, 2, 3, 1, 2),
    'accumulator-external': (0, 2, 3, 1, 2),
}

PASSES = {'inline': 'recursive-inline', 'candidate': 'recursive-inline-candidates', 'literals': 'recursive-literals',
          'zero': 'recursive-zero-version', 'bias': 'recursive-guard-bias', 'accumulators': 'checked-accumulator-recursion'}


def run_mode(mode, ir):
    """The count and module of MODE over IR. `inline` gets a generic target machine;
    `literals`, `zero` and `bias` run twice, counting `first * 10 + second`."""
    if mode == 'inline':
        return run_pass_with_target(PASSES[mode], ir, 'generic', None)
    count, module = run_pass(PASSES[mode], ir)
    if mode not in ('literals', 'zero', 'bias'):
        return count, module
    second, module = run_pass(PASSES[mode], module)
    return count * 10 + second, module
