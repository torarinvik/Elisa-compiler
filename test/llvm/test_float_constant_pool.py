#!/usr/bin/env python3
"""Check the AArch64 float constant pool against its shapes.

On a CPU that fuses literal loads, a small acyclic function loads its expensive doubles
from a private, 8-aligned table when the table pays for its address: a tiny function,
three or more constants in short code, four to eight distinct constants in a small
function, three to eight constants shared by six to twelve uses, a dense block of twelve
or more, a comparison literal with a returned one, or constants that only return phis
take. A returned constant is loaded on its own incoming edge, split from a branching
predecessor. Each expectation is (changes, pooled loads, split edges); the shapes come from
float_constant_pool_cases.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass_with_target
from float_constant_pool_cases import CASES

POOLED = 'private unnamed_addr constant'

EXPECTED = {
    'tiny_select': (1, 1, 0),
    'tiny_select_cheap': (0, 0, 0),
    'tiny_select_float': (0, 0, 0),
    'tiny_select_infinity': (0, 0, 0),
    'tiny_select_nan': (0, 0, 0),
    'tiny_select_denormal': (0, 0, 0),
    'tiny_select_ones': (0, 0, 0),
    'four_products': (1, 4, 0),
    'four_products_linux': (1, 4, 0),
    'four_products_generic': (0, 0, 0),
    'four_products_feature': (1, 4, 0),
    'four_products_x86': (0, 0, 0),
    'four_products_no_target': (0, 0, 0),
    'four_products_target_cpu': (0, 0, 0),
    'four_products_target_features': (0, 0, 0),
    'four_products_optnone': (0, 0, 0),
    'two_products_large': (0, 0, 0),
    'two_products_short': (1, 2, 0),
    'three_products_short_table': (1, 3, 0),
    'three_subtractions_short': (1, 3, 0),
    'three_subtractions_long': (0, 0, 0),
    'three_additions': (0, 0, 0),
    'shared_six': (1, 6, 0),
    'shared_five': (0, 0, 0),
    'shared_thirteen': (0, 0, 0),
    'nine_products': (0, 0, 0),
    'dense_twelve': (1, 12, 0),
    'dense_twenty_four': (1, 24, 0),
    'dense_twenty_five': (0, 0, 0),
    'too_many_instructions': (0, 0, 0),
    'comparison_and_return': (1, 2, 1),
    'comparison_and_return_long': (1, 2, 1),
    'return_edges': (1, 3, 0),
    'return_edges_five': (0, 0, 0),
    'switch_edge': (0, 0, 0),
    'shared_edge': (0, 0, 0),
    'looping': (0, 0, 0),
    'debug_located': (1, 4, 0),
}


def observed(name):
    ir, cpu, features = CASES[name]
    changes, module = run_pass_with_target('float-constant-pool', ir, cpu, features)
    loads = sum(1 for line in module.splitlines() if 'load double' in line and '@elisa.float.constants' in line)
    return (changes, loads, module.count('_crit_edge:')), module


def check(name):
    result, module = observed(name)
    problems = [] if result == EXPECTED[name] else [f'got {result}, expected {EXPECTED[name]}']
    if result[0] and (POOLED not in module or 'align 8' not in module):
        problems.append('the table is not a private, 8-aligned constant')
    if name == 'debug_located' and sum(1 for line in module.splitlines() if 'load double' in line and '!dbg' in line) != 4:
        problems.append('a pooled load lost its debug location')
    return problems


def main():
    failures = 0
    for name in CASES:
        problems = check(name)
        print(('FAIL ' if problems else 'PASS ') + name + (': ' + '; '.join(problems) if problems else ''))
        failures += bool(problems)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
