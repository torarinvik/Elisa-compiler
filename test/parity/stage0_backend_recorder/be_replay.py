#!/usr/bin/env python3
"""Replay stage0's backend-lowering corpus through stage1 and report gaps."""
import base64, subprocess, sys, tempfile, os, pathlib, collections

ORACLE = sys.argv[1]
REPO = os.environ.get("REPO_ROOT", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0

rows = {}
for line in open(ORACLE):
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 5:
        continue
    fname = base64.b64decode(parts[0]).decode()
    ok, opt = int(parts[1]), int(parts[2])
    src = base64.b64decode(parts[3]).decode()
    if ok != 1:
        continue
    rows.setdefault((opt, src), fname)

items = list(rows.items())
if LIMIT:
    items = items[:LIMIT]
print(f"replaying {len(items)} stage0-lowered sources", file=sys.stderr)

results = collections.Counter()
gaps = []
work = tempfile.mkdtemp()
for i, ((opt, src), fname) in enumerate(items):
    f = os.path.join(work, "case.elisa")
    pathlib.Path(f).write_text(src)
    out = os.path.join(work, "case.o")
    try:
        p = subprocess.run(
            ["bash", "scripts/elisac_stage1.sh", "-o", out, f],
            cwd=REPO, capture_output=True, text=True, timeout=120)
        rc, err = p.returncode, (p.stderr or p.stdout)
    except subprocess.TimeoutExpired:
        rc, err = -99, "TIMEOUT"
    if rc == 0:
        results["match"] += 1
    else:
        results["gap"] += 1
        gaps.append((fname, rc, err.strip()[:400], src))
    if (i + 1) % 25 == 0:
        print(f"  {i+1}/{len(items)} match={results['match']} gap={results['gap']}", file=sys.stderr)

print(f"\n=== stage0 lowered {len(items)}; stage1 match={results['match']} gap={results['gap']} ===")
for fname, rc, err, src in gaps:
    print(f"\n--- GAP {fname} (rc={rc})\n{err}")
import json
json.dump([{"file": f, "rc": rc, "err": e, "src": s} for f, rc, e, s in gaps],
          open(os.path.join(os.path.dirname(ORACLE), "be_gaps.json"), "w"), indent=1)
