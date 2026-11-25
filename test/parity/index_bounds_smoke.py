#!/usr/bin/env python3
"""Qualify paired-index validation rewrites with independent linked results."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test' / 'llvm'))
from elisa_llvm_pass import run_pass

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
        print('index bounds: requires LLVM 23; skipped')
        return
    bindir = Path(run([config, '--bindir']).stdout.strip())
    with tempfile.TemporaryDirectory(prefix='elisa-index-bounds-') as tmp:
        work=Path(tmp)
        fixture=(ROOT/'test/parity/index_bounds_fixture.ll').read_text()
        cases={
          'paired':(fixture,1,0),
          'different-error':(fixture.replace('[ -1, %upper ]','[ -2, %upper ]'),0,1),
          'observable':(fixture.replace('upper:\n','upper:\n call void @observable()\n'),0,2),
          'unknown-bound':(fixture.replace('%n = and i64 %raw, 63','%n = add i64 %raw, 0'),0,3),
          'negative-bound':(fixture.replace('%n = and i64 %raw, 63','%n = or i64 %raw, -64'),0,4),
          'continue-phi':(fixture.replace('valid:\n','valid:\n %seen = phi i64 [ 1, %upper ]\n',1),0,0),
          'sanitized':(fixture.replace('%raw) {','%raw) sanitize_address {'),0,0),
        }
        loop = fixture.replace('valid:\n ret i64 7', 
            'valid:\n br label %loop\nloop:\n %i = phi i64 [ 0, %valid ], [ %next, %loop ]\n'
            ' %next = add i64 %i, 1\n %done = icmp eq i64 %next, 16\n'
            ' br i1 %done, label %finished, label %loop\nfinished:\n ret i64 7', 1)
        for label, target, expected in [('darwin-loop','arm64-apple-darwin',True), ('linux-loop','aarch64-unknown-linux-gnu',False)]:
            _,output=run_pass('index-bounds',loop.replace('aarch64-unknown-linux-gnu',target))
            if ('llvm.loop.align' in output)!=expected:raise RuntimeError(label+': wrong alignment policy')
        explicit=loop.replace('aarch64-unknown-linux-gnu','arm64-apple-darwin').replace(
            'br i1 %done, label %finished, label %loop','br i1 %done, label %finished, label %loop, !llvm.loop !0')
        explicit+='\n!0 = distinct !{!0, !1}\n!1 = !{!"llvm.loop.align", i32 8}\n'
        _,output=run_pass('index-bounds',explicit)
        if '!"llvm.loop.align", i32 8' not in output or '!"llvm.loop.align", i32 16' in output:
            raise RuntimeError('explicit loop alignment was changed')
        harness=work/'check.c'
        harness.write_text(r'''
#include <stdint.h>
#include <stdio.h>
static int calls;
void observable(void){++calls;}
extern int64_t validate(int64_t,int64_t,int64_t);
#ifndef MODE
#define MODE 0
#endif
int main(void){unsigned count=0;
 for(int64_t raw=-2;raw<=66;++raw)for(int64_t a=-2;a<=66;++a)for(int64_t b=-2;b<=66;++b){
  int64_t n=MODE==3?raw:MODE==4?(raw|INT64_C(-64)):(raw&63);
  int neg=a<0||b<0;int upper=a>=n||b>=n;
  int64_t expected=neg?-1:upper?(MODE==1?-2:-1):7;
  calls=0;int64_t got=validate(a,b,raw);
  if(got!=expected||calls!=((MODE==2&&!neg)?1:0))return 1;
  ++count;
 }
 printf("%u linked cases passed\n",count);return 0;
}
''')
        for name,(text,want,mode) in cases.items():
            source=work/(name+'.ll');source.write_text(text)
            count,module=run_pass('index-bounds',text)
            if count!=want:raise RuntimeError(f'{name}: wrong rewrite count {count}')
            changed=work/(name+'-changed.ll');changed.write_text(module)
            if run_pass('index-bounds',module)[0]!=0:raise RuntimeError(name+': not idempotent')
            for label,ir in [('baseline',source),('candidate',changed)]:
                binary=work/(name+'-'+label)
                run([bindir/'clang','-O3',f'-DMODE={mode}',ir,harness,'-o',binary])
                print(name,label,run([binary]).stdout.strip())
    print('index bounds: CFG exclusions and independent linked results passed')

if __name__=='__main__':main()
