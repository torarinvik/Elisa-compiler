#!/usr/bin/env python3
"""Qualify bounded-product overflow proofs with independent linked results."""
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
        print('bounded product: requires LLVM 23; skipped')
        return
    bindir = Path(run([config, '--bindir']).stdout.strip())
    flags = shlex.split(run([config, '--cxxflags']).stdout)
    links = shlex.split(run([config, '--ldflags', '--libs', '--system-libs']).stdout)
    libdir = run([config, '--libdir']).stdout.strip()
    host_target = run([config, '--host-target']).stdout.strip()
    fixture = (ROOT / 'test/parity/bounded_product_fixture.ll').read_text().replace(
        'target triple = "aarch64-unknown-linux-gnu"', f'target triple = "{host_target}"')
    cleanup = 'function(correlated-propagation,instcombine,simplifycfg)'
    if 'darwin' in host_target and host_target.startswith(('arm64', 'aarch64')):
        cleanup = ('function(correlated-propagation,instcombine,simplifycfg,'
                   'loop-simplify,lcssa,loop-vectorize,instcombine,simplifycfg)')
    with tempfile.TemporaryDirectory(prefix='elisa-product-proof-') as tmp:
        work = Path(tmp)
        driver = work / 'driver.cpp'
        driver.write_text('#include ' + json.dumps(str(ROOT / 'src/backend/llvm_bounded_product.cpp')) + r'''
#include <llvm/IRReader/IRReader.h>
#include <llvm/IR/Verifier.h>
#include <llvm/Support/SourceMgr.h>
int main(int argc,char **argv){using namespace llvm;if(argc!=2)return 2;
 LLVMContext C;SMDiagnostic E;auto M=parseIRFile(argv[1],E,C);if(!M){E.print(argv[0],errs());return 2;}
 if(verifyModule(*M,&errs()))return 2;
 errs()<<"changed="<<elisacoreBoundedProducts(wrap(M.get()))<<"\n";
 if(verifyModule(*M,&errs()))return 2;M->print(outs(),nullptr);return 0;
}
''')
        transform = work / 'transform'
        run([bindir / 'clang++', *flags, '-O2', driver, *links, '-Wl,-rpath,'+libdir, '-o', transform])
        def apply(label, text):
            source = work / (label+'.ll')
            source.write_text(text)
            return run([transform, source]).stdout
        def checked(text):
            return any('call ' in line and '@llvm.smul.with.overflow' in line for line in text.splitlines())
        candidate = apply('safe', fixture)
        if checked(candidate):
            raise RuntimeError('safe product still has an overflow check')
        controls = {
            'large-base': fixture.replace('srem i64 %base_arg, 10', 'srem i64 %base_arg, 2147483647'),
            'unknown-base-definedness': fixture.replace('i64 noundef %base_arg', 'i64 %base_arg'),
            'unknown-counter-definedness': fixture.replace('i64 noundef %pos', 'i64 %pos'),
            'unsigned-poison-flag': fixture.replace('%low = mul i64', '%low = mul nuw i64'),
            'non-unit-exponent': fixture.replace('%exponent, 1', '%exponent, 2'),
            'sanitizer': fixture.replace('%base_arg) {', '%base_arg) sanitize_address {'),
            'unknown-metadata': fixture.replace('i64 %value, i64 %frozen_base)', 'i64 %value, i64 %frozen_base), !opaque !0') + '\n!0 = !{}\n',
            'unbounded-counter': fixture.replace('%pos_shift, 7', '%pos_shift, 100'),
        }
        for name, text in controls.items():
            if not checked(apply(name, text)):
                raise RuntimeError(name+': unproved overflow check removed')
        early = fixture.replace('%low = mul', '%early_use = add i64 %frozen_base, 1\n %low = mul')
        if 'freeze i64' not in apply('earlier-freeze-use', early):
            raise RuntimeError('freeze removed outside the proven use context')
        # The last header visit takes no backedge, but its checked add still
        # executes. Its overflowing flag is observable even without a trap.
        header_text = (ROOT / 'test/parity/bounded_product_header_counter.ll').read_text()
        header_original = work / 'header-counter.ll'
        header_candidate = work / 'header-counter-candidate.ll'
        header_candidate.write_text(apply('header-counter', header_text))
        header_check = work / 'header-check.c'
        header_check.write_text('#include <stdint.h>\nextern int64_t header_counter(void);\nint main(void){return header_counter()!=1;}\n')
        for label, ir in [('base', header_original), ('candidate', header_candidate)]:
            binary = work / ('header-' + label)
            run([bindir/'clang', '-O0', ir, header_check, '-o', binary])
            run([binary])
        harness = work / 'check.c'
        harness.write_text(r'''
#include <stdint.h>
#include <signal.h>
#include <setjmp.h>
#include <stdio.h>
extern int64_t scan_power(int64_t,int64_t,int64_t);
static sigjmp_buf trap;
static void caught(int n){(void)n;siglongjmp(trap,1);}
#ifndef MODULUS
#define MODULUS 10
#endif
static int check(int64_t n,int64_t p,int64_t b){
 int64_t original_p=p;int64_t expected=-777;int overflow=0;
 if(n>=1&&n<=99999999&&p>=1&&p<=8){uint64_t total=0;int64_t base=b%MODULUS;
  for(int64_t rest=n;rest>0;rest/=10,--p){int64_t power=1;
   for(int64_t e=0;e<p;++e)if(__builtin_mul_overflow(power,base,&power)){overflow=1;break;}
   if(overflow)break;total+=(uint64_t)power;
  }expected=(int64_t)total;
 }
 if(sigsetjmp(trap,1))return !overflow;
 int64_t got=scan_power(n,original_p,b);
 return got!=expected||overflow;
}
''')
        code = harness.read_text()
        code += r'''
int main(void){struct sigaction action={0};action.sa_handler=caught;sigemptyset(&action.sa_mask);sigaction(SIGILL,&action,0);sigaction(SIGTRAP,&action,0);
 int64_t ns[]={0,1,9,10,99,100,999,10000000,99999999,100000000};
 int64_t bs[]={INT64_MIN,INT64_MIN+1,-3037000500LL,-2147483648LL,-10,-9,-2,-1,0,1,2,9,10,2147483647LL,3037000500LL,INT64_MAX};
 unsigned count=0;
 for(unsigned i=0;i<sizeof(ns)/sizeof(ns[0]);++i)for(int64_t p=0;p<=9;++p)for(unsigned j=0;j<sizeof(bs)/sizeof(bs[0]);++j){if(check(ns[i],p,bs[j]))return 1;++count;}
 uint64_t state=43176;
 for(unsigned i=0;i<20000;++i){state=state*6364136223846793005ULL+1;int64_t n=state%100000005;state=state*6364136223846793005ULL+1;int64_t p=state%12;state=state*6364136223846793005ULL+1;if(check(n,p,(int64_t)state))return 2;++count;}
 printf("%u cases passed\n",count);return 0;
}
'''
        harness.write_text(code)
        for label, text, modulus in [('safe',fixture,10),('large-base',controls['large-base'],2147483647)]:
            original = work / (label+'.ll')
            changed = work / (label+'-changed.ll')
            changed.write_text(apply(label,text))
            clean = work / (label+'-clean.ll')
            run([bindir/'opt','-passes=' + cleanup,'-S',changed,'-o',clean])
            for name, ir in [('base',original),('candidate',clean)]:
                binary = work/(label+'-'+name)
                run([bindir/'clang','-O0','-D_POSIX_C_SOURCE=200809L',f'-DMODULUS={modulus}',ir,harness,'-o',binary])
                print(label,name,run([binary]).stdout.strip())
    print('bounded product: 8 exclusions and linked result/overflow corpus passed')

if __name__=='__main__':main()
