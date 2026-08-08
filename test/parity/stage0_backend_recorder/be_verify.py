#!/usr/bin/env python3
"""Cross-check the stage1 gap set against stage0's CLI, to separate real feature
gaps from in-process-test-only artifacts."""
import base64, subprocess, sys, tempfile, os, pathlib, collections, json

S = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("REPO_ROOT", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
STAGE0 = os.path.expanduser("~/.elisac/elisac")

gapnames = set()
for line in open(os.path.join(S, "be_full.txt")):
    if line.startswith("--- GAP "):
        gapnames.add(line.split()[2])

rows = {}
for line in open(os.path.join(S, "be_oracle.tsv")):
    p = line.rstrip("\n").split("\t")
    if len(p) < 5 or int(p[1]) != 1:
        continue
    f = base64.b64decode(p[0]).decode()
    if f in gapnames:
        rows.setdefault(f, base64.b64decode(p[3]).decode())

print(f"cross-checking {len(rows)} gap sources against stage0 CLI", file=sys.stderr)
work = tempfile.mkdtemp()
real, artifact = [], []
for i, (f, src) in enumerate(sorted(rows.items())):
    p = os.path.join(work, "c.elisa")
    pathlib.Path(p).write_text(src)
    o = os.path.join(work, "c.o")
    try:
        r = subprocess.run([STAGE0, "-emit", "obj", "-O0", "-o", o, p],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        artifact.append((f, "stage0 TIMEOUT", src)); continue
    if r.returncode == 0:
        real.append((f, src))
    else:
        artifact.append((f, (r.stderr or r.stdout).strip()[:200], src))
    if (i + 1) % 25 == 0:
        print(f"  {i+1}/{len(rows)} real={len(real)} artifact={len(artifact)}", file=sys.stderr)

print(f"\n=== REAL gaps (stage0 CLI compiles, stage1 does not): {len(real)}")
for f, _ in real:
    print("  ", f)
print(f"\n=== artifacts (stage0 CLI also fails): {len(artifact)}")
for f, e, _ in artifact:
    print("  ", f, "|", e.replace("\n", " ")[:120])

json.dump({"real": [{"file": f, "src": s} for f, s in real],
           "artifact": [{"file": f, "err": e} for f, e, _ in artifact]},
          open(os.path.join(S, "be_verified.json"), "w"), indent=1)
