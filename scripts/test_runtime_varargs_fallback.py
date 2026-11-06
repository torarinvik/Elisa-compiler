#!/usr/bin/env python3
"""Link and exercise the exported pointer-based varargs ABI with normal Clang builtins."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = r'''
#include <stdarg.h>
#include <stdint.h>
#define STR_INNER(x) #x
#define STR(x) STR_INNER(x)
extern void *copy_args(void *) __asm__(STR(__USER_LABEL_PREFIX__) "va_copy");
extern void end_args(void *) __asm__(STR(__USER_LABEL_PREFIX__) "va_end");
static int exercise(int marker, ...) {
    va_list original;
    va_start(original, marker);
#if (defined(__x86_64__) && !defined(_WIN32)) || (defined(__aarch64__) && !defined(__APPLE__) && !defined(_WIN32))
    void *handle = copy_args(&original);
    va_list *copy = (va_list *)handle;
    int first = va_arg(*copy, int);
    int second = va_arg(*copy, int);
    int third = va_arg(*copy, int);
#else
    void *handle = copy_args((void *)original);
    va_list copy = (va_list)handle;
    int first = va_arg(copy, int);
    int second = va_arg(copy, int);
    int third = va_arg(copy, int);
#endif
    int original_first = va_arg(original, int);
    end_args(handle);
    va_end(original);
    return first == 7 && second == 11 && third == 19 && original_first == 7 ? 0 : 1;
}
int main(void) { return exercise(0, 7, 11, 19); }
'''
with tempfile.TemporaryDirectory(prefix='elisa-varargs-abi-') as work:
    work = Path(work)
    (work / 'test.c').write_text(source)
    # Deliberately retain Clang's normal builtin handling: the old fallback names
    # collide with builtins on Linux, before a program can be linked or tested.
    subprocess.run([os.environ.get('CC', 'clang'), '-Wall', '-Wextra', '-Werror',
                    str(work / 'test.c'), str(root / 'scripts/pymodule_runtime_fallback.c'),
                    '-o', str(work / 'test')], check=True, timeout=28)
    subprocess.run([str(work / 'test')], check=True, timeout=10)
print('PASS exported va_copy/va_end ABI and independent argument cursors')
