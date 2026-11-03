#!/usr/bin/env python3
"""Qualify Stage1 FP modes, including strict overrides and constant builders."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

SOURCE = '''def product_sum(a: f64, b: f64, c: f64) -> f64:
    return a*b+c

@fast_math
def opted_product_sum(a: f64, b: f64, c: f64) -> f64:
    return a*b+c

def quotient(a: f64, b: f64) -> f64:
    return a/b

def negate_value(a: f64) -> f64:
    return -a

def nan_value(a: f64) -> i64:
    return 1 if a != a else 0

@fast_math
def folded_value() -> f64:
    return 1.5*2.0+3.0

def product_sum_f32(a: f32, b: f32, c: f32) -> f32:
    return a*b+c

export fn rounding_probe_f32(a: f32, b: f32, c: f32) -> f32 = product_sum_f32
export fn rounding_probe(a: f64, b: f64, c: f64) -> f64 = product_sum
export fn opted_probe(a: f64, b: f64, c: f64) -> f64 = opted_product_sum
export fn division_probe(a: f64, b: f64) -> f64 = quotient
export fn neg_probe(a: f64) -> f64 = negate_value
export fn nan_probe(a: f64) -> i64 = nan_value
export fn constant_probe() -> f64 = folded_value
'''
C_SOURCE = r'''#include <stdint.h>
#include <math.h>
#include <stdlib.h>
extern double rounding_probe(double,double,double),opted_probe(double,double,double);
extern double division_probe(double,double),neg_probe(double),constant_probe(void);
extern int64_t nan_probe(double);
extern float rounding_probe_f32(float,float,float);
int main(int argc,char **argv){
 int strict=atoi(argv[1]);
 double a=1.0+0x1p-27,b=1.0-0x1p-27,c=-1.0;
 double expected=strict?0.0:-0x1p-54;
 if(rounding_probe(a,b,c)!=expected)return 1;
 if(opted_probe(a,b,c)!=expected)return 2;
 if(constant_probe()!=6.0)return 3;
 float af=1.0f+0x1p-13f,bf=1.0f-0x1p-13f;
 if(rounding_probe_f32(af,bf,-1.0f)!=(strict?0.0f:-0x1p-26f))return 9;
 if(!signbit(neg_probe(0.0))||signbit(neg_probe(-0.0)))return 4;
 if(neg_probe(INFINITY)!=-INFINITY||neg_probe(-INFINITY)!=INFINITY)return 5;
 if(nan_probe(NAN)!=1)return 6;
 if(strict){
  double values[]={0.0,-0.0,1.0,-1.0,0x1p-1022,0x1p-1074,0x1.fffffffffffffp1023,INFINITY,-INFINITY,NAN};
  for(unsigned i=0;i<10;i++)for(unsigned j=0;j<10;j++){
   volatile double x=values[i],y=values[j];double ref=x/y,actual=division_probe(x,y);
   if(isnan(ref)){if(!isnan(actual))return 7;}
   else if(actual!=ref||(actual==0.0&&signbit(actual)!=signbit(ref)))return 8;
  }
 }
 return 0;
}'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compiler',required=True)
    p.add_argument('--cc',default='clang')
    args=p.parse_args()
    prefix=['gtimeout' if os.uname().sysname=='Darwin' else 'timeout','-k','.1s','29s']
    with tempfile.TemporaryDirectory(prefix='elisa-fp-policy-') as tmp:
        root=Path(tmp);source=root/'probe.elisa';source.write_text(SOURCE)
        driver=root/'driver.c';driver.write_text(C_SOURCE)
        base=os.environ.copy()
        for k in ['ELISACORE_FAST_MATH','ELISACORE_STRICT_FP']:base.pop(k,None)
        cases=[('default',[],{},False,False),
               ('strict-cli',['-fstrict-fp'],{},True,False),
               ('strict-env',[],{'ELISACORE_STRICT_FP':'1'},True,False),
               ('strict-nonempty-env',[],{'ELISACORE_STRICT_FP':'true'},True,False),
               ('strict-zero-spelling',[],{'ELISACORE_STRICT_FP':'0'},True,False),
               ('global-fast',['-ffast-math'],{},False,True),
               ('global-fast-env',[],{'ELISACORE_FAST_MATH':'true'},False,True),
               ('global-fast-zero-spelling',[],{'ELISACORE_FAST_MATH':'0'},False,True),
               ('strict-over-global',['-ffast-math','-fstrict-fp'],{},True,False),
               ('strict-over-environment',[],{'ELISACORE_FAST_MATH':'1','ELISACORE_STRICT_FP':'1'},True,False)]
        for name,flags,extra,strict,fast in cases:
            env=dict(base,**extra);ir=root/(name+'.ll')
            c=[args.compiler,'-O0',*flags,'-emit','llvm','-o',str(ir),str(source)]
            r=subprocess.run(prefix+c,env=env,text=True,capture_output=True)
            if r.returncode:raise RuntimeError(name+': '+r.stdout+r.stderr)
            text=ir.read_text()
            if strict:
                if re.search(r'\b(?:fadd|fsub|fmul|fdiv|frem|fneg|fcmp)\s+(?:fast|contract|arcp|nnan|ninf|nsz|reassoc)\b',text):raise RuntimeError(name+': strict mode retained FP flags')
            elif fast:
                if 'fmul fast' not in text or 'fdiv fast' not in text:raise RuntimeError(name+': missing explicit fast-math flags')
            else:
                if 'fmul contract' not in text or 'fdiv arcp contract' not in text:raise RuntimeError(name+': missing default policy')
                normal=text.split('@nan_value(',1)[-1].split('\n}',1)[0]
                if re.search(r'fcmp (?:fast|nnan|ninf)',normal):raise RuntimeError(name+': default assumed finite input')
            if name in ('default','strict-cli','strict-over-global'):
                obj=root/(name+'.o');exe=root/name
                r=subprocess.run(prefix+[args.compiler,'-O3',*flags,'-emit','obj','-o',str(obj),str(source)],env=env,text=True,capture_output=True)
                if r.returncode:raise RuntimeError(name+': '+r.stderr)
                subprocess.run(prefix+[args.cc,'-O2',str(driver),str(obj),'-o',str(exe),'-lm'],check=True)
                subprocess.run(prefix+[str(exe),str(int(strict))],check=True)
            print(name+': passed',flush=True)


if __name__=='__main__':main()
