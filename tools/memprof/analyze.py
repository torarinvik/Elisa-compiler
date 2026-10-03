#!/usr/bin/env python3
"""Analyze elisa_memprof output.
usage: analyze.py BINARY PROFILE [--live] [--depth N] [--top N]
Prints top allocating functions (inclusive, by sampled bytes), and with --live only the
samples whose arena was still alive at the RSS peak.
"""
import sys, subprocess, collections, re, argparse

ap = argparse.ArgumentParser()
ap.add_argument('binary'); ap.add_argument('profile')
ap.add_argument('--live', action='store_true')
ap.add_argument('--depth', type=int, default=6)
ap.add_argument('--top', type=int, default=40)
ap.add_argument('--skip', default=r'^(arena_|darray_|elisa_|Elisacore|collection_|new_region|sview_|__|backtrace)')
a = ap.parse_args()

events = []
for line in open(a.profile):
    p = line.split()
    if not p: continue
    events.append(p)

# RSS peak index
peak_i, peak_rss = len(events), 0
for i, p in enumerate(events):
    if p[0] == 'R':
        rss = int(p[3].split('=')[1])
        if rss > peak_rss: peak_rss, peak_i = rss, i
print(f'peak rss sample: {peak_rss} MB at event {peak_i}/{len(events)}')
for p in events:
    if p[0] == 'SUMMARY': print(' '.join(p))

samples = []  # (weight, arena, addrs, alive)
alive_gen = {}  # arena -> generation
gen = collections.defaultdict(int)
owner = {}
def find(x):
    while x in owner: x = owner[x]
    return x
sample_meta = []
by_key = collections.defaultdict(list)
for i, p in enumerate(events):
    if i > peak_i and a.live: break
    if p[0] == 'S' and p[1] in 'AI':
        ar = p[3]
        m = [int(p[2]), ar, gen[ar], p[4:]]
        sample_meta.append(m); by_key[(ar, gen[ar])].append(m)
    elif p[0] == 'F':
        gen[p[1]] += 1
    elif p[0] == 'M':
        child, parent = p[1], p[2]
        # samples of child now belong to parent: relabel lazily
        moved = by_key.pop((child, gen[child]), [])
        for s in moved:
            s[1] = parent; s[2] = gen[parent]
        by_key[(parent, gen[parent])].extend(moved)
        gen[child] += 1

if a.live:
    sample_meta = [s for s in sample_meta if gen[s[1]] == s[2]]

addrs = set()
for s in sample_meta: addrs.update(s[3][:40])
addrs = sorted(addrs)
sym = {}
if addrs:
    out = subprocess.run(['llvm-symbolizer', '--obj=' + a.binary, '--functions=linkage', '--no-inlines', '-C'],
                         input='\n'.join('0x' + x for x in addrs), capture_output=True, text=True).stdout
    blocks = out.strip('\n').split('\n\n')
    for x, b in zip(addrs, blocks):
        sym[x] = b.split('\n')[0]

skip = re.compile(a.skip)
incl = collections.Counter(); selfc = collections.Counter(); stacks = collections.Counter()
total = 0
for w, ar, g, st in sample_meta:
    total += w
    names = [sym.get(x, x) for x in st]
    user = [n for n in names if not skip.search(n)]
    for n in set(user): incl[n] += w
    if user: selfc[user[0]] += w
    stacks[' < '.join(user[:a.depth])] += w
mb = lambda b: b / 1048576
print(f'total sampled: {mb(total):.0f} MB ({"live at peak" if a.live else "all allocations"})')
print('\n== top self (first non-runtime frame)')
for n, w in selfc.most_common(a.top): print(f'{mb(w):9.0f} MB  {n}')
print('\n== top inclusive')
for n, w in incl.most_common(a.top): print(f'{mb(w):9.0f} MB  {n}')
print('\n== top stacks')
for n, w in stacks.most_common(a.top): print(f'{mb(w):9.0f} MB  {n}')
