#!/usr/bin/env python3
"""Build a development probe from production compiler functions and their call closure.

Usage: compiler_atom_slice.py ROOT.elisa PROBE.elisa OUTPUT.elisa
Keeps the standard runtime and all data declarations. Retains overloads by name and
protocol/impl members; removes other unreferenced function bodies. This is a focused
runtime test aid, not a replacement for compiling the complete compiler. Function
values passed indirectly may need an explicit reference in the probe to be retained.
"""
from pathlib import Path
import re,sys
root=Path(sys.argv[1]).resolve(); harness=Path(sys.argv[2]).read_text();out=Path(sys.argv[3]);seen=set()
def expand(path):
 path=path.resolve()
 if path in seen:return ''
 seen.add(path)
 if 'elisacore_std' in path.parts:return f'include "{path}"\n'
 parts=[]
 for line in path.read_text().splitlines(keepends=True):
  m=re.match(r'^include "([^"]+)"',line)
  parts.append(expand(path.parent/m[1]) if m else line)
 return ''.join(parts)+'\n'
s=expand(root);lines=s.splitlines(keepends=True);base=[];funcs=[];i=0;contexts=[];mandatory=set()
while i<len(lines):
 line=lines[i]
 if line.strip() and not line.lstrip().startswith('#'):
  line_indent=len(line)-len(line.lstrip())
  while contexts and contexts[-1][0]>=line_indent:contexts.pop()
 m=re.match(r'^( *)(?:(?:private|public) )?(?:ghost )?def ([A-Za-z_]\w*)',lines[i])
 if not m:
  if lines[i].rstrip().endswith(':'):contexts.append((len(lines[i])-len(lines[i].lstrip()),lines[i].strip()))
  base.append(lines[i]);i+=1;continue
 indent=len(m[1]);start=i;end=i+1
 while end<len(lines):
  l=lines[end]
  if l.strip() and not l.lstrip().startswith('#') and len(l)-len(l.lstrip())<=indent:break
  end+=1
 # Attach declaration decorators to the definition they describe.
 while base and (not base[-1].strip() or base[-1].lstrip().startswith('#')):base.pop()
 attrs=[]
 while base and re.match(r'^ {'+str(indent)+r'}@',base[-1]):attrs.insert(0,base.pop())
 body=''.join(attrs+lines[start:end]);key=len(funcs);
 if not lines[start].rstrip().endswith(':') or any(re.match(r'(?:protocol|interface|impl)\b',c[1]) for c in contexts):mandatory.add(key)
 funcs.append((m[2],body));base.append(f'__ATOM_FUNCTION_{key}__\n');i=end
# Remove the entrypoint from the source unit; the probe provides its own.
def refs(t):
 # Keep quoted text intact: a literal '#' must not hide calls later on the
 # same line. Match character literals narrowly so loop labels ('outer) do
 # not consume code. Keeping strings also conservatively retains references
 # in interpolated expressions.
 t=re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])'|#[^\n]*''',
          lambda m: '' if m[0].startswith('#') else m[0],t);found=set()
 for m in re.finditer(r'\b([A-Za-z_]\w*)\s*(?=[(\[])',t):
  pos=m.end()
  if t[pos]=='(':
   found.add(m[1]);continue
  depth=0
  while pos<len(t):
   if t[pos]=='[':depth+=1
   elif t[pos]==']':
    depth-=1
    if depth==0:
     pos+=1;break
   pos+=1
  while pos<len(t) and t[pos].isspace():pos+=1
  if pos<len(t) and t[pos]=='(':found.add(m[1])
 return found

base_text=''.join(base);needed=refs(re.sub(r'__ATOM_FUNCTION_\d+__','',base_text)+harness);kept=set();changed=True
while changed:
 changed=False
 for j,(name,body) in enumerate(funcs):
  if j not in kept and name!='main' and (j in mandatory or name in needed):
   kept.add(j);needed.update(refs(body));changed=True
s=re.sub(r'__ATOM_FUNCTION_(\d+)__\n',lambda m:funcs[int(m[1])][1] if int(m[1]) in kept else '',base_text)
# Remove visibility and module wrappers that became empty after pruning.
ll=s.splitlines();changed=True
while changed:
 changed=False;result=[]
 for i,l in enumerate(ll):
  if re.match(r'^ *(?:public|private|module [^:]+|extend [^:]+):\s*$',l):
   indent=len(l)-len(l.lstrip());nxt=next((x for x in ll[i+1:] if x.strip() and not x.lstrip().startswith('#')),None)
   if nxt is None or len(nxt)-len(nxt.lstrip())<=indent:
    if l.lstrip().startswith('module '):result.append(l);result.append(' '*(indent+4)+'const __compiler_atom_module_anchor: u32 = 0');continue
    changed=True;continue
  result.append(l)
 ll=result
# Pruning the last function from a static branch must not leave an empty suite.
# Keep its condition and else pairing intact with a compile-time-only anchor.
anchored=[]
for i,line in enumerate(result):
 anchored.append(line)
 if re.match(r'^ *static (?:if .+|elif .+|else):\s*$',line):
  indent=len(line)-len(line.lstrip())
  nxt=next((x for x in result[i+1:] if x.strip() and not x.lstrip().startswith('#')),None)
  if nxt is None or len(nxt)-len(nxt.lstrip())<=indent:
   anchored.append(' '*(indent+4)+f'const __compiler_atom_branch_anchor_{i}: u32 = 0')
out.write_text('\n'.join(anchored)+'\n'+harness)
print(f'{len(kept)}/{len(funcs)} functions; {len(s.splitlines())} lines; {out}')
