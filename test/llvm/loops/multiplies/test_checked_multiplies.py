#!/usr/bin/env python3
"""Check the checked-multiply folds (`checked-multiplies`).

Bounded cursors, outer-loop counter squares, counting square roots, constant-trip
initializers and guarded powers lose their checked multiplies; a short power loop is
unrolled; any other in-loop checked multiply guarded by its own flag is versioned onto a
`checkedmul.slow` path. Constant operands, a flag with a second use, debug info and
non-AArch64 targets leave the module alone. Cases: checked_multiply_cases.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass
from checked_multiply_cases import CASES

CHECKED = 'call { i64, i1 } @llvm.smul.with.overflow'

# name: (changes, checked multiplies left, versioned slow paths, other text expected)
EXPECTED = {
    'versioned': (1, 1, True, None),
    'versioned_x86': (0, 1, False, None),
    'versioned_debug_info': (0, 1, False, None),
    'constant_operand': (0, 1, False, None),
    'flag_used_twice': (0, 1, False, None),
    'cursor_sum': (1, 0, False, 'checkedmul.limit'),
    'cursor_sum_noundef': (1, 0, False, 'add nsw'),
    'cursor_unbounded': (1, 1, True, None),
    'outer_square': (1, 0, False, None),
    'outer_square_large': (0, 1, False, None),
    'bounded_root': (1, 0, False, None),
    'bounded_root_large_limit': (1, 1, True, None),
    'bounded_root_signed_greater_equal': (1, 1, True, None),
    'guarded_power': (1, 0, False, None),
    'guarded_power_argument_limit': (1, 0, False, 'checkedpower.limit'),
    'guarded_power_seventeen': (0, 1, False, None),
    'guarded_power_large_base': (0, 1, False, None),
    'short_power': (1, 0, False, None),
    'short_power_nine': (0, 0, False, 'phi i64'),
    'initializer': (1, 0, False, None),
    'initializer_long': (1, 1, True, None),
}

if __name__ == '__main__':
    assert set(EXPECTED) == set(CASES), set(EXPECTED) ^ set(CASES)
    for name, ir in CASES.items():
        changes, checked, versioned, text = EXPECTED[name]
        got, module = run_pass('checked-multiplies', ir)
        assert got == changes, (name, got, module)
        assert module.count(CHECKED) == checked, (name, module)
        assert ('checkedmul.slow:' in module) == versioned, (name, module)
        assert text is None or text in module, (name, text, module)
        print('PASS', name)
