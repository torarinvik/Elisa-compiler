#!/usr/bin/env python3
"""Exercise privacy through real compiler front doors, including identical LLVM for public/private layouts."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = '''module Vault:
    struct Handle:
        private:
            value: mutable i64
        public:
            tag: i64
    def Handle() -> Handle:
        Handle{value: 41, tag: 1}
    def read(h: Handle&) -> i64:
        h.value
'''
CASES = {
    'constructor': (False, '''def main() -> i32:
    h = Vault::Handle()
    0 if Vault::read(&h) == 41 and h.tag == 1 else 1
'''),
    'read': (True, '''def main() -> i64:
    h = Vault::Handle()
    h.value
'''),
    'reference': (True, '''def get(h: Vault::Handle&) -> i64:
    h.value
'''),
    'write': (True, '''def set(h: mutable Vault::Handle&) -> void:
    h.value <- 0
'''),
    'literal': (True, '''def main() -> i64:
    h = Vault::Handle{value: 0, tag: 1}
    h.tag
'''),
    'nested_block': (True, '''def main() -> i64:
    h: Vault::Handle =
        Vault::Handle()
    h.value
'''),
    'inferred_block': (True, '''def main() -> i64:
    h =
        temp = Vault::Handle()
        temp
    h.value
'''),
    'generic_return': (True, '''def identity[T](value: T) -> T:
    value
def main() -> i64:
    h = identity[Vault::Handle](Vault::Handle())
    h.value
'''),
    'generic_pattern': (True, '''def identity[T](value: T) -> T:
    value
def main() -> i64:
    h = identity[Vault::Handle](Vault::Handle())
    match h:
        Vault::Handle{value: v}: v
'''),
    'zeroed': (True, '''def main() -> i64:
    h: Vault::Handle = zeroed
    h.tag
'''),
    'zeroed_nested': (True, '''struct Wrapper:
    handle: Vault::Handle
def main() -> i64:
    wrapper: Wrapper = zeroed
    wrapper.handle.tag
'''),
    'zeroed_generic_wrapper': (True, '''type Payload = Vault::Handle
struct Wrapper[T]:
    payload: T
def main() -> i64:
    wrapper: Wrapper[Payload] = zeroed
    wrapper.payload.tag
'''),
    'zeroed_owner': (False, '''module Vault::Child:
    def empty() -> i64:
        h: Vault::Handle = zeroed
        h.tag
def main() -> i32:
    0 if Vault::Child::empty() == 0 else 1
'''),
    'record_update': (True, '''def main() -> i64:
    h = Vault::Handle()
    changed = h{value = 0}
    changed.tag
'''),
    'alias': (True, '''type Alias = Vault::Handle
def get(h: Alias&) -> i64:
    h.value
'''),
    'pattern': (True, '''def main() -> i64:
    h = Vault::Handle()
    match h:
        Vault::Handle{value: v}: v
'''),
    'descendant': (False, '''module Vault::Child:
    def get(h: Vault::Handle&) -> i64:
        h.value
def main() -> i32:
    h = Vault::Handle()
    0 if Vault::Child::get(&h) == 41 else 1
'''),
    'visibility_named_fields': (False, '''struct Flags:
    private: i64
    public: i64
def main() -> i32:
    flags = Flags{private: 1, public: 2}
    0 if flags.private + flags.public == 3 else 1
'''),
    'same_name_global': (False, '''struct Handle:
    value: i64
def main() -> i32:
    h = Handle{value: 2}
    0 if h.value == 2 else 1
'''),
    'nested_type': (False, '''module Vault::Nested:
    struct Item:
        private:
            hidden: i64
    def Item() -> Item:
        Item{hidden: 3}
    def read(item: Item&) -> i64:
        item.hidden
def main() -> i32:
    item: Vault::Nested::Item = Vault::Nested::Item()
    0 if Vault::Nested::read(&item) == 3 else 1
'''),
    'relative_catch': (False, '''module Left:
    module Ops:
        error Failure:
            Failed
        def make() -> Vault::Handle error[Failure]:
            Vault::Handle()
    def get() -> Vault::Handle:
        catch Ops::make():
            value: value
            error failure: Vault::Handle()
module Right::Ops:
    error Failure:
        Failed
    def make() -> i64 error[Failure]:
        7
def main() -> i32:
    h = Left::get()
    0 if Vault::read(&h) == 41 else 1
'''),
    'qualified_catch': (False, '''module Left::Ops:
    error Failure:
        Failed
    def make() -> Vault::Handle error[Failure]:
        Vault::Handle()
module Right::Ops:
    error Failure:
        Failed
    def make() -> i64 error[Failure]:
        7
def main() -> i32:
    h: Vault::Handle = catch Left::Ops::make():
        value: value
        error failure: Vault::Handle()
    0 if Vault::read(&h) == 41 else 1
'''),
    'same_name_public': (False, '''module Other:
    struct Handle:
        value: i64
def main() -> i32:
    h: Other::Handle = Other::Handle{value: 2}
    0 if h.value == 2 else 1
'''),
}

def main():
    env = dict(os.environ, ELISA_ALLOW_STALE_STAGE1='1')
    stage0 = Path(os.environ.get('ELISACORE_BIN', ROOT / '../../Go projects/Elisa-core/compiler/bin/elisac'))
    compilers = [stage0, ROOT / 'scripts/elisac_stage1.sh']
    with tempfile.TemporaryDirectory(prefix='elisa-private-fields-') as directory:
        work = Path(directory)
        for compiler in compilers:
            for name, (reject, body) in CASES.items():
                source = work / f'{name}.elisa'
                source.write_text(BASE + body)
                result = subprocess.run([str(compiler), '-emit', 'llvm', '-o', str(work / 'case.ll'), str(source)], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                output = result.stdout + result.stderr
                if reject:
                    assert result.returncode != 0 and 'is private to module' in output, (compiler, name, result.returncode, output[-6000:])
                else:
                    assert result.returncode == 0, (compiler, name, output[-6000:])
                if name == 'constructor':
                    private_ir = (work / 'case.ll').read_text()
                    source.write_text((BASE + body).replace('private:', 'public :'))
                    public = subprocess.run([str(compiler), '-emit', 'llvm', '-o', str(work / 'case.ll'), str(source)], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    assert public.returncode == 0, public.stderr
                    assert (work / 'case.ll').read_text() == private_ir, 'field privacy changed generated LLVM'
                print(f'{compiler.name}: {name} PASS', flush=True)
if __name__ == '__main__':
    main()
