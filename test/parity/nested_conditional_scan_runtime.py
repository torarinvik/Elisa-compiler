#!/usr/bin/env python3
"""Check a Stage1 product's nested conditional scan against an independent C loop."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', required=True, type=Path)
    parser.add_argument('--cc', default='clang')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    fixtures = root / 'test/bench/codegen_perf'
    cc = shutil.which(args.cc)
    if cc is None:
        parser.error('C compiler unavailable')
    with tempfile.TemporaryDirectory(prefix='nested-scan-check-') as directory:
        obj = Path(directory) / 'scan.o'
        binary = Path(directory) / 'check'
        subprocess.run([str(args.compiler.resolve()), '-O3', '-emit', 'obj', '-o', str(obj),
                        str(fixtures / 'nested_conditional_scan.elisa')], check=True, timeout=29)
        subprocess.run([cc, '-O2', str(fixtures / 'nested_conditional_scan_check.c'),
                        str(obj), '-o', str(binary)], check=True, timeout=29)
        subprocess.run([str(binary)], check=True, timeout=29)
    print('passed 1224 nested-scan runtime cases')


if __name__ == '__main__':
    main()
