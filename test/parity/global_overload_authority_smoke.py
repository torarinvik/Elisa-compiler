#!/usr/bin/env python3
"""Actual canonical parser/Semantic reporter controls; no source rewriting."""
import json, pathlib, re, subprocess, sys
reporter = sys.argv[1]
cases = json.loads(pathlib.Path(__file__).with_name("global_overload_authority_cases.json").read_text())
failed = 0
for case in cases:
    name, source, missing = case[:3]
    rows = case[3] if len(case) > 3 else None
    result = subprocess.run([reporter], input=("# rows\n" if rows is not None else "") + "# nopath\n" + source, text=True, capture_output=True)
    output = result.stdout + result.stderr
    parsed = re.search(r"^P 0$", output, re.M)
    family = missing.split(".")[0] if missing else None
    # The canonical authority checker reports a missing operation grant as
    # "add can Family.Member". Accept the older checker wording too so this
    # control remains useful across the reporter migration.
    missing_grant = (
        f"requires can[{family}" in output
        or f"add can {missing}" in output
    ) if missing else False
    good = result.returncode == 0 and parsed and (re.search(r"^D 0$", output, re.M) if not missing else missing_grant and re.search(rf"\b{re.escape(missing.split('.')[-1])}\b", output) and re.search(r"^S 1$", output, re.M))
    if rows is not None:
        actual_rows = {}
        for function, ref, mandatory in re.findall(r"^R (\S+) (\S+) ([01])$", output, re.M):
            actual_rows.setdefault(function, set()).add((ref, int(mandatory)))
        good = good and all(actual_rows.get(function, set()) == {(ref, mandatory) for ref, mandatory in expected} for function, expected in rows.items())
    print(("PASS " if good else "FAIL ") + name)
    if not good:
        failed += 1
        print(output)
print(f"overload authority: {len(cases)-failed}/{len(cases)} PASS")
sys.exit(bool(failed))
