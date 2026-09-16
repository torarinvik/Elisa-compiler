#!/usr/bin/env bash
# docs/127 §3.6 — the extern audit surface in `-emit unsafe`, and the one property that keeps
# it honest.
#
# The report claims, per extern parameter and return, what OBLIGATION its type forms and what
# EVIDENCE discharges it. Two rows are not evidence: `untyped` (no obligation could be formed)
# and the `bare` header state (no contract and no @trusted at all). Those are exactly what
# `-strict-externs` refuses, so this gate asserts the BICONDITIONAL on every fixture:
#
#     extern-untyped == 0 and extern-bare == 0   <=>   -strict-externs accepts
#
# in BOTH compilers, plus byte-identical sections between them. A report that drifted from the
# gate would be worse than no report — an audit nobody can trust is how "we checked" becomes a
# label — and a biconditional is the only check that catches drift in either direction.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ROOT="$ROOT" python3 - "$STAGE0" "$STAGE1" "$WORK" <<'PY'
from pathlib import Path
import os, re, subprocess, sys
stage0, stage1, work = sys.argv[1:]
work = Path(work); root = Path(os.environ['ROOT'])

def section(text):
    """The extern rows only: everything from the first count line to the end."""
    start = text.find('extern-untyped:')
    assert start >= 0, 'report has no extern audit section'
    return text[start:]

def counts(text):
    untyped = int(re.search(r'^extern-untyped: (\d+)$', text, re.M).group(1))
    bare = int(re.search(r'^extern-bare: (\d+)$', text, re.M).group(1))
    return untyped, bare

# Families chosen so every obligation kind and every evidence tag appears at least once, and so
# both sides of the biconditional are exercised. `clean` is the shape a binding family should
# reach: every row proven or checked, and -strict-externs silent.
FAMILIES = {
    'clean': '''extern resource CFile

def __drop__(self: CFile) -> void:
    _ = fclose(move self)

@callconv(c)
extern fclose(file: CFile) -> i32 ensure result <= 0

@callconv(c)
extern strnlen(text: view[u8]) -> usize ensure result <= text.len

def main() -> i64:
    text: mutable darray[u8] = []
    text.push(0)
    return strnlen(text[0:1]).i64()
''',
    'uncovered_pointer': '''@callconv(c)
extern probe(text: cstr, limit: usize) -> usize ensure result <= limit

def main() -> i64:
    return probe("hi", 8).i64()
''',
    'bare_family': '''@callconv(c)
extern strnlen(text: view[u8]) -> usize

def main() -> i64:
    text: mutable darray[u8] = []
    text.push(0)
    return strnlen(text[0:1]).i64()
''',
    'trusted_family': '''@callconv(c)
@trusted("the platform test suite validates libc strlen")
extern strlen(s: cstr) -> usize

def main() -> i64:
    return strlen("hi").i64() - 2
''',
    # The only family that reaches `owned` (a returned handle the caller must release) and
    # `void`. Every row is `assumed` here, which is what one @trusted per extern buys — and the
    # audit lists each reason, so "what are we trusting?" has one answer in one place.
    'owned_handle': '''extern resource CFile

def __drop__(self: CFile) -> void:
    _ = fclose(move self)

@callconv(c)
@trusted("libc fopen hands back the platform's own file handle")
extern fopen(path: cstr, mode: cstr) -> CFile?

@callconv(c)
@trusted("libc fclose releases the handle it is given")
extern fclose(file: CFile) -> i32

@callconv(c)
@trusted("libc rewind takes the handle and returns nothing")
extern rewind(file: CFile&) -> void

def main() -> i64:
    return 0
''',
    # A binding family normally LIVES in a module, and a top-level-only walk reported
    # `extern-obligations: none` for exactly this shape — the audit silently omitting a whole
    # module's boundary. Rows are namespace-qualified with "." like the `functions:` section.
    'module_family': '''module Net:
    @callconv(c)
    extern send_bytes(buffer: view[u8]) -> i64 ensure result <= buffer.len

def main() -> i64:
    payload: mutable darray[u8] = []
    payload.push(0)
    return Net::send_bytes(payload[0:1])
''',
    'bounds_family': '''@callconv(c)
@bounds(text, cap)
extern strnlen(text: u8&, cap: usize) -> usize ensure result <= text.len

def main() -> i64:
    t: mutable darray[u8] = []
    t.push(0)
    return strnlen(t[0:1]).i64()
''',
}

for name, text in FAMILIES.items():
    src = work / (name + '.elisa'); src.write_text(text)
    sections = []
    for stage, compiler in enumerate((stage0, stage1)):
        report = work / f'{name}.{stage}.txt'
        run = subprocess.run([compiler, '-emit', 'unsafe', '-o', str(report), str(src)],
                             capture_output=True, timeout=60)
        assert run.returncode == 0, (f'stage{stage} could not report on {name}', run.stderr)
        body = section(report.read_text())
        sections.append(body)
        untyped, bare = counts(body)
        strict = subprocess.run([compiler, '-strict-externs', '-emit', 'obj', '-o', str(work / f'{name}.o'), str(src)],
                                capture_output=True, timeout=60)
        # The biconditional, per compiler. Either direction failing means the audit and the
        # gate disagree about the same program, which is the failure this gate exists for.
        clean_report = (untyped == 0 and bare == 0)
        assert clean_report == (strict.returncode == 0), (
            f'{name}: stage{stage} audit says untyped={untyped} bare={bare} '
            f'but -strict-externs returned {strict.returncode}', strict.stderr)
    assert sections[0] == sections[1], (name, sections[0], sections[1])
    untyped, bare = counts(sections[0])
    verdict = 'passes -strict-externs' if (untyped == 0 and bare == 0) else f'untyped={untyped} bare={bare}'
    print(f'{name}: sections byte-identical, audit agrees with the gate ({verdict}) PASS', flush=True)

# Every obligation kind and evidence tag the report can print must be exercised above, or this
# gate would be green while a whole classification arm rotted unmeasured.
seen = set()
for name in FAMILIES:
    for line in section((work / f'{name}.0.txt').read_text()).splitlines():
        row = re.match(r'^    \S+: (\S+) (\S+)$', line)
        if row:
            seen.add(row.group(1)); seen.add(row.group(2))
for wanted in ('handle', 'owned', 'view', 'bounds', 'pointer', 'scalar', 'void',
               'proven', 'checked', 'assumed', 'untyped'):
    assert wanted in seen, f'no fixture exercises the {wanted!r} row; add one'
print('extern_audit: every obligation kind and evidence tag exercised PASS', flush=True)

module_rows = section((work / 'module_family.0.txt').read_text())
assert 'Net.send_bytes' in module_rows, ('a module-nested extern must be reported, '
                                        'namespace-qualified with "."', module_rows)
print('extern_audit: module-nested extern reported as Net.send_bytes PASS', flush=True)
PY
