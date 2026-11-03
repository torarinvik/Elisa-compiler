#!/usr/bin/env python3
"""Verify reciprocal sharing legality, SSA/idempotency, and native FP boundaries."""
import argparse
from pathlib import Path
import os
import shlex
import subprocess
import tempfile

DRIVER = r'''
#include <llvm/IRReader/IRReader.h>
#include <llvm/IR/Verifier.h>
#include <llvm/Support/SourceMgr.h>
#include <llvm/Support/raw_ostream.h>
#include "llvm_shared_reciprocal.cpp"
int main(int argc,char **argv){
 llvm::LLVMContext C;llvm::SMDiagnostic E;auto M=llvm::parseIRFile(argv[1],E,C);
 if(!M){E.print(argv[0],llvm::errs());return 1;}
 unsigned changed=elisacoreShareReciprocals(llvm::wrap(M.get()));
 if(llvm::verifyModule(*M,&llvm::errs()))return 2;
 if(elisacoreShareReciprocals(llvm::wrap(M.get())))return 3;
 llvm::errs()<<"changed "<<changed<<"\n";M->print(llvm::outs(),nullptr);
}'''


def three(name, ty='double', flags='arcp contract', attrs=''):
    return f'''define {ty} @{name}({ty} %a,{ty} %b,{ty} %c,{ty} %d) {attrs} {{
entry:
 %x = fdiv {flags} {ty} %a,%b
 %y = fdiv {flags} {ty} %c,%b
 %z = fdiv {flags} {ty} %d,%b
 %s = fadd {ty} %x,%y
 %r = fadd {ty} %s,%z
 ret {ty} %r
}}
'''

IR = three('shared')+three('shared32','float')+three('strict',flags='')+three('strict_attr',attrs='strictfp')+'''
define double @two(double %a,double %b,double %c) {
 %x=fdiv arcp double %a,%b
 %y=fdiv arcp double %c,%b
 %r=fadd double %x,%y
 ret double %r
}
define double @different(double %a,double %b,double %c,double %d) {
 %x=fdiv arcp double %a,%b
 %y=fdiv arcp double %a,%c
 %z=fdiv arcp double %a,%d
 %s=fadd double %x,%y
 %r=fadd double %s,%z
 ret double %r
}
define double @siblings(i1 %cond,double %a,double %b) {
entry:
 br i1 %cond,label %left,label %right
left:
 %x=fdiv arcp double %a,%b
 br label %exit
right:
 %y=fdiv arcp double %a,%b
 %z=fdiv arcp double %a,%b
 %s=fadd double %y,%z
 br label %exit
exit:
 %r=phi double [%x,%left],[%s,%right]
 ret double %r
}
'''
IR += """
define double @crossblock(double %a,double %b,double %c,double %d,i1 %cond) {
entry:
 %x=fdiv arcp double %a,%b
 br i1 %cond,label %left,label %right
left:
 br label %join
right:
 br label %join
join:
 %y=fdiv arcp double %c,%b
 %z=fdiv arcp double %d,%b
 %s=fadd double %x,%y
 %r=fadd double %s,%z
 ret double %r
}
define double @dependent(double %a,double %b,double %c,double %d) {
 %x=fdiv arcp double %a,%b
 %y=fdiv arcp double %c,%b
 %z=fdiv arcp double %d,%b
 %u=fdiv arcp double %a,%x
 %v=fdiv arcp double %c,%x
 %w=fdiv arcp double %d,%x
 %s=fadd double %y,%z
 %t=fadd double %u,%v
 %q=fadd double %s,%t
 %r=fadd double %q,%w
 ret double %r
}
"""
NATIVE = r'''
#include <math.h>
#include <stdint.h>
#include <stdio.h>
extern double shared(double,double,double,double),strict(double,double,double,double);
extern float shared32(float,float,float,float);
static int same(double a,double b){return isnan(a)?isnan(b):(a==b&&(a!=0||!!signbit(a)==!!signbit(b)));}
int main(void){
 double vals[]={0.,-0.,1.,-1.,3.,0x1p-1022,0x1p-1074,0x1.fffffffffffffp1023,INFINITY,-INFINITY,NAN};
 float vals32[]={0.f,-0.f,1.f,-1.f,3.f,0x1p-126f,0x1p-149f,0x1.fffffep127f,INFINITY,-INFINITY,NAN};
 unsigned checked=0;
 for(unsigned i=0;i<11;i++)for(unsigned j=0;j<11;j++)for(unsigned k=0;k<11;k++)for(unsigned l=0;l<11;l++){
  volatile double a=vals[i],b=vals[j],c=vals[k],d=vals[l],inv=1./b;
  volatile double x=a*inv,y=c*inv,z=d*inv,s=x+y;double ref=s+z;
  if(!same(ref,shared(a,b,c,d)))return 1;
  volatile double q=a/b,r=c/b,t=d/b,u=q+r;
  if(!same(u+t,strict(a,b,c,d)))return 2;
  volatile float af=vals32[i],bf=vals32[j],cf=vals32[k],df=vals32[l],iv=1.f/bf;
  volatile float xf=af*iv,yf=cf*iv,zf=df*iv,sf=xf+yf;
  if(!same((float)(sf+zf),shared32(af,bf,cf,df)))return 3;
  ++checked;
 }
 printf("native boundary tuples: %u (f32, f64 and strict control)\n",checked);return 0;
}'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--llvm-config',default='llvm-config')
    args=p.parse_args();repo=Path(__file__).resolve().parents[2]
    def config(*flags):return shlex.split(subprocess.check_output([args.llvm_config,*flags],text=True))
    bindir=Path(subprocess.check_output([args.llvm_config,'--bindir'],text=True).strip())
    prefix=['gtimeout' if os.uname().sysname=='Darwin' else 'timeout','-k','.1s','29s']
    def run(c,**kw):return subprocess.run(prefix+list(map(str,c)),check=True,**kw)
    with tempfile.TemporaryDirectory(prefix='elisa-reciprocal-') as tmp:
        root=Path(tmp);cpp=root/'driver.cpp';cpp.write_text(DRIVER);driver=root/'driver'
        run([bindir/'clang++',*config('--cxxflags'),'-O2','-I',repo/'src/backend',cpp,*config('--ldflags','--libs','core','irreader','analysis','--system-libs'),'-o',driver])
        source=root/'input.ll';source.write_text(IR)
        result=run([driver,source],capture_output=True,text=True)
        if result.stderr.strip()!='changed 15':raise RuntimeError(result.stderr)
        for name,expected in [('shared',1),('shared32',1),('strict',3),('strict_attr',3),('two',2),('different',3),('siblings',3),('crossblock',1),('dependent',2)]:
            body=result.stdout.split('@'+name+'(',1)[1].split('\n}',1)[0]
            if body.count('fdiv ')!=expected:raise RuntimeError('unexpected division count: '+name)
        out=root/'out.ll';out.write_text(result.stdout);obj=root/'out.o'
        run([bindir/'llc','-O3','-filetype=obj',out,'-o',obj])
        c=root/'check.c';c.write_text(NATIVE);exe=root/'check'
        run([bindir/'clang','-O2','-ffp-contract=off',c,obj,'-o',exe,'-lm']);run([exe])
        print('strict, threshold, denominator identity, branch dominance, verifier and idempotency: passed')

if __name__=='__main__':main()
