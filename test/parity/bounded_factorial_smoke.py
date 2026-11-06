#!/usr/bin/env python3
"""Qualify exact running-product proofs: 20! fits; every overflowing control keeps its trap."""
import json, os, shlex, shutil, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
def run(args, check=True):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=120)
    if check and p.returncode:
        raise RuntimeError(f'{args}: {p.returncode}\n{p.stderr}')
    return p
def main():
    config = os.environ.get('LLVM_CONFIG') or shutil.which('llvm-config') or '/opt/homebrew/opt/llvm/bin/llvm-config'
    if int(run([config, '--version']).stdout.split('.')[0]) < 23:
        print('bounded factorial: requires LLVM 23; skipped'); return
    bindir = Path(run([config, '--bindir']).stdout.strip())
    flags = shlex.split(run([config, '--cxxflags']).stdout)
    links = shlex.split(run([config, '--ldflags', '--libs', '--system-libs']).stdout)
    libdir = run([config, '--libdir']).stdout.strip()
    host = run([config, '--host-target']).stdout.strip()
    fixture = (ROOT / 'test/parity/bounded_factorial_fixture.ll').read_text().replace('aarch64-unknown-linux-gnu', host)
    with tempfile.TemporaryDirectory(prefix='elisa-factorial-proof-') as tmp:
        work = Path(tmp)
        (work / 'driver.cpp').write_text('#include ' + json.dumps(str(ROOT / 'src/backend/llvm_bounded_factorial.cpp')) + r'''
#include <llvm/IRReader/IRReader.h>
#include <llvm/IR/Verifier.h>
#include <llvm/Support/SourceMgr.h>
int main(int argc,char **argv){using namespace llvm;LLVMContext C;SMDiagnostic E;auto M=parseIRFile(argv[1],E,C);
 if(!M||verifyModule(*M,&errs()))return 2;elisacoreBoundedFactorials(wrap(M.get()));
 if(verifyModule(*M,&errs()))return 2;M->print(outs(),nullptr);return 0;}
''')
        transform = work / 'transform'
        run([bindir / 'clang++', *flags, '-O2', work / 'driver.cpp', *links, '-Wl,-rpath,' + libdir, '-o', transform])
        def apply(name, text):
            src = work / (name + '.ll'); src.write_text(text)
            return run([transform, src]).stdout
        checked = lambda t: any('call ' in l and 'smul.with.overflow' in l for l in t.splitlines())
        safe = apply('safe', fixture)
        if checked(safe): raise RuntimeError('20! still has an overflow check')
        controls = {
            'bound-21': fixture.replace('ugt i64 %n, 20', 'ugt i64 %n, 21'),
            'unbounded': fixture.replace('%bad = icmp ugt i64 %n, 20', '%bad = icmp eq i64 %n, -5'),
            'large-start': fixture.replace('[1,%pre], [%low,%ok]', '[4,%pre], [%low,%ok]'),
            'negative-limit-start': fixture.replace('[2,%pre], [%next', '[-30,%pre], [%next'),
            'step-two': fixture.replace('add i64 %c, 1', 'add i64 %c, 2').replace('ugt i64 %n, 20', 'ugt i64 %n, 2000'),
            'non-unit-step': fixture.replace('add i64 %c, 1', 'mul i64 %c, 3'),
            'wrong-direction': fixture.replace('icmp sgt i64 %next, %n', 'icmp slt i64 %next, %n'),
            'other-operands': fixture.replace('i64 %p, i64 %c), !elisa', 'i64 %p, i64 %n), !elisa'),
            'sanitizer': fixture.replace('@fact(i64 %n) {', '@fact(i64 %n) sanitize_address {'),
        }
        for name, text in controls.items():
            if not checked(apply(name, text)):
                raise RuntimeError(name + ': unproved overflow check removed')
        # Results must stay identical to the unoptimized fixture for every input.
        harness = work / 'check.c'
        harness.write_text('#include <stdint.h>\n#include <stdio.h>\nextern int64_t fact(int64_t);\nint main(void){'
            'int64_t want=1;if(fact(21)!=-1||fact(-1)!=-1||fact(0)!=1||fact(1)!=1)return 1;'
            'for(int64_t n=2;n<=20;++n){want*=n;if(fact(n)!=want){printf("%lld\\n",(long long)n);return 1;}}return 0;}\n')
        cand = work / 'candidate.ll'; cand.write_text(safe)
        for label, ir in (('base', work / 'safe.ll'), ('candidate', cand)):
            run([bindir / 'clang', '-O2', '-Wno-override-module', ir, harness, '-o', work / label])
            run([work / label])
        # Division accumulators: both addend forms prove; unproved variants keep the check.
        sums = {name: (ROOT / 'test/parity/bounded_division_sum_fixture.ll').read_text().replace('aarch64-unknown-linux-gnu', host).replace('ADDEND', add) for name, add in (('q', 'q'), ('rem', 'm'))}
        ch = lambda t: any('call ' in l and 'sadd.with.overflow' in l for l in t.splitlines())
        for name, text in sums.items():
            if ch(apply('sum-' + name, text)): raise RuntimeError(name + ': division sum still checked')
        q = sums['q']
        for name, text in {
            'huge-start': q.replace('[0,%pre], [%sn', '[9223372036854775000,%pre], [%sn'),
            'no-input-bound': q.replace('%bad = icmp ugt i64 %n, 1000000000', '%bad = icmp eq i64 %n, -1'),
            'other-addend': q.replace('i64 %s, i64 %q)', 'i64 %s, i64 %n)'),
            'divide-by-one': q.replace('udiv i64 %r, 5', 'udiv i64 %r, 1'),
        }.items():
            if not ch(apply('sum-' + name, text)): raise RuntimeError(name + ': unproved sum check removed')
        h = (ROOT / 'test/parity/bounded_horner_fixture.ll').read_text().replace('aarch64-unknown-linux-gnu', host)
        cm = lambda t: any('call ' in l and 'with.overflow' in l for l in t.splitlines())
        if cm(apply('horner', h)): raise RuntimeError('bounded Horner recurrence still checked')
        for name, text in {
            'count-too-big': h.replace('ugt i64 %n, 12', 'ugt i64 %n, 64'),
            'count-unbounded': h.replace('%bad = icmp ugt i64 %n, 12', '%bad = icmp eq i64 %n, -7'),
            'count-may-be-zero': h.replace('icmp ult i64 %n, 1', 'icmp ult i64 %n, 0'),
            'big-factor': h.replace('i64 %x, i64 26', 'i64 %x, i64 100000000'),
            'addend-unbounded': h.replace('%d_bad = icmp ugt i64 %d, 26', '%d_bad = icmp eq i64 %d, -1'),
            'huge-start': h.replace('[0,%pre], [%xn', '[1000000000000000000,%pre], [%xn'),
        }.items():
            if not cm(apply('horner-' + name, text)): raise RuntimeError(name + ': unproved Horner check removed')
        # General interval simulation: mutually dependent values with a reset.
        g = (ROOT / 'test/parity/bounded_interval_fixture.ll').read_text().replace('aarch64-unknown-linux-gnu', host)
        if cm(apply('interval', g)): raise RuntimeError('bounded interval loop still checked')
        for name, text in {
            'too-many-iterations': g.replace('ugt i64 %n, 15', 'ugt i64 %n, 200'),
            'no-iteration-bound': g.replace('%bad = icmp ugt i64 %n, 15', '%bad = icmp eq i64 %n, -7'),
            'big-sample': g.replace('ugt i64 %d, 8', 'ugt i64 %d, 4611686018427387904'),
            'unchecked-sample': g.replace('%d_bad = icmp ugt i64 %d, 8', '%d_bad = icmp eq i64 %d, -1'),
            'squared-growth': g.replace('i64 %t, i64 3)', 'i64 %t, i64 %t)').replace('[%t,%cmp]', '[%qv,%cmp]').replace('[0,%reset]', '[%qv,%reset]').replace('%s = phi i64 [0,%pre]', '%s = phi i64 [2,%pre]'),
        }.items():
            if not cm(apply('interval-' + name, text)): raise RuntimeError(name + ': unproved interval check removed')
        # Linked behavior: optimized and original agree, and real overflow still traps.
        orig, opt = work / 'orig.ll', work / 'opt.ll'
        orig.write_text(g); opt.write_text(apply('interval2', g))
        check = work / 'g.c'
        check.write_text('#include <stdint.h>\n#include <stdio.h>\nextern int64_t interval(const int64_t*,int64_t);'
            'int main(void){int64_t v[15];uint64_t s=88172645463325252ULL,h=0;for(int r=0;r<20000;r++){int n=(s>>7)%16;'
            'for(int i=0;i<15;i++){s^=s<<13;s^=s>>7;s^=s<<17;v[i]=(int64_t)(s%10);}h=h*31+(uint64_t)interval(v,n);}'
            'printf("%llu\\n",(unsigned long long)h);return 0;}')
        outs = []
        for label, ir in (('orig', orig), ('opt', opt)):
            run([bindir / 'clang', '-O1', '-Wno-override-module', ir, check, '-o', work / label])
            outs.append(run([work / label]).stdout)
        if outs[0] != outs[1]: raise RuntimeError(f'interval results differ: {outs}')
    print(f'bounded factorial: ok ({len(controls)} controls)')
main()
