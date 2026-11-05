#!/usr/bin/env python3
"""Check sqrt no-NaN proofs and linked reduction results, including exclusions."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[2]
def run(args):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=28)
    if p.returncode:
        raise RuntimeError(f'{args}: {p.returncode}\n{p.stderr}')
    return p

def main():
    config = os.environ.get('LLVM_CONFIG') or shutil.which('llvm-config')
    if not config:
        config = next((str(p) for p in [Path('/opt/homebrew/opt/llvm/bin/llvm-config'), Path('/usr/lib/llvm-23/bin/llvm-config')] if p.is_file()), None)
    if not config: raise RuntimeError('LLVM_CONFIG required')
    if int(run([config, '--version']).stdout.split('.')[0]) < 23:
        print('sqrt proof requires LLVM 23; skipped'); return
    bindir = Path(run([config, '--bindir']).stdout.strip())
    host = run([config, '--host-target']).stdout.strip()
    flags = shlex.split(run([config, '--cxxflags']).stdout)
    links = shlex.split(run([config, '--ldflags', '--libs', '--system-libs']).stdout)
    libdir = run([config, '--libdir']).stdout.strip()
    fixture = re.sub(r'target triple = "[^"]+"', f'target triple = "{host}"', (ROOT/'test/parity/sqrt_proof_fixture.ll').read_text())
    controls = {
        'nan-seed': fixture.replace('phi double [ 0.000000e+00,', 'phi double [ 0x7FF8000000000000,', 1),
        'negative-square-seed': fixture.replace('%vec.phi13 = phi double [ 0.000000e+00,', '%vec.phi13 = phi double [ -1.000000e+00,').replace('%squared_deviations.0112.i.ph = phi double [ 0.000000e+00,', '%squared_deviations.0112.i.ph = phi double [ -1.000000e+00,'),
        'unknown-fp': re.sub(r'sitofp (<2 x i64>|i64) (%[A-Za-z0-9._]+) to', r'bitcast \1 \2 to', fixture),
        'zero-divisor': fixture.replace('%divtmp75.i = fdiv arcp contract double %addtmp68.i.lcssa, %uitofp.i', '%divtmp75.i = fdiv arcp contract double %addtmp68.i.lcssa, 0.000000e+00'),
        'strict': fixture.replace('attributes #1 = {', 'attributes #1 = { strictfp '),
        'sanitizer': fixture.replace('attributes #1 = {', 'attributes #1 = { sanitize_address '),
        'nobuiltin': fixture.replace('tail call double @sqrt(double %divtmp75.i)', 'tail call double @sqrt(double %divtmp75.i) #3')+'\nattributes #3 = { nobuiltin }\n',
        'wide-int': fixture.replace('%sitofp.i = sitofp i64 %idx42.i to double', '%extend.i = sext i64 %idx42.i to i2048\n %wide.i = shl i2048 %extend.i, 2000\n %sitofp.i = sitofp i2048 %wide.i to double'),
    }
    opposite = f'target triple = "{host}"\n' + r'''
declare double @sqrt(double)
define double @infinite_reduction(i64 %n) {
entry:
 br label %loop
loop:
 %mean = phi double [ 0xFFF0000000000000, %entry ], [ %next, %loop ]
 %i = phi i64 [ 0, %entry ], [ %inc, %loop ]
 %next = fadd double %mean, 0x7FF0000000000000
 %inc = add i64 %i, 1
 %done = icmp eq i64 %inc, %n
 br i1 %done, label %exit, label %loop
exit:
 %dev = fsub double 1.000000e+00, %next
 %square = fmul double %dev, %dev
 %root = call double @sqrt(double %square)
 ret double %root
}
'''
    controls['opposite-infinities'] = opposite
    with tempfile.TemporaryDirectory(prefix='elisa-sqrt-proof-') as tmp:
        q=Path(tmp);driver=q/'driver.cpp'
        driver.write_text('#include '+json.dumps(str(ROOT/'src/backend/llvm_sqrt_proof.cpp'))+r'''
#include <llvm/IRReader/IRReader.h>
#include <llvm/IR/Verifier.h>
#include <llvm/Support/SourceMgr.h>
#include <llvm-c/Target.h>
int main(int argc,char **argv){using namespace llvm;LLVMContext C;SMDiagnostic E;
 auto M=parseIRFile(argv[1],E,C);if(!M){E.print(argv[0],errs());return 2;}
 if(verifyModule(*M,&errs()))return 2;
 LLVMTargetMachineRef TM=nullptr;
 if(argc==3){LLVMInitializeNativeTarget();LLVMInitializeNativeAsmPrinter();LLVMTargetRef T;char *Error=nullptr;
 auto Triple=M->getTargetTriple().str();if(LLVMGetTargetFromTriple(Triple.c_str(),&T,&Error))return 2;
 TM=LLVMCreateTargetMachine(T,Triple.c_str(),"generic","",LLVMCodeGenLevelAggressive,LLVMRelocDefault,LLVMCodeModelDefault);if(!TM)return 2;}
 errs()<<"changed="<<(argc==3 ? elisacoreOptimizeSqrtNonNaN(wrap(M.get()), TM) : elisacoreProveSqrtNonNaN(wrap(M.get())))<<"\n";
 if(TM)LLVMDisposeTargetMachine(TM);
 if(verifyModule(*M,&errs()))return 2;M->print(outs(),nullptr);}
''')
        transform=q/'transform'
        run([bindir/'clang++', *flags, '-O2', driver, *links, '-Wl,-rpath,'+libdir, '-o', transform])
        def apply(name, text, changed, cleanup=False):
            source=q/(name+'.ll');source.write_text(text);p=run([transform,source]+(["cleanup"] if cleanup else []))
            if ('changed=1' in p.stderr)!=changed: raise RuntimeError(name+': '+p.stderr)
            return p.stdout
        candidate=apply('original',fixture,True)
        if apply('idempotent',candidate,False).splitlines()[1:]!=candidate.splitlines()[1:]: raise RuntimeError('not idempotent')
        for name,text in controls.items(): apply(name,text,False)
        infinite=apply('positive-infinity',opposite.replace('0xFFF0000000000000','0.000000e+00'),True)
        if 'ninf' in infinite: raise RuntimeError('infinity incorrectly excluded')
        candidate=apply("cleanup",fixture,True,True)
        if "@llvm.sqrt.f64" not in candidate: raise RuntimeError("sqrt cleanup did not run")
        # Exercise the exact linked base/candidate results, output canaries and
        # invalid-input precedence over a deterministic varied input corpus.
        harness=q/'check.c';harness.write_text(r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
extern int64_t dispersion(int64_t*,uint64_t,unsigned char*,uint64_t);
int main(void){uint64_t state=78193;int64_t x[129];unsigned char out[32];
 for(unsigned k=0;k<800;k++){unsigned n=k%130;
  for(unsigned i=0;i<n;i++){state=state*6364136223846793005ULL+1;x[i]=(int64_t)(state%20001)-10000;}
  if(k%17==0&&n)x[n-1]=10001;
  unsigned cap=k%19==0?15:16;memset(out,0xa5,sizeof out);
  int64_t rc=dispersion(x,n,out,cap);printf("%lld:",(long long)rc);
  for(unsigned i=0;i<32;i++)printf("%02x",out[i]);puts("");
 }return 0;}
''')
        outputs=[]
        for name,text in [('base',fixture),('candidate',candidate)]:
            source=q/(name+'.ll');source.write_text(text);binary=q/name
            run([bindir/'clang','-O3','-Wno-override-module',source,harness,'-lm','-o',binary]);outputs.append(run([binary]).stdout)
        if outputs[0]!=outputs[1]: raise RuntimeError('linked results differ')
    print('sqrt proof: safe reduction, 9 exclusions, idempotence, 800 linked cases passed')
if __name__=='__main__': main()
