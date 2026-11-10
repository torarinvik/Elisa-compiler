#!/usr/bin/env python3
"""Exercise nested guard configuration through the real self-host wrappers."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="self-host-budget-") as work:
    work = Path(work)
    fake = work / "compiler"
    fake.write_text('#!/bin/bash\nprintf "%s" "$ELISA_STAGE1_MAX_RSS_KB" > "$BUDGET_RESULT"\nexit 17\n')
    fake.chmod(0o755)
    cases = [({}, "8388608"),
             ({"ELISA_SELF_HOST_GEN2_MAX_RSS_KB": "16777216"}, "16777216"),
             ({"ELISA_SELF_HOST_GEN2_MAX_RSS_KB": "16777216", "ELISA_STAGE1_MAX_RSS_KB": "4194304"}, "4194304")]
    for index, (settings, expected) in enumerate(cases):
        env = dict(os.environ)
        env.pop("ELISA_STAGE1_MAX_RSS_KB", None)
        env.pop("ELISA_SELF_HOST_GEN2_MAX_RSS_KB", None)
        result = work / f"budget-{index}"
        env.update(settings, ELISA_STAGE1_BIN=str(fake), BUDGET_RESULT=str(result))
        run = subprocess.run(["bash", str(root / "scripts/self_host_gen2.sh"), str(work / f"out-{index}")],
                             cwd=root, env=env, capture_output=True, text=True, timeout=10)
        if run.returncode != 17 or not result.exists() or result.read_text() != expected:
            raise SystemExit(f"budget propagation failed: {settings}\n{run.stdout}{run.stderr}")

    fake.write_text("#!/bin/bash\nexec /bin/sleep 60\n")
    env.pop("ELISA_SELF_HOST_GEN2_TIMEOUT_WRAPPED", None)
    run = subprocess.run(
        ["bash", str(root / "scripts/self_host_gen2.sh"), str(work / "deadline")],
        cwd=root, env=env, capture_output=True, text=True, timeout=8,
    )
    if run.returncode != 124 or "deadline exceeded (5s)" not in run.stderr:
        raise SystemExit(f"direct self-host deadline failed\n{run.stdout}{run.stderr}")
print("PASS nested memory budgets and the direct five-second deadline")
