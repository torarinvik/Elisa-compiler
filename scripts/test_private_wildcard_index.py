#!/usr/bin/env python3
"""Compile actual wildcard-index helpers and compare with the original full scan."""
import os, re, subprocess, tempfile
from pathlib import Path
root = Path(__file__).resolve().parents[1]
text = (root / 'src/semantic/check_private_member_access.elisa').read_text()
def helper(name):
    start = text.index('        def ' + name + '(')
    match = re.search(r'\n        (?:def |#|public:|private:)', text[start + 1:])
    return text[start:start + 1 + match.start()] + '\n'
names = ['pma_build_wildcard_import_index', 'pma_visible_wildcard_import',
         'pma_import_scope_visible', 'pma_within_module', 'pma_import_row_branch_uncertain']
source = 'include "' + str(root / 'elisacore_std/collections.elisa') + '"\n'
source += 'include "' + str(root / 'src/semantic/private_module_boundary.elisa') + '"\n'
source += '''module Ast:
    public:
        struct EnumAnnotation:
            owner: sview = ""
            name: sview = ""
            module: sview = ""
            detail_name: sview = ""
            line: u32 = 0
            offset: u32 = 0
module Semantic:
    public:
        struct PrivateMemberIndex:
            wildcard_rows: mutable darray[usize] = []
''' + ''.join(helper(name) for name in names) + '''
        def original(annotations: darray[Ast::EnumAnnotation]&, current_module: sview, owner: sview, require_definite: bool) -> bool can[Abort.Panic]:
            return any annotation in annotations where annotation.name == "__binding_wildcard_import" and annotation.owner == owner and pma_import_scope_visible(current_module, annotation.module) and (not require_definite or not pma_import_row_branch_uncertain(annotations, annotation.owner, annotation.name, annotation.module, annotation.line, annotation.offset))
        def exercise() -> i64 can[Memory.Allocate, Abort.Panic]:
            scopes: darray[sview] = ["", "A", "A::B", "A::Bee", "B", "A::B::C"]
            owners: darray[sview] = ["", "Library", "Other", "missing"]
            for variant in 0..<32:
                rows: mutable darray[Ast::EnumAnnotation] = []
                for row in 0..<32:
                    rows.push(Ast::EnumAnnotation{owner: "Library" if row % 2 == 0 else "Other", name: "__binding_wildcard_import" if row % 5 == 0 else "noise", module: scopes[row % scopes.count], line: (row % 3).u32(), offset: row.u32()})
                    if row < variant:
                        rows.push(Ast::EnumAnnotation{owner: "__pma_unknown_static_import", name: "Library" if row % 2 == 0 else "Other", detail_name: "__binding_wildcard_import", module: scopes[row % scopes.count], line: (row % 3).u32(), offset: row.u32()})
                index: mutable PrivateMemberIndex = PrivateMemberIndex{}
                pma_build_wildcard_import_index(rows, &index)
                if index.wildcard_rows.count != 7: return 1
                if not pma_visible_wildcard_import(&index, rows, "", "Library", false): return 4
                if variant == 0 and not pma_visible_wildcard_import(&index, rows, "", "Library", true): return 5
                if variant == 31 and pma_visible_wildcard_import(&index, rows, "", "Library", true): return 6
                for scope in scopes:
                    for owner in owners:
                        for mode in 0..<2:
                            if original(rows, scope, owner, mode == 1) != pma_visible_wildcard_import(&index, rows, scope, owner, mode == 1): return 2
            empty: mutable darray[Ast::EnumAnnotation] = []
            empty_index: mutable PrivateMemberIndex = PrivateMemberIndex{}
            pma_build_wildcard_import_index(empty, &empty_index)
            if pma_visible_wildcard_import(&empty_index, empty, "", "", false): return 3
            return 0

def main() -> i64 can[Memory.Allocate, Abort.Panic] = Semantic::exercise()
'''
with tempfile.TemporaryDirectory(prefix='private-wildcard-index-') as tmp:
 p=Path(tmp);(p/'test.elisa').write_text(source)
 compiler=os.environ.get('ELISACORE_BIN','/Users/torarinvikbjarko/.elisac/elisac-stage0')
 command=[compiler,'-O3','-emit','obj','-o',str(p/'test.o'),str(p/'test.elisa')]
 r=subprocess.run(command,capture_output=True,text=True,timeout=28)
 if r.returncode:raise SystemExit(r.stdout+r.stderr)
 (p/'hooks.c').write_text("""#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef struct { const void *data; intptr_t len; } View;
uint8_t ctx_string_view_index(View a, intptr_t i) { return ((const uint8_t*)a.data)[i]; }
int ctx_string_views_eq(View a, View b) { return a.len == b.len && a.len >= 0 && (!a.len || !memcmp(a.data,b.data,(size_t)a.len)); }
uint32_t elisa_profile_allocation_negotiate(uint32_t v) { return 0; }
uint32_t elisa_profile_region_layout_negotiate(uint32_t v) { return 0; }
void elisa_profile_region_layout_v1(uintptr_t a,size_t r,uintptr_t h,uintptr_t d,size_t c) {}
void elisa_profile_allocation_event_v1(uint32_t k,uintptr_t p,size_t s,uintptr_t q,size_t t,uintptr_t a,size_t r) {}
""")
 subprocess.run(['clang',str(p/'test.o'),str(p/'hooks.c'),'-o',str(p/'test')],check=True,timeout=28)
 subprocess.run([str(p/'test')],check=True,timeout=28)
 print('PASS indexed wildcard visibility matches full scans across 1536 scope, owner, and branch queries')
