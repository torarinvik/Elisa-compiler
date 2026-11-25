#!/usr/bin/env python3
"""Check the AArch64 stack-view helper rewrite against its shapes.

A small internal helper called with views over two different stack arrays and a
constant flag is inlined at those calls; a three-parameter helper the inliner rejects,
whose every call passes two separate whole arrays, instead gets an
`llvm.assume [ "separate_storage" ]` of the two data pointers and the
`elisa.disjoint-stack-views` attribute. The expected outcomes are what the C++ pass did
with the same shapes (stack_view_cases.py).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass
from stack_view_cases import CAPPED, CASES, REMAINING_CALLS

PASS = 'stack-view-helpers'
ASSUMPTION = re.compile(r'call void @llvm\.assume\(i1 true\) \[ "separate_storage"\(ptr %\w+, ptr %\w+\) \]')


def helper_calls(module):
    return len(re.findall(r'call \w+ @helper\(', module))


def check_outcome(name, ir, outcome, module):
    if outcome == 'assumed':
        assert ASSUMPTION.search(module) and '"elisa.disjoint-stack-views"' in module, (name, 'no assumption')
        assert helper_calls(module) == helper_calls(ir), (name, 'calls changed')
    elif outcome == 'inlined':
        assert 'separate_storage' not in module, (name, 'unexpected assumption')
        assert helper_calls(module) == REMAINING_CALLS.get(name, 0), (name, 'calls left', helper_calls(module))


def main():
    for name, (ir, outcome) in CASES.items():
        status, module = run_pass(PASS, ir)
        assert status == (0 if outcome == 'unchanged' else 1), (name, status, outcome)
        check_outcome(name, ir, outcome, module)
        if name not in CAPPED:
            again, _ = run_pass(PASS, module)
            assert again == 0, (name, 'not idempotent', again)
        print('PASS', name, flush=True)
    print('stack-view helpers: outcomes and rewritten shapes passed')


if __name__ == '__main__':
    main()
