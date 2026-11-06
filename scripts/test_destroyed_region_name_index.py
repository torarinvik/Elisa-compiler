#!/usr/bin/env python3
"""Exercise the actual indexed and scan helpers with collisions and visibility cases."""
import os,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=(root/'src/semantic/check_destroyed_region.elisa').read_text()
a=s.index('        struct DestroyedRegionNameIndex:');b=s.index('        # Legacy spelling query',a)
helpers=s[a:b]
source='include "'+str(root/'elisacore_std/collections.elisa')+'"\n'+'''module Ast:
    public:
        struct LocalRegionAnnotation:
            name: sview = ""
            region: sview = ""
            line: u32 = 0
            owner_offset: u32 = 0
            end_offset: u32 = 0
            type_expression: bool = false
module Semantic:
    public:
        const SYMBOL_INDEX_ROW_NONE: u32 = 4294967295
        const NO_REGION_BINDING: u32 = 0
        # Force collisions to check that the index is never identity evidence.
        def name_hash(name: sview) -> u64 = 1
        def local_type_cannot_carry_region(value: bool) -> bool = value
        def region_binding_id_at(annotations: darray[Ast::LocalRegionAnnotation]&, region: sview, function_line: u32, use_line: u32, use_offset: u32, known: bool) -> u32 = use_offset + 1
        def region_annotation_window_start(annotations: darray[Ast::LocalRegionAnnotation]&, line: u32) -> usize = 0
        def region_annotation_window_end(annotations: darray[Ast::LocalRegionAnnotation]&, line: u32) -> usize = annotations.count
        def region_annotation_offset_window_end(annotations: darray[Ast::LocalRegionAnnotation]&, offset: u32) -> usize = annotations.count
'''+helpers+'''
        def exercise() -> i64 can[Memory.Allocate, Abort.Panic, Global{Read,Write}]:
            rows: mutable darray[Ast::LocalRegionAnnotation] = []
            for i in 0..<16:
                rows.push(Ast::LocalRegionAnnotation{name: "x" if i % 2 == 0 else "y", region: "r" if i % 3 != 0 else "", line: (i % 5).u32(), owner_offset: (i * 4).u32(), end_offset: (i * 4 + 9).u32() if i % 3 != 0 else 0, type_expression: i % 4 == 0})
            index: mutable DestroyedRegionNameIndex = DestroyedRegionNameIndex{}
            destroyed_build_region_name_index(rows, &index) can Global{Read,Write}
            names: darray[sview] = ["x", "y", "missing"]
            for offset in 0..<70:
                for line in 0..<7:
                    for mode in 0..<2:
                        for name in names:
                            before: mutable darray[u32] = [99]
                            after: mutable darray[u32] = [99]
                            function_regions_of_name(rows, name, 1, line.u32(), &before, offset.u32(), mode == 1) can Global{Read,Write}
                            destroyed_indexed_function_regions_of_name(&index, rows, name, 1, line.u32(), &after, offset.u32(), mode == 1) can Global{Read,Write}
                            if before.count != after.count: return 1
                            for i in 0..<before.count:
                                if before[i] != after[i]: return 2
            filtered: mutable darray[Ast::LocalRegionAnnotation] = []
            for i in 0..<rows.count:
                if i % 3 == 1: filtered.push(rows[i])
            filtered_index: mutable DestroyedRegionNameIndex = DestroyedRegionNameIndex{}
            destroyed_build_region_name_index(filtered, &filtered_index) can Global{Read,Write}
            for offset in 0..<70:
                for name in names:
                    before: mutable darray[u32] = []
                    after: mutable darray[u32] = []
                    function_regions_of_name(filtered, name, 1, 5, &before, offset.u32(), true) can Global{Read,Write}
                    destroyed_indexed_function_regions_of_name(&filtered_index, filtered, name, 1, 5, &after, offset.u32(), true) can Global{Read,Write}
                    if before.count != after.count: return 3
                    for i in 0..<before.count:
                        if before[i] != after[i]: return 4
            return 0

def main() -> i64 can[Memory.Allocate, Abort.Panic, Global{Read,Write}] = Semantic::exercise() can Global{Read,Write}
'''
with tempfile.TemporaryDirectory(prefix='region-name-index-') as tmp:
 p=Path(tmp);(p/'test.elisa').write_text(source)
 compiler=os.environ.get('ELISACORE_BIN','/Users/torarinvikbjarko/.elisac/elisac-stage0')
 command=[compiler,'-O3','-emit','obj','-o',str(p/'test.o'),str(p/'test.elisa')]
 r=subprocess.run(command,capture_output=True,text=True,timeout=28)
 if r.returncode:raise SystemExit(r.stdout+r.stderr)
 (p/'hooks.c').write_text("""#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef struct { const void *data; intptr_t len; } View;
int ctx_string_views_eq(View a, View b) { return a.len == b.len && a.len >= 0 && (!a.len || !memcmp(a.data,b.data,(size_t)a.len)); }
uint32_t elisa_profile_allocation_negotiate(uint32_t v) { return 0; }
uint32_t elisa_profile_region_layout_negotiate(uint32_t v) { return 0; }
void elisa_profile_region_layout_v1(uintptr_t a,size_t r,uintptr_t h,uintptr_t d,size_t c) {}
void elisa_profile_allocation_event_v1(uint32_t k,uintptr_t p,size_t s,uintptr_t q,size_t t,uintptr_t a,size_t r) {}
""")
 subprocess.run(['clang',str(p/'test.o'),str(p/'hooks.c'),'-o',str(p/'test')],check=True,timeout=28)
 subprocess.run([str(p/'test')],check=True,timeout=28)
 print('PASS 3150 indexed/scan comparisons with collisions, shadowing, expiry, scalar and empty regions')
