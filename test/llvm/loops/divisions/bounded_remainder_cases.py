"""IR shapes for the AArch64 bounded remainder fold, shared by its test.

`recurrence` is a loop whose two remainders by 97 each feed the other's header phi,
with a range-checked load added in; `guarded` takes a remainder of a load a dominating
branch bounds; `sum` and `nested` bound a dividend through an add or an inner remainder;
`mersenne` multiplies two remainders by `2^k - 1`; `validated` checks a loaded divisor
through `select other, true, (divisor + offset) > limit` before a checked remainder by
it. Each case maps to the rewrite count the C++ pass reported for the same input.
"""
MAC = 'arm64-apple-macosx14.0.0'
X86 = 'x86_64-apple-macosx14.0.0'


def module(body, triple=MAC):
    return f'target triple = "{triple}"\ndeclare void @use(i64)\n{body}'


RECURRENCE = """define i64 @recurrence(ptr %data, i64 %length) {
entry:
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %invalid, label %loop

loop:
  %index = phi i64 [ 0, %entry ], [ %next, %step ]
  %a = phi i64 [ 1, %entry ], [ %a.rem, %step ]
  %b = phi i64 [ 0, %entry ], [ %b.rem, %step ]
  %ptr = getelementptr i64, ptr %data, i64 %index
  %value = load i64, ptr %ptr
  %bad = icmp ugt i64 %value, 96
  br i1 %bad, label %invalid, label %step

step:
  %a.sum = add i64 %a, %value
  %a.rem = srem i64 %a.sum, 97
  %b.sum = add i64 %b, %a.rem
  %b.rem = srem i64 %b.sum, 97
  %next = add i64 %index, 1
  %done = icmp eq i64 %next, %length
  br i1 %done, label %exit, label %loop

exit:
  ret i64 %b.rem

invalid:
  ret i64 -1
}
"""


def guarded(predicate='ult', limit=14, modulus=7, opcode='urem', integer='i64', bypass=False, merge=False, metadata='', dividend='%value'):
    accepted, rejected = ('%bad', '%ok') if bypass else ('%ok', '%bad')
    join = 'ok:\n  br label %join\njoin:\n' if merge else 'ok:\n'
    entry_target = f'br i1 %in.range, label {accepted}, label {rejected}'
    return module(f'''define {integer} @f(ptr %p) {{
entry:
  %value = load {integer}, ptr %p
  %in.range = icmp {predicate} {integer} %value, {limit}
  {entry_target}
{join}  %r = {opcode} {integer} {dividend}, {modulus}{metadata}
  ret {integer} %r
bad:
  ret {integer} 0
}}
{"!0 = !{}" if metadata else ""}
''')


def two_loads(left_limit, right_limit, combine='add', modulus=7, integer='i64', outer='urem'):
    return module(f'''define {integer} @f(ptr %p, ptr %q) {{
entry:
  %left = load {integer}, ptr %p
  %right = load {integer}, ptr %q
  %left.ok = icmp ule {integer} %left, {left_limit}
  br i1 %left.ok, label %next, label %bad
next:
  %right.ok = icmp ule {integer} %right, {right_limit}
  br i1 %right.ok, label %ok, label %bad
ok:
  %combined = {combine} {integer} %left, %right
  %r = {outer} {integer} %combined, {modulus}
  ret {integer} %r
bad:
  ret {integer} 0
}}
''')


def nested(inner='urem', inner_modulus=5, outer_modulus=7, guarded_inner=True, inner_limit=100):
    guard = f'  %ok = icmp ult i64 %value, {inner_limit}\n  br i1 %ok, label %body, label %bad\nbody:\n' if guarded_inner else '  br label %body\nbody:\n'
    return module(f'''define i64 @f(ptr %p) {{
entry:
  %value = load i64, ptr %p
{guard}  %inner = {inner} i64 %value, {inner_modulus}
  %outer = urem i64 %inner, {outer_modulus}
  ret i64 %outer
bad:
  ret i64 0
}}
''')


def mersenne(shift=20, integer='i64', modulus=None, left_modulus=None, opcode='urem'):
    modulus = modulus if modulus is not None else (1 << shift) - 1
    left_modulus = left_modulus if left_modulus is not None else modulus
    return module(f'''define {integer} @f({integer} %a, {integer} %b) {{
entry:
  %left = urem {integer} %a, {left_modulus}
  %right = urem {integer} %b, {modulus}
  %product = mul {integer} %left, %right
  %r = {opcode} {integer} %product, {modulus}
  ret {integer} %r
}}
''')


def validated(offset=-1, limit=63, extent=64, reject='true', other_block=False, shared_accept=False, swapped=False, predicate='ugt'):
    divisor_block = 'entry:\n  %divisor = load i64, ptr %p\n  br label %check\ncheck:\n' if other_block else 'entry:\n  br label %check\ncheck:\n  %divisor = load i64, ptr %p\n'
    targets = 'label %accept, label %reject' if swapped else 'label %reject, label %accept'
    rejected_exit = '  br i1 %other, label %accept, label %bail\nbail:\n  ret i64 0\n' if shared_accept else '  ret i64 0\n'
    return module(f'''define i64 @f(ptr %p, i64 %x, i1 %other) {{
{divisor_block}  %adjusted = add i64 %divisor, {offset}
  %too.large = icmp {predicate} i64 %adjusted, {limit}
  %rejected = select i1 %other, i1 {reject}, i1 %too.large
  br i1 %rejected, {targets}
accept:
  %r = urem i64 %x, %divisor
  %r.ok = icmp ult i64 %r, {extent}
  br i1 %r.ok, label %done, label %reject
done:
  ret i64 %r
reject:
{rejected_exit}}}
''')


def many_candidates(count):
    remainders = ''.join(f'  %r{index} = urem i64 %value, {7 + 2 * index}\n  call void @use(i64 %r{index})\n' for index in range(count))
    return module(f'''define void @f(ptr %p) {{
entry:
  %value = load i64, ptr %p
  %in.range = icmp ult i64 %value, 14
  br i1 %in.range, label %ok, label %bad
ok:
{remainders}  ret void
bad:
  ret void
}}
''')


def large_function(padding):
    filler = ''.join(f'  %pad{index} = add i64 %value, {index}\n' for index in range(padding))
    return module(f'''define i64 @f(ptr %p) {{
entry:
  %value = load i64, ptr %p
  %in.range = icmp ult i64 %value, 14
  br i1 %in.range, label %ok, label %bad
ok:
{filler}  %r = urem i64 %value, 7
  ret i64 %r
bad:
  ret i64 0
}}
''')


CASES = {
    'recurrence': (module(RECURRENCE), 2),
    'recurrence-unsigned': (module(RECURRENCE.replace('srem', 'urem')), 2),
    'recurrence-mixed': (module(RECURRENCE.replace('%b.rem = srem', '%b.rem = urem')), 2),
    'recurrence-unknown-sign': (module(RECURRENCE.replace('icmp ugt', 'icmp sgt')), 0),
    'recurrence-undefined-seed': (module(RECURRENCE.replace('[ 1, %entry ]', '[ undef, %entry ]')), 0),
    'recurrence-negative-seed': (module(RECURRENCE.replace('[ 1, %entry ]', '[ -1, %entry ]')), 0),
    'recurrence-wide-dividend': (module(RECURRENCE.replace('%value, 96', '%value, 98')), 1),
    'recurrence-guard-bypass': (module(RECURRENCE.replace('label %invalid, label %step', 'label %step, label %invalid')), 0),
    'recurrence-x86': (module(RECURRENCE, X86), 0),
    'recurrence-optsize': (module(RECURRENCE.replace('i64 %length) {', 'i64 %length) optsize {')), 0),
    'guarded': (guarded(), 1),
    'guarded-signed-remainder': (guarded(opcode='srem'), 1),
    'guarded-ule': (guarded(predicate='ule', limit=13), 1),
    'guarded-at-limit': (guarded(limit=15), 0),
    'guarded-ule-at-limit': (guarded(predicate='ule', limit=14), 0),
    'guarded-zero-limit': (guarded(limit=0), 0),
    'guarded-signed-predicate': (guarded(predicate='slt'), 0),
    'guarded-negative-limit': (guarded(predicate='ult', limit=-2), 0),
    'guarded-bypass': (guarded(bypass=True), 0),
    'guarded-inverse-edge': (guarded(predicate='uge', limit=14, bypass=True), 1),
    'guarded-merge': (guarded(merge=True), 1),
    'guarded-i32': (guarded(integer='i32'), 1),
    'guarded-i128': (guarded(integer='i128'), 0),
    'guarded-power-of-two': (guarded(modulus=8, limit=16), 0),
    'guarded-modulus-one': (guarded(modulus=1, limit=2), 0),
    'guarded-negative-modulus': (guarded(opcode='srem', modulus=-7), 0),
    'guarded-metadata': (guarded(metadata=', !unknown !0'), 0),
    'guarded-constant': (guarded(dividend='5'), 1),
    'guarded-large-constant': (guarded(dividend='20'), 0),
    'sum': (two_loads(3, 3), 1),
    'sum-at-limit': (two_loads(7, 7), 0),
    'sum-signed-overflow': (two_loads(100, 100, integer='i8', modulus=101), 0),
    'sum-just-fits': (two_loads(63, 64, integer='i8', modulus=101), 1),
    'product-without-mersenne': (two_loads(3, 3, combine='mul'), 0),
    'nested': (nested(), 1),
    'nested-both': (nested(inner_limit=10), 2),
    'nested-signed-inner': (nested(inner='srem'), 1),
    'nested-both-signed': (nested(inner='srem', inner_limit=10), 2),
    'nested-unguarded': (nested(guarded_inner=False), 0),
    'nested-large-inner': (nested(inner_modulus=15), 0),
    'mersenne': (mersenne(), 1),
    'mersenne-17': (mersenne(shift=17), 1),
    'mersenne-31': (mersenne(shift=31), 1),
    'mersenne-16': (mersenne(shift=16), 0),
    'mersenne-32': (mersenne(shift=32), 0),
    'mersenne-not-mask': (mersenne(modulus=(1 << 20) + 1), 0),
    'mersenne-i32': (mersenne(shift=20, integer='i32'), 0),
    'mersenne-signed': (mersenne(opcode='srem'), 0),
    'mersenne-wider-factor': (mersenne(left_modulus=(1 << 21) - 1), 0),
    'validated': (validated(), 1),
    'validated-short-extent': (validated(extent=63), 0),
    'validated-false-reject': (validated(reject='false'), 0),
    'validated-other-block': (validated(other_block=True), 0),
    'validated-shared-accept': (validated(shared_accept=True), 0),
    'validated-swapped': (validated(swapped=True), 0),
    'validated-full-range': (validated(predicate='ult', limit=0, offset=0), 0),
    'many-candidates': (many_candidates(64), 64),
    'too-many-candidates': (many_candidates(65), 0),
    'large-function': (large_function(1990), 1),
    'too-large-function': (large_function(1996), 0),
}
