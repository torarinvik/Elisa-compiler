#!/usr/bin/env python3
"""Compare a native checker to captured source/output/status cases and full rounds.

This checks behavioral equivalence to the supplied baseline, including its known
limitations. It does not turn those limitations into semantic correctness claims.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checker', type=Path)
    parser.add_argument('snapshot', type=Path)
    args = parser.parse_args()
    checker = str(args.checker.resolve())
    cases = json.loads(args.snapshot.read_text())
    if not cases:
        raise SystemExit('Snapshot contains no cases')
    environment = dict(os.environ)
    environment.pop('ELISA_STAGE1_TIMINGS', None)
    environment.pop('ELISA_AUTHORITY_FULL_SUMMARIES', None)
    failures = []
    for case in cases:
        expected = (case['status'], case['stdout'], case['stderr'])
        for mode, env in (('dependency', environment), ('full', dict(environment, ELISA_AUTHORITY_FULL_SUMMARIES='1'))):
            try:
                result = subprocess.run([checker], input=case['source'], text=True, capture_output=True, timeout=30, env=env)
            except subprocess.TimeoutExpired:
                failures.append(f"{case['name']} ({mode}): timed out after 30 seconds")
                continue
            actual = result.returncode, result.stdout, result.stderr
            if actual != expected:
                failures.append(f"{case['name']} ({mode}): expected status/output {expected!r}; got {actual!r}")
    if failures:
        raise SystemExit('\n'.join(failures))
    print(f'Native checker snapshot: {len(cases)} cases match exactly in dependency and full modes')


if __name__ == '__main__':
    main()
