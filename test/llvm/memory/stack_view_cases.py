"""IR shapes for the AArch64 stack-view helper rewrite, shared by its test.

A helper takes two `{ptr, i64}` views and an `i1` flag; each caller builds the views over
two small stack arrays. `inline_module` makes the helper inlinable (internal, `nounwind
norecurse`, 40 to 360 instructions, two to four direct calls); `disjoint_module` marks it
`noinline`, so the rewrite assumes the two arrays' storage separate instead. Each case
maps to what the C++ pass did with the same input: inlined at least one call, assumed
the storage separate (a helper the inliner rejects may still qualify), or left it
unchanged.
"""
MAC = 'arm64-apple-macosx14.0.0'
X86 = 'x86_64-apple-macosx14.0.0'
VIEW = '{ ptr, i64 }'


def helper_body(stages, element='i32'):
    add = 'fadd' if element in ('double', 'float', 'half') else 'add'
    lines = ['  %left = extractvalue { ptr, i64 } %a, 0', '  %right = extractvalue { ptr, i64 } %b, 0']
    for index in range(stages):
        lines += [
            f'  %left.slot{index} = getelementptr inbounds {element}, ptr %left, i64 {index}',
            f'  %right.slot{index} = getelementptr inbounds {element}, ptr %right, i64 {index}',
            f'  %left.value{index} = load {element}, ptr %left.slot{index}',
            f'  %right.value{index} = load {element}, ptr %right.slot{index}',
            f'  %sum{index} = select i1 true, ptr %left.value{index}, ptr %right.value{index}' if element == 'ptr' else f'  %sum{index} = {add} {element} %left.value{index}, %right.value{index}',
            f'  %chosen{index} = select i1 %flag, {element} %sum{index}, {element} %left.value{index}',
            f'  store {element} %chosen{index}, ptr %left.slot{index}',
        ]
    return '\n'.join(lines)


def helper(stages=6, linkage='internal', attributes='nounwind norecurse', element='i32', extra_parameters='', returns='void'):
    result = '  ret void' if returns == 'void' else '  ret i32 0'
    return f'''define {linkage} {returns} @helper({VIEW} %a, {VIEW} %b, i1 %flag{extra_parameters}) #0 {{
entry:
{helper_body(stages, element)}
{result}
}}
attributes #0 = {{ {attributes} }}
'''


def view(name, storage, length):
    return (f'  %{name}.partial = insertvalue {VIEW} poison, ptr {storage}, 0\n'
            f'  %{name} = insertvalue {VIEW} %{name}.partial, i64 {length}, 1\n')


ELEMENT_VALUES = {'double': '1.0', 'float': '1.0', 'half': '1.0', 'ptr': 'null'}


def caller(index, element='i32', first_elements=8, second_elements=8, length=8, flag='i1 true', same_array=False, second_storage=None,
           call_attributes='', bundle='', extra_arguments='', array_size='', first_data=None, attributes='', padding=0, returns='void'):
    first_type = f'[{first_elements} x {element}]'
    second_type = f'[{second_elements} x {element}]'
    lines = [f'  %first = alloca {first_type}{array_size}, align 16', f'  %second = alloca {second_type}, align 16']
    lines.append(f'  store {element} {ELEMENT_VALUES.get(element, "1")}, ptr %first')
    lines.append(f'  store {element} {ELEMENT_VALUES.get(element, "2")}, ptr %second')
    for pad in range(padding):
        lines.append(f'  %pad{pad} = add i64 %count, {pad}')
    data = first_data or '%first'
    if first_data and first_data.startswith('%first.offset'):
        lines.append(f'  %first.offset = getelementptr inbounds {first_type}, ptr %first, i64 0, i64 0')
    text = '\n'.join(lines) + '\n' + view('first.view', data, length)
    text += view('second.view', '%first' if same_array else (second_storage or '%second'), length)
    call_result = '' if returns == 'void' else '%unused = '
    text += f'  {call_result}call {returns} @helper({VIEW} %first.view, {VIEW} %second.view, {flag}{extra_arguments}){call_attributes}{bundle}\n'
    text += f'  %result = load {element}, ptr %first\n  ret {element} %result\n'
    return f'define {element} @caller{index}(i64 %count, ptr %outside, i1 %variable) {attributes} {{\nentry:\n{text}}}\n'


def inline_module(calls=2, triple=MAC, helper_text=None, caller_options=None, prefix=''):
    caller_options = caller_options or {}
    callers = ''.join(caller(index, **caller_options.get(index, caller_options.get('all', {}))) for index in range(calls))
    return f'target triple = "{triple}"\n{prefix}{helper_text or helper()}{callers}'


def disjoint_module(calls=2, helper_options=None, caller_options=None, prefix=''):
    options = {'attributes': 'nounwind norecurse noinline'}
    options.update(helper_options or {})
    return inline_module(calls, helper_text=helper(**options), caller_options=caller_options, prefix=prefix)


def every(options):
    return {'all': options}


MANY_DECLARATIONS = ''.join(f'declare void @external{index}()\n' for index in range(511))
SIZE_ONLY = 'attributes #1 = { optsize }\n'

CASES = {
    'inline': (inline_module(), 'inlined'),
    'inline-three-calls': (inline_module(calls=3), 'inlined'),
    'inline-four-calls': (inline_module(calls=4), 'inlined'),
    'inline-five-calls': (inline_module(calls=5), 'unchanged'),
    'inline-one-call': (inline_module(calls=1), 'unchanged'),
    'inline-x86': (inline_module(triple=X86), 'unchanged'),
    'inline-many-functions': (inline_module(prefix=MANY_DECLARATIONS), 'unchanged'),
    'inline-just-under-function-limit': (inline_module(prefix=MANY_DECLARATIONS[:MANY_DECLARATIONS.index('declare void @external509')]), 'inlined'),
    'inline-same-array': (inline_module(caller_options=every({'same_array': True})), 'unchanged'),
    'inline-one-same-array': (inline_module(caller_options={0: {'same_array': True}}), 'inlined'),
    'inline-zero-length': (inline_module(caller_options=every({'length': 0})), 'unchanged'),
    'inline-length-32': (inline_module(caller_options=every({'length': 32, 'first_elements': 32, 'second_elements': 32})), 'inlined'),
    'inline-length-33': (inline_module(caller_options=every({'length': 33, 'first_elements': 32, 'second_elements': 32})), 'unchanged'),
    'inline-array-33': (inline_module(caller_options=every({'first_elements': 33})), 'unchanged'),
    'inline-length-over-array': (inline_module(caller_options=every({'length': 16})), 'inlined'),
    'inline-double': (inline_module(helper_text=helper(element='double'), caller_options=every({'element': 'double'})), 'inlined'),
    'inline-pointer-elements': (inline_module(helper_text=helper(element='ptr'), caller_options=every({'element': 'ptr'})), 'unchanged'),
    'inline-variable-flag': (inline_module(caller_options=every({'flag': 'i1 %variable'})), 'unchanged'),
    'inline-byte-flag': (inline_module(helper_text=helper().replace('select i1 %flag', 'select i1 true').replace('i1 %flag', 'i8 %flag'), caller_options=every({'flag': 'i8 1'})), 'unchanged'),
    'inline-outside-pointer': (inline_module(caller_options=every({'second_storage': '%outside'})), 'unchanged'),
    'inline-array-allocation': (inline_module(caller_options=every({'array_size': ', i32 2'})), 'unchanged'),
    'inline-offset-data': (inline_module(caller_options=every({'first_data': '%first.offset'})), 'inlined'),
    'inline-external-helper': (inline_module(helper_text=helper(linkage='')), 'unchanged'),
    'inline-private-helper': (inline_module(helper_text=helper(linkage='private')), 'inlined'),
    'inline-throwing-helper': (inline_module(helper_text=helper(attributes='norecurse')), 'assumed'),
    'inline-recursive-helper': (inline_module(helper_text=helper(attributes='nounwind')), 'assumed'),
    'inline-convergent-helper': (inline_module(helper_text=helper(attributes='nounwind norecurse convergent')), 'assumed'),
    'inline-noduplicate-helper': (inline_module(helper_text=helper(attributes='nounwind norecurse noduplicate')), 'assumed'),
    'inline-optsize-helper': (inline_module(helper_text=helper(attributes='nounwind norecurse optsize')), 'unchanged'),
    'inline-small-helper': (inline_module(helper_text=helper(stages=4)), 'assumed'),
    'inline-smallest-helper': (inline_module(helper_text=helper(stages=6)), 'inlined'),
    'inline-large-helper': (inline_module(helper_text=helper(stages=52)), 'assumed'),
    'inline-largest-helper': (inline_module(helper_text=helper(stages=51)), 'inlined'),
    'inline-budget': (inline_module(calls=4, helper_text=helper(stages=50)), 'inlined'),
    'inline-six-parameters': (inline_module(helper_text=helper(extra_parameters=', i32 %c, i32 %d, i32 %e'), caller_options=every({'extra_arguments': ', i32 3, i32 4, i32 5'})), 'inlined'),
    'inline-seven-parameters': (inline_module(helper_text=helper(extra_parameters=', i32 %c, i32 %d, i32 %e, i32 %f'), caller_options=every({'extra_arguments': ', i32 3, i32 4, i32 5, i32 6'})), 'unchanged'),
    'inline-variable-argument': (inline_module(helper_text=helper(extra_parameters=', i64 %c'), caller_options=every({'extra_arguments': ', i64 %count'})), 'unchanged'),
    'inline-returning-helper': (inline_module(helper_text=helper(returns='i32'), caller_options=every({'returns': 'i32'})), 'unchanged'),
    'inline-noinline-call': (inline_module(caller_options=every({'call_attributes': ' #2'}), prefix='attributes #2 = { noinline }\n'), 'assumed'),
    'inline-one-noinline-call': (inline_module(caller_options={0: {'call_attributes': ' #2'}}, prefix='attributes #2 = { noinline }\n'), 'inlined'),
    'inline-bundle-call': (inline_module(caller_options=every({'bundle': ' [ "unknown"() ]'})), 'assumed'),
    'inline-optsize-caller': (inline_module(caller_options=every({'attributes': '#1'}), prefix=SIZE_ONLY), 'assumed'),
    'inline-large-caller': (inline_module(caller_options={0: {'padding': 1190}}), 'inlined'),
    'inline-largest-caller': (inline_module(caller_options={0: {'padding': 1189}}), 'inlined'),
    'disjoint': (disjoint_module(), 'assumed'),
    'disjoint-four-calls': (disjoint_module(calls=4), 'assumed'),
    'disjoint-five-calls': (disjoint_module(calls=5), 'unchanged'),
    'disjoint-one-call': (disjoint_module(calls=1), 'unchanged'),
    'disjoint-marked': (disjoint_module(helper_options={'attributes': 'nounwind norecurse noinline "elisa.disjoint-stack-views"'}), 'unchanged'),
    'disjoint-offset-data': (disjoint_module(caller_options=every({'first_data': '%first.offset'})), 'unchanged'),
    'disjoint-length-over-array': (disjoint_module(caller_options=every({'length': 16})), 'unchanged'),
    'disjoint-same-array': (disjoint_module(caller_options=every({'same_array': True})), 'unchanged'),
    'disjoint-external': (disjoint_module(helper_options={'linkage': ''}), 'unchanged'),
    'disjoint-four-parameters': (disjoint_module(helper_options={'extra_parameters': ', i32 %c'}, caller_options=every({'extra_arguments': ', i32 3'})), 'unchanged'),
    'disjoint-returning': (disjoint_module(helper_options={'returns': 'i32'}, caller_options=every({'returns': 'i32'})), 'unchanged'),
    'disjoint-address-taken': (disjoint_module(prefix='@table = global ptr @helper\n'), 'unchanged'),
    'disjoint-throwing': (disjoint_module(helper_options={'attributes': 'noinline'}), 'assumed'),
    'disjoint-optsize': (disjoint_module(helper_options={'attributes': 'noinline optsize'}), 'unchanged'),
}
# Calls of the helper left after a rewrite that inlined only some of them.
REMAINING_CALLS = {'inline-budget': 1, 'inline-large-caller': 1, 'inline-one-noinline-call': 1, 'inline-one-same-array': 1}
# Cases a second run changes again: the cleanup after the assumption shrinks the helper
# below the inlining limit.
CAPPED = {'inline-large-helper'}
