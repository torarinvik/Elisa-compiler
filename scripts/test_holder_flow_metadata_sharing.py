#!/usr/bin/env python3
"""Compile real holder-flow cloning helpers and exercise ownership/isolation invariants."""
import os, re, subprocess, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
text=(root/'src/semantic/check_call_holder_view_store.elisa').read_text()
def section(name):
    start=text.index('        def '+name+'(')
    end=re.search(r'\n        (?:def |#)',text[start+1:])
    return text[start:start+1+end.start()]+'\n'
start=text.index('        struct CHVScalarFields:')
end=text.index('        def chv_flow_latest(',start)
helpers=text[start:end]+''.join(section(name) for name in ('chv_flow_latest','chv_flow_clone','chv_flow_has_lmut_rebind_claim','chv_flow_bind'))
mutable_fields=re.findall(r'^            (\w+): mutable darray\[',text[start:end],re.M)
checks=''
for i,field in enumerate(mutable_fields):
    checks+='            if branch.'+field+'.count != parent.'+field+'.count: return '+str(10+i)+'\n'
    checks+='            if (&branch.'+field+'[0]).cast[uintptr] == (&parent.'+field+'[0]).cast[uintptr]: return '+str(40+i)+'\n'
source='include "'+str(root/'elisacore_std/collections.elisa')+'"\n'+'''module Ast:
    public:
        type Expr = i64
        struct EnumAnnotation:
            owner: sview = ""
            name: sview = ""
            line: u32 = 0
module Semantic:
    public:
'''+helpers+'''
        def exercise() -> i64 can[Memory.Allocate, Abort.Panic, Unsafe.PointerCast]:
            parent: mutable CHVViewFlow = CHVViewFlow{rebind_claims: [Ast::EnumAnnotation{owner: "__lmut_rebind_claim", name: "x", line: 7}], reference_holders: ["Holder"], type_alias_names: ["Alias"], type_alias_targets: [42], scalar_type_mask: 32767, scalar_calls: CHVScalarCalls{names: ["count_value"], shadow_names: ["local"], fields: CHVScalarFields{owners: ["Packet"], names: ["value"]}}}
            chv_flow_bind(&parent, "x", true, false, true)
            parent.shape_shadow_names.push("shadow")
            parent.last_value_may_be_owned_view <- true
            branch: mutable CHVViewFlow = chv_flow_clone(&parent)
            sibling: mutable CHVViewFlow = chv_flow_clone(&parent)
'''+checks+'''
            if not chv_flow_has_lmut_rebind_claim(&branch, "x", 7): return 1
            if branch.reference_holders[0] != "Holder" or branch.type_alias_names[0] != "Alias" or branch.type_alias_targets[0] != 42: return 2
            if (&branch.rebind_claims[0]).cast[uintptr] != (&parent.rebind_claims[0]).cast[uintptr]: return 3
            if (&branch.reference_holders[0]).cast[uintptr] != (&parent.reference_holders[0]).cast[uintptr]: return 4
            if (&branch.type_alias_names[0]).cast[uintptr] != (&parent.type_alias_names[0]).cast[uintptr]: return 5
            if (&branch.type_alias_targets[0]).cast[uintptr] != (&parent.type_alias_targets[0]).cast[uintptr]: return 6
            if branch.scalar_type_mask != parent.scalar_type_mask or sibling.scalar_type_mask != 32767: return 9
            if branch.scalar_calls.names[0] != "count_value" or branch.scalar_calls.shadow_names[0] != "local": return 90
            if (&branch.scalar_calls.names[0]).cast[uintptr] != (&parent.scalar_calls.names[0]).cast[uintptr]: return 91
            if branch.scalar_calls.fields.owners[0] != "Packet" or branch.scalar_calls.fields.names[0] != "value": return 93
            if (&branch.scalar_calls.fields.owners[0]).cast[uintptr] != (&parent.scalar_calls.fields.owners[0]).cast[uintptr]: return 94
            branch.scalar_calls <- CHVScalarCalls{}
            if parent.scalar_calls.names.count != 1 or sibling.scalar_calls.names.count != 1: return 92
            branch.owned[0] <- false
            branch.may_alias_reference[0] <- false
            branch.names[0] <- "branch"
            branch.shape_shadow_names[0] <- "branch-shadow"
            branch.last_value_may_be_owned_view <- false
            if not parent.owned[0] or not sibling.owned[0] or not parent.may_alias_reference[0] or not sibling.may_alias_reference[0]: return 7
            if parent.names[0] != "x" or sibling.names[0] != "x" or parent.shape_shadow_names[0] != "shadow" or not parent.last_value_may_be_owned_view: return 8
            return 0

def main() -> i64 can[Memory.Allocate, Abort.Panic, Unsafe.PointerCast] = Semantic::exercise()
'''
with tempfile.TemporaryDirectory(prefix='holder-flow-sharing-') as tmp:
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
 (p/'negative.elisa').write_text(source.replace('            return 0\n', '            branch.reference_holders.push("forbidden")\n            return 0\n', 1))
 negative=subprocess.run([compiler,'-O0','-emit','llvm','-o',os.devnull,str(p/'negative.elisa')],capture_output=True,text=True,timeout=28)
 if negative.returncode == 0 or 'darray push requires a mutable darray receiver' not in negative.stderr.lower():
  raise SystemExit('metadata mutation was not rejected for immutability: '+negative.stderr)
 print('PASS immutable metadata sharing, independent branch facts, and forbidden metadata mutation')
