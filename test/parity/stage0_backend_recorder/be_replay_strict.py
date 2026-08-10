#!/usr/bin/env python3
"""STRICT replay: a source counts as covered only if stage1 compiles it AND declines
NO function.

The plain replay (be_replay.py) treats exit 0 as a match, but stage1 deliberately
continues past a function it cannot lower -- it records the name as `!elisa.declined`
module metadata and emits the rest. So a file whose function under test was silently
dropped still exits 0. With 286 of the 287 corpus sources having no `def main()`, that
gap matters: the whole point of those sources IS the function stage0 lowered.

Uses -emit llvm so the metadata is visible.
"""
import base64, subprocess, sys, tempfile, os, pathlib, collections, json, re

S = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("REPO_ROOT", os.path.abspath(os.path.join(S, "..", "..", "..")))
ORACLE = sys.argv[1]

rows = {}
for line in open(ORACLE):
    p = line.rstrip("\n").split("\t")
    if len(p) < 5 or int(p[1]) != 1:
        continue
    rows.setdefault((int(p[2]), base64.b64decode(p[3]).decode()), base64.b64decode(p[0]).decode())

print(f"strict replay over {len(rows)} stage0-lowered sources", file=sys.stderr)
res = collections.Counter()
dropped = []
failed = []
work = tempfile.mkdtemp()
for i, ((opt, src), fname) in enumerate(sorted(rows.items(), key=lambda kv: kv[1])):
    f = os.path.join(work, "case.elisa")
    pathlib.Path(f).write_text(src)
    out = os.path.join(work, "case.ll")
    try:
        p = subprocess.run(["bash", "scripts/elisac_stage1.sh", "-emit", "llvm", "-o", out, f],
                           cwd=REPO, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        res["gap"] += 1; failed.append(fname); continue
    if p.returncode != 0:
        res["gap"] += 1; failed.append(fname); continue
    ir = pathlib.Path(out).read_text() if os.path.exists(out) else ""
    names = re.findall(r'!\d+ = !\{!"([^"]+)"\}', ir)
    if "!elisa.declined" in ir:
        res["dropped"] += 1
        dropped.append((fname, names[:4]))
    else:
        res["covered"] += 1
    if (i + 1) % 40 == 0:
        print(f"  {i+1}/{len(rows)} covered={res['covered']} dropped={res['dropped']} gap={res['gap']}", file=sys.stderr)

print(f"\n=== STRICT: {len(rows)} sources — covered={res['covered']} "
      f"compiled-but-DROPPED-a-function={res['dropped']} failed={res['gap']} ===")
for f, n in dropped[:40]:
    print(f"  DROPPED {f}: {n}")
json.dump({"covered": res["covered"], "dropped": res["dropped"], "gap": res["gap"],
           "dropped_files": [f for f, _ in dropped], "failed_files": failed},
          open(os.path.join(S, "strict_result.json"), "w"), indent=1)
