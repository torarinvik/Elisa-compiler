#!/usr/bin/env python3
"""Check runtime object reuse across effective FP policies using native objects."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc',default='clang')
    args=parser.parse_args()
    cc=shutil.which(args.cc) or args.cc
    repo=Path(__file__).resolve().parents[2]
    timeout='gtimeout' if os.uname().sysname=='Darwin' else 'timeout'
    prefix=[timeout,'-k','.1s','29s']
    with tempfile.TemporaryDirectory(prefix='elisa-runtime-fp-cache-') as tmp:
        root=Path(tmp);(root/'scripts').mkdir();(root/'elisacore_std').mkdir()
        for name in ['build_runtime_object.sh','write_profiler_hook_fallbacks.sh']:
            shutil.copy2(repo/'scripts'/name,root/'scripts'/name)
        (root/'elisacore_std/native_runtime_support.elisa').write_text('# cache input fixture\n')
        product=root/'compiler';calls=root/'calls';out=root/'runtime.o'
        product.write_text('#!'+sys.executable+'\n'+'''import os,subprocess,sys
from pathlib import Path
mode=1 if os.environ.get('ELISACORE_STRICT_FP') else (2 if os.environ.get('ELISACORE_FAST_MATH') else 0)
with open(os.environ['FP_CACHE_CALLS'],'a') as f:f.write(str(mode)+'\\n')
out=sys.argv[sys.argv.index('-o')+1]
subprocess.run([os.environ['ELISA_CLANG'],'-O2','-x','c','-c','-','-o',out],input=f'int runtime_fp_mode(void){{return {mode};}}\\n',text=True,check=True)
''');product.chmod(0o755)
        driver=root/'main.c';driver.write_text('extern int runtime_fp_mode(void);\nint main(void){return runtime_fp_mode();}\n')
        env=os.environ.copy()
        env.update(ELISA_STAGE1_BIN=str(product),ELISA_RUNTIME_OBJ=str(out),ELISA_CLANG=cc,FP_CACHE_CALLS=str(calls))
        for strict,fast,expected,compilations in [('', '',0,1),('1','',1,2),('true','1',1,2),('0','true',1,2),('', '1',2,3),('', 'true',2,3),('', '',0,4),('', '',0,4)]:
            current=dict(env,ELISACORE_STRICT_FP=strict,ELISACORE_FAST_MATH=fast)
            subprocess.run(prefix+['bash',str(root/'scripts/build_runtime_object.sh')],env=current,check=True,capture_output=True,text=True)
            observed=len(calls.read_text().splitlines())
            if observed!=compilations:raise RuntimeError(f'FP mode {expected}: compiler called {observed} times, expected {compilations}')
            binary=root/'check'
            subprocess.run(prefix+[cc,str(driver),str(out),'-o',str(binary)],check=True,capture_output=True,text=True)
            result=subprocess.run(prefix+[str(binary)])
            if result.returncode!=expected:raise RuntimeError(f'cached object has FP mode {result.returncode}, expected {expected}')
        print('runtime FP cache: eight transitions, four compiles; native outputs verified')


if __name__=='__main__':main()
