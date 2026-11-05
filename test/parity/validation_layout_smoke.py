#!/usr/bin/env python3
"""Qualify validation-chain layout hints with independent linked results."""
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
        print('validation layout: requires LLVM 23; skipped')
        return
    bindir = Path(run([config, '--bindir']).stdout.strip())
    flags = shlex.split(run([config, '--cxxflags']).stdout)
    links = shlex.split(run([config, '--ldflags', '--libs', '--system-libs']).stdout)
    libdir = run([config, '--libdir']).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='elisa-validation-layout-') as tmp:
        work=Path(tmp)
        driver=work/'driver.cpp'
        driver.write_text('#include '+json.dumps(str(ROOT/'src/backend/llvm_validation_layout.cpp'))+r'''
#include <llvm/IRReader/IRReader.h>
#include <llvm/IR/Verifier.h>
#include <llvm/Support/SourceMgr.h>
int main(int argc,char **argv){using namespace llvm;if(argc!=3)return 2;
 LLVMContext C;SMDiagnostic E;auto M=parseIRFile(argv[1],E,C);if(!M){E.print(argv[0],errs());return 2;}
 if(verifyModule(*M,&errs()))return 2;
 unsigned N=argv[2][0]=='1'?elisacoreBiasValidationReturns(wrap(M.get())):0;
 errs()<<N<<"\n";
 if(verifyModule(*M,&errs()))return 2;M->print(outs(),nullptr);return 0;
}
''')
        transform=work/'transform'
        run([bindir/'clang++',*flags,'-O2',driver,*links,'-Wl,-rpath,'+libdir,'-o',transform])
        fixture=(ROOT/'test/parity/validation_layout_fixture.ll').read_text()
        cases={
          'shared-error':(fixture,5),
          'different-error':(fixture.replace('[ -1, %load2 ]','[ -2, %load2 ]'),0),
          'volatile':(fixture.replace('load i64','load volatile i64',1),0),
          'constant-success':(fixture.replace('[ %sum, %success ]','[ 0, %success ]'),0),
          'existing-profile':(fixture.replace('label %load0, label %invalid','label %load0, label %invalid, !prof !0',1)+'\n!0 = !{!"branch_weights", i32 1, i32 31}\n',0),
        }
        harness=work/'check.c'
        harness.write_text(r'''
#include <stdint.h>
#include <stdio.h>
extern int64_t validated_sum(const int64_t *,uint64_t);
int main(void){unsigned count=0;int64_t v[4];
 for(v[0]=-1;v[0]<=11;++v[0])for(v[1]=-1;v[1]<=11;++v[1])for(v[2]=-1;v[2]<=11;++v[2])for(v[3]=-1;v[3]<=11;++v[3])for(uint64_t n=0;n<=5;++n){
  int64_t expected=-1;
  if(n==4&&v[0]>=0&&v[0]<=10&&v[1]>=0&&v[1]<=10&&v[2]>=0&&v[2]<=10&&v[3]>=0&&v[3]<=10)expected=v[0]+v[1]+v[2]+v[3];
  if(validated_sum(v,n)!=expected)return 1;++count;
 }
 printf("%u linked cases passed\n",count);return 0;
}
''')
        for name,(text,want) in cases.items():
            source=work/(name+'.ll');source.write_text(text)
            result=run([transform,source,'1'])
            if result.stderr.strip()!=str(want):raise RuntimeError(name+': wrong hint count '+result.stderr)
            changed=work/(name+'-changed.ll');changed.write_text(result.stdout)
            if run([transform,changed,'1']).stderr.strip()!='0':raise RuntimeError(name+': not idempotent')
            if want:
                import re
                def without_hints(t):
                    return '\n'.join(re.sub(r', !prof ![0-9]+','',l) for l in t.splitlines() if not re.match(r'^![0-9]+ =',l)).strip()
                original=run([transform,source,'0']).stdout
                if without_hints(original)!=without_hints(result.stdout):raise RuntimeError('instructions changed')
                if '!"expected"' not in result.stdout:raise RuntimeError('hint presented as measured profile')
                for label,ir in [('baseline',source),('candidate',changed)]:
                    binary=work/(name+'-'+label)
                    run([bindir/'clang','-O3',ir,harness,'-o',binary])
                    print(name,label,run([binary]).stdout.strip())
    print('validation layout: only expected weights changed; profiles and exclusions preserved')

if __name__=='__main__':main()
