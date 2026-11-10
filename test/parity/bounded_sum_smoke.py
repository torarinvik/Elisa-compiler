#!/usr/bin/env python3
"""Qualify bounded-sum overflow proofs with independent linked results."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

def run(args):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=29)
    if p.returncode:
        raise RuntimeError(f'{args}: {p.returncode}\n{p.stderr}')
    return p

def main():
    config = os.environ.get('LLVM_CONFIG') or shutil.which('llvm-config')
    if not config:
        config = next((str(p) for p in [Path('/opt/homebrew/opt/llvm/bin/llvm-config'), Path('/usr/lib/llvm-23/bin/llvm-config')] if p.is_file()), None)
    if not config:
        raise RuntimeError('LLVM_CONFIG is required')
    if int(run([config, '--version']).stdout.split('.')[0]) < 23:
        print('bounded sum: requires LLVM 23; skipped')
        return
    bindir = Path(run([config, '--bindir']).stdout.strip())
    flags = shlex.split(run([config, '--cxxflags']).stdout)
    links = shlex.split(run([config, '--ldflags', '--libs', '--system-libs']).stdout)
    libdir = run([config, '--libdir']).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='elisa-sum-proof-') as tmp:
        work = Path(tmp)
        driver = work / 'driver.cpp'
        driver.write_text('#include ' + json.dumps(str(ROOT / 'src/backend/llvm_bounded_sum.cpp')) + r'''
#include <llvm/IRReader/IRReader.h>
#include <llvm/IR/Verifier.h>
#include <llvm/Support/SourceMgr.h>
int main(int argc,char **argv){using namespace llvm;if(argc!=2)return 2;
 LLVMContext C;SMDiagnostic E;auto M=parseIRFile(argv[1],E,C);if(!M){E.print(argv[0],errs());return 2;}
 if(verifyModule(*M,&errs()))return 2;
 elisacoreBoundedCheckedSums(wrap(M.get()));
 if(verifyModule(*M,&errs()))return 2;M->print(outs(),nullptr);return 0;
}
''')
        transform = work / 'transform'
        run([bindir/'clang++', *flags, '-O2', driver, *links, '-Wl,-rpath,'+libdir, '-o', transform])
        fixture = ROOT/'test/parity/bounded_sum_fixture.ll'
        changed = work/'changed.ll'
        changed.write_text(run([transform, fixture]).stdout)
        text = changed.read_text()
        def body(name):
            return text.split('@'+name+'(',1)[1].split('\n}',1)[0]
        for name in ['safe_checked', 'safe_clamped']:
            if 'call { i8, i1 } @llvm.sadd.with.overflow' in body(name):
                raise RuntimeError(name + ': safe checked sum was not proved')
        if 'add nuw nsw i8 %sum, %step' not in body('safe_plain'):
            raise RuntimeError('safe wrapping sum was not proved')
        for name in ['unsafe_m33','nonzero_seed127','header_update_before_exit','header_update_observable_flag']:
            if 'call { i8, i1 } @llvm.sadd.with.overflow' not in body(name):
                raise RuntimeError(name+': unproved overflow removed')
        if run([transform, changed]).stdout.splitlines()[1:] != text.splitlines()[1:]:
            raise RuntimeError('proof is not idempotent')
        original = fixture.read_text()
        negative_cap = work/'negative-cap.ll'
        negative_cap.write_text(original.replace(
            '@llvm.smin.i8(i8 %value, i8 %cap)', '@llvm.smin.i8(i8 %value, i8 -1)'))
        result = run([transform, negative_cap]).stdout.split('@safe_clamped(', 1)[1]
        if 'call { i8, i1 } @llvm.sadd.with.overflow' not in result.split('\n}', 1)[0]:
            raise RuntimeError('negative cap: unproved unsigned bound')
        for label, operand in [('zero-step', '0'), ('undef-step', 'undef')]:
            control=work/(label+'.ll')
            control.write_text(original.replace('i8 %sum, i8 %step)', 'i8 %sum, i8 '+operand+')'))
            result=run([transform,control]).stdout.split('@safe_checked(',1)[1].split('\n}',1)[0]
            has_check='call { i8, i1 } @llvm.sadd.with.overflow' in result
            if has_check != (operand == 'undef'):
                raise RuntimeError(label+': incorrect definedness handling')
        for label, attribute in [('sanitize','sanitize_address'), ('optnone','optnone noinline'), ('size','optsize')]:
            control=work/(label+'.ll')
            control.write_text(original.replace('ptr noundef %data) {','ptr noundef %data) '+attribute+' {'))
            result=run([transform,control]).stdout.split('@safe_checked(',1)[1].split('\n}',1)[0]
            if 'call { i8, i1 } @llvm.sadd.with.overflow' not in result:
                raise RuntimeError(label+': unsupported function transformed')
        libs=[]
        for label, source in [('baseline',fixture), ('candidate',changed)]:
            lib=work/(label+'.so')
            run([bindir/'clang','-O3','-shared','-fPIC',source,'-o',lib])
            libs.append(lib)
        harness=work/'check'
        extra=['-ldl'] if 'linux' in run([config,'--host-target']).stdout else []
        run([bindir/'clang','-O2',ROOT/'test/parity/bounded_sum_harness.c',*extra,'-o',harness])
        print(run([harness,*libs]).stdout.strip())
    print('bounded sum: proof, exclusions, idempotence and linked overflow parity passed')

if __name__=='__main__':main()
