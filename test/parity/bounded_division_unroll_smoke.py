#!/usr/bin/env python3
"""Check bounded division unrolling, policy exclusions and overflow traps."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], capture_output=True,
                            text=True, timeout=29, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args}: exit {result.returncode}\n{result.stderr}')
    return result


def main():
    config = os.environ.get('LLVM_CONFIG') or shutil.which('llvm-config')
    if not config:
        config = next((str(p) for p in [Path('/opt/homebrew/opt/llvm/bin/llvm-config'),
                      Path('/usr/lib/llvm-23/bin/llvm-config')] if p.is_file()), None)
    if not config:
        raise RuntimeError('LLVM_CONFIG is required')
    if int(run([config, '--version']).stdout.split('.')[0]) < 23:
        print('bounded division unroll: requires LLVM 23; skipped')
        return
    bindir = Path(run([config, '--bindir']).stdout.strip())
    clang, cxx = bindir / 'clang', bindir / 'clang++'
    flags = shlex.split(run([config, '--cxxflags']).stdout)
    links = shlex.split(run([config, '--ldflags', '--libs', '--system-libs']).stdout)
    libdir = run([config, '--libdir']).stdout.strip()
    helper = ROOT / 'src/backend/llvm_bounded_division_unroll.cpp'
    fixture = (ROOT / 'test/parity/bounded_division_unroll_fixture.ll').read_text()
    with tempfile.TemporaryDirectory(prefix='elisa-division-unroll-') as tmp:
        work = Path(tmp)
        driver = work / 'driver.cpp'
        driver.write_text('#include ' + json.dumps(str(helper)) + r'''
#include <llvm/IRReader/IRReader.h>
#include <llvm/IR/LLVMContext.h>
#include <llvm/IR/Verifier.h>
#include <llvm/Support/SourceMgr.h>
int main(int argc,char **argv) {
 using namespace llvm; if(argc!=2)return 2;
 LLVMContext C; SMDiagnostic E; auto M=parseIRFile(argv[1],E,C);
 if(!M){E.print(argv[0],errs());return 2;}
 if(verifyModule(*M,&errs()))return 2;
 errs()<<"changed="<<elisacoreUnrollBoundedDivisionLoops(wrap(M.get()))<<"\n";
 if(verifyModule(*M,&errs()))return 2;
 M->print(outs(),nullptr);return 0;
}
''')
        transform = work / 'transform'
        run([cxx, *flags, '-O2', driver, *links, '-Wl,-rpath,' + libdir,
             '-o', transform])
        source = work / 'base.ll'
        source.write_text(fixture)
        transformed = run([transform, source])
        if 'changed=0' in transformed.stderr:
            raise RuntimeError('bounded checked loop was not transformed')
        changed = work / 'changed.ll'
        changed.write_text(transformed.stdout)
        if 'changed=0' not in run([transform, changed]).stderr:
            raise RuntimeError('second application changed the loop again')
        clean = work / 'clean.ll'
        run([bindir / 'opt', '-passes=function(instcombine,simplifycfg)',
             '-S', changed, '-o', clean])
        controls = {
            'disable': fixture.replace('label %trap, label %head',
                       'label %trap, label %head, !llvm.loop !0') +
                       '\n!0 = distinct !{!0, !1}\n!1 = !{!"llvm.loop.unroll.disable"}\n',
            'signed': fixture.replace('udiv i64', 'sdiv i64'),
            'divisor-one': fixture.replace('udiv i64 %digits, 10', 'udiv i64 %digits, 1')
                          .replace('icmp ult i64 %digits, 10', 'icmp ult i64 %digits, 1'),
            'sanitize': fixture.replace('i64 %offset) {', 'i64 %offset) sanitize_address {'),
            'optnone': fixture.replace('i64 %offset) {', 'i64 %offset) noinline optnone {'),
            'metadata-cycle': fixture.replace('label %trap, label %head',
                       'label %trap, label %head, !llvm.loop !0') +
                       '\n!0 = distinct !{!0, !1}\n!1 = distinct !{!1}\n',
        }
        for name, text in controls.items():
            path = work / (name + '.ll')
            path.write_text(text)
            if 'changed=0' not in run([transform, path]).stderr:
                raise RuntimeError('unsupported loop transformed: ' + name)
        harness = work / 'main.c'
        harness.write_text(r'''
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
extern int64_t count_with_offset(int64_t,int64_t);
static void caught(int n){(void)n;_Exit(77);}
int main(int argc,char **argv){
 if(argc!=3)return 2;signal(SIGILL,caught);signal(SIGTRAP,caught);
 printf("%" PRId64 "\n",count_with_offset(strtoimax(argv[1],0,10),strtoimax(argv[2],0,10)));
 return 0;
}
''')
        maximum, minimum = 2**63 - 1, -(2**63)
        cases = [(1, maximum, 0, str(maximum)), (10, maximum, 77, ''),
                 (100, maximum-1, 77, ''), (99999999, maximum-7, 0, str(maximum)),
                 (99999999, maximum-6, 77, ''), (99, minimum, 0, str(minimum+1)),
                 (0, maximum, 0, '-1'), (135, 0, 0, '2')]
        for name, ir in [('baseline', source), ('candidate', clean)]:
            binary = work / name
            run([clang, ir, harness, '-o', binary])
            for n, offset, code, output in cases:
                result = subprocess.run([str(binary), str(n), str(offset)],
                                        capture_output=True, text=True, timeout=5)
                if (result.returncode, result.stdout.strip()) != (code, output):
                    raise RuntimeError(f'{name}: {n}, {offset}: {result}')
        # Constant counter recurrences qualify only with a defined division seed.
        # Exercise both step signs and the exact endpoints of the overflow proof.
        runtime_checks = len(cases) * 2
        for label, start, step in [('positive', 0, 1), ('negative', 17, -3),
                                   ('maximum-safe', maximum-7, 1),
                                   ('maximum-trap', maximum-6, 1),
                                   ('minimum-safe', minimum+7, -1),
                                   ('minimum-trap', minimum+6, -1)]:
            constant = fixture.replace('i64 %n, i64 %offset', 'i64 noundef %n, i64 %offset')
            constant = constant.replace('[%initial, %entry]',
                                        f'[{{i64 {start}, i1 false}}, %entry]')
            constant = constant.replace('i64 %count, i64 1)', f'i64 %count, i64 {step})')
            original = work / (label + '-original.ll')
            original.write_text(constant)
            changed = work / (label + '-changed.ll')
            result = run([transform, original])
            if '@llvm.assume' not in result.stdout:
                raise RuntimeError(label + ': missing proven division invariant')
            safe_endpoint = minimum <= start + 7 * step <= maximum
            has_checked_add = any('call ' in line and '@llvm.sadd.with.overflow' in line
                                  for line in result.stdout.splitlines())
            if safe_endpoint and has_checked_add:
                raise RuntimeError(label + ': safe counter still checked')
            if not safe_endpoint and 'call void @llvm.trap' not in result.stdout:
                raise RuntimeError(label + ': overflow trap disappeared')
            changed.write_text(result.stdout)
            cleaned = work / (label + '-clean.ll')
            run([bindir / 'opt', '-passes=function(correlated-propagation,instcombine,simplifycfg)',
                 '-S', changed, '-o', cleaned])
            for tag, ir in [('base', original), ('opt', cleaned)]:
                binary = work / (label + '-' + tag)
                run([clang, ir, harness, '-o', binary])
                for n in [0, 1, 10, 999, 10000000, 99999999, 100000000]:
                    expected = -1 if not 1 <= n <= 99999999 else start + (len(str(n))-1)*step
                    code, output = (0, str(expected)) if minimum <= expected <= maximum else (77, '')
                    result = subprocess.run([str(binary), str(n), '0'],
                                            capture_output=True, text=True, timeout=5)
                    if (result.returncode, result.stdout.strip()) != (code, output):
                        raise RuntimeError(f'{label}/{tag}: {n}: {result}')
                    runtime_checks += 1
        for label, text in [('unknown-definedness', constant.replace('i64 noundef %n', 'i64 %n')),
                            ('exact-division', constant.replace('udiv i64', 'udiv exact i64'))]:
            path = work / (label + '.ll')
            path.write_text(text)
            if '@llvm.assume' in run([transform, path]).stdout:
                raise RuntimeError(label + ': unproved invariant introduced')
    print(f'bounded division unroll: 6 policy controls, 2 invariant exclusions and {runtime_checks} runtime/trap checks passed')


if __name__ == '__main__':
    main()
