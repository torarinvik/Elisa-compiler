#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"
export RPT
python3 - <<'PY'
import os, subprocess
flags = ['ELISA_TARGET_OS_MACOS', 'ELISA_TARGET_OS_LINUX', 'ELISA_TARGET_OS_WINDOWS',
         'ELISA_TARGET_OS_FREEBSD', 'ELISA_TARGET_OS_POSIX', 'ELISA_TARGET_OS_WASI',
         'ELISA_TARGET_OS_WASM', 'ELISA_TARGET_ARCH_X86_64', 'ELISA_TARGET_ARCH_ARM64',
         'ELISA_TARGET_ARCH_WASM32', 'ELISA_TARGET_ARCH_WASM64', 'ELISA_TARGET_ARCH_WASM']
source = ''.join(f'static if {flag}:\n    static assert 1 == 2, "{flag}"\n' for flag in flags)
cases = {
    'arm64-apple-darwin': {'MACOS', 'POSIX', 'ARM64'},
    'x86_64-unknown-linux-gnu': {'LINUX', 'POSIX', 'X86_64'},
    'x86_64-pc-windows-msvc': {'WINDOWS', 'X86_64'},
    'aarch64-unknown-freebsd': {'FREEBSD', 'POSIX', 'ARM64'},
    'wasm32-unknown-unknown': {'WASI', 'POSIX', 'WASM', 'WASM32'},
    ' WASM64-unknown-WASI ': {'WASI', 'POSIX', 'WASM', 'WASM64'},
    'riscv64-unknown-none': set(),
}
for triple, expected in cases.items():
    env = os.environ.copy(); env['ELISA_STAGE1_TRIPLE'] = triple
    result = subprocess.run([env['RPT']], input=source, text=True, capture_output=True, env=env, check=True)
    actual = {flag.removeprefix('ELISA_TARGET_OS_').removeprefix('ELISA_TARGET_ARCH_') for flag in flags if 'static assert failed: ' + flag in result.stdout}
    if actual != expected:
        raise SystemExit(f'{triple}: expected {expected}, got {actual}:\n{result.stdout}')
print('semantic target predicate matrix OK')
PY
