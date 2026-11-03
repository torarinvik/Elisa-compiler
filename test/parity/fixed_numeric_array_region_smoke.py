#!/usr/bin/env python3
"""Verify inline numeric arrays avoid a carrier while nested allocations retain it."""
import argparse
from pathlib import Path
import os
import subprocess
import tempfile

PURE='''def fixed_float(a: f64) -> f64:
    values: mutable f64[3] = [a, 2.0, 3.0]
    return values[0]+values[1]+values[2]

def fixed_signed(a: i64) -> i64:
    values: mutable i64[3] = [a, 2, 3]
    return values[0]+values[1]+values[2]

def fixed_unsigned(a: u8) -> u8:
    values: mutable u8[3] = [a, 2, 3]
    return values[0]

def fixed_bool(a: bool) -> bool:
    values: mutable bool[2] = [a, false]
    return values[0]

export fn float_probe(a: f64) -> f64 = fixed_float
export fn signed_probe(a: i64) -> i64 = fixed_signed
export fn unsigned_probe(a: u8) -> u8 = fixed_unsigned
export fn bool_probe(a: bool) -> bool = fixed_bool
'''
NESTED='''def make_values(a: i64) -> darray[i64]:
    return [a, a+1]

def nested_allocation(a: i64) -> f64:
    values: mutable f64[2] = [make_values(a).count.f64(), 3.0]
    return values[0]+values[1]

export fn nested_probe(a: i64) -> f64 = nested_allocation
'''
GROWABLE='''def dynamic_values(a: i64) -> i64:
    values: mutable darray[i64] = [a, a+1]
    return values[0]+values[1]

export fn dynamic_probe(a: i64) -> i64 = dynamic_values
'''
C='''#include <stdint.h>
#include <stdbool.h>
extern double float_probe(double),nested_probe(int64_t);
extern int64_t signed_probe(int64_t),dynamic_probe(int64_t);
extern uint8_t unsigned_probe(uint8_t);
extern bool bool_probe(bool);
int main(void){
 for(int i=-100;i<=100;i++){
  if(float_probe(i)!=i+5||signed_probe(i)!=i+5)return 1;
  if(unsigned_probe((uint8_t)i)!=(uint8_t)i)return 2;
  if(bool_probe(i!=0)!=(i!=0))return 3;
#ifdef WITH_RUNTIME
  if(nested_probe(i)!=5.0||dynamic_probe(i)!=2*i+1)return 4;
#endif
 }
 return 0;
}'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compiler',required=True);p.add_argument('--cc',default='clang')
    p.add_argument('--runtime',required=True)
    args=p.parse_args();prefix=['gtimeout' if os.uname().sysname=='Darwin' else 'timeout','-k','.1s','29s']
    def run(c):
        r=subprocess.run(prefix+list(map(str,c)),capture_output=True,text=True)
        if r.returncode:raise RuntimeError(' '.join(map(str,c))+'\n'+r.stdout+r.stderr)
        return r
    with tempfile.TemporaryDirectory(prefix='elisa-fixed-array-region-') as tmp:
        root=Path(tmp);driver=root/'check.c';driver.write_text(C)
        for level in ['-O0','-O3']:
            objects=[]
            for name,source in [('pure',PURE),('nested',NESTED),('growable',GROWABLE)]:
                src=root/(name+'.elisa');src.write_text(source);ir=root/(name+'.ll');obj=root/(name+'.o')
                run([args.compiler,level,'-emit','llvm','-o',ir,src]);text=ir.read_text()
                calls_free='call void @arena_free(' in text
                if name=='pure' and calls_free:raise RuntimeError('numeric fixed array acquired a region')
                if name!='pure' and not calls_free:raise RuntimeError(name+' lost its allocation carrier')
                run([args.compiler,level,'-emit','obj','-o',obj,src]);objects.append(obj)
            pure=root/'pure';run([args.cc,driver,objects[0],'-o',pure,'-lm']);run([pure])
            combined=root/'combined';dead=['-Wl,-dead_strip'] if os.uname().sysname=='Darwin' else ['-Wl,--gc-sections']
            run([args.cc,'-DWITH_RUNTIME',driver,*objects,args.runtime,*dead,'-o',combined,'-lm']);run([combined])
            print(level+': pure arrays link without runtime; nested/growable native checks passed',flush=True)
if __name__=='__main__':main()
