#!/usr/bin/env python3
"""Verify packed Boolean arrays across word boundaries and pointer-index wrapping: the
`private-bool-arrays` pass through `elisac llvm-pass`, then every write/read pair run."""
import os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'test'/'llvm'))
from elisa_llvm_pass import run_pass
CONFIG=os.environ.get('LLVM_CONFIG','/opt/homebrew/opt/llvm@23/bin/llvm-config')
def run(cmd):return subprocess.run(list(map(str,cmd)),capture_output=True,text=True,check=True,timeout=28)
def fixture(n,volatile=False,wrap=False):
 # The chained non-inbounds GEPs deliberately leave and return to the allocation.
 ptr='%a'
 geps=''
 if wrap:
  geps=' %outside = getelementptr i8, ptr %a, i64 -1\n %back = getelementptr i8, ptr %outside, i64 1\n'
  ptr='%back'
 return f'''target triple = "{os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin')}"
target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1 immarg)
define i32 @probe(i64 %write, i64 %read, i1 %v) {{
 %a = alloca [{n} x i1]
 call void @llvm.memset.p0.i64(ptr %a, i8 0, i64 {n}, i1 false)
{geps} %w = getelementptr i8, ptr {ptr}, i64 %write
 store {'volatile ' if volatile else ''}i1 %v, ptr %w
 %clear = getelementptr i8, ptr %a, i64 63
 call void @llvm.memset.p0.i64(ptr %clear, i8 0, i64 2, i1 false)
 %r = getelementptr i8, ptr {ptr}, i64 %read
 %bit = load i1, ptr %r
 %result = zext i1 %bit to i32
 ret i32 %result
}}
'''
with tempfile.TemporaryDirectory(prefix='bool-array-pack-') as tmp:
 d=Path(tmp);bindir=Path(run([CONFIG,'--bindir']).stdout.strip())
 for n,vol,wrap in [(64,False,False),(65,False,False),(100,False,False),(128,False,False),(129,False,False),(100,True,False),(100,False,True)]:
  # A two-byte partial clear requires an array of at least 65 elements.
  ir=fixture(n,vol,wrap) if n>=65 else fixture(n,vol,wrap).replace('i64 2, i1 false','i64 1, i1 false')
  changed,module=run_pass('private-bool-arrays',ir);assert changed==(0 if n>128 or vol else 1),(n,vol,wrap,module)
  (d/'output.ll').write_text(module)
  (d/'main.c').write_text(f'''extern int probe(unsigned long,unsigned long,_Bool);
int main(void){{for(unsigned long w=0;w<{n};++w)for(unsigned long r=0;r<{n};++r)for(int v=0;v<2;++v){{int expected=w==r && v && !(r>=63 && r<{min(65,n)});if(probe(w,r,v)!=expected)return 1;}}return 0;}}''')
  run([bindir/'clang','-O2',d/'output.ll',d/'main.c','-o',d/'check']);run([d/'check'])
  print('PASS',n,'volatile' if vol else 'ordinary','wrapping-gep' if wrap else '')
