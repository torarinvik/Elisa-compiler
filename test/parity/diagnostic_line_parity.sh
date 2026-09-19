#!/usr/bin/env bash
# Diagnostic LINE parity. diagnostics_diff compares MESSAGES with the location prefix
# stripped and as a SET, so two things pass it byte-for-byte: a stage1 diagnostic that
# names the right rule at the wrong LINE, and a message stage1 emits fewer times than
# stage0 when at least one copy survives. diagnostic_columns_smoke.sh owns the column
# span; this gate owns the line and the count.
#
# HOW IT SCORES. Per fixture, per distinct message, the two compilers' LINE MULTISETS are
# compared. A stage0 row that stage1 does not match is a defect — but only for messages
# stage1 emits SOMEWHERE in that fixture: a sentence stage1 never produces is
# diagnostics_diff's business, and counting it here would make one gap fail two gates with
# two different numbers. stage1 may say MORE than stage0 (it has supplemental
# diagnostics), so extra rows are not defects.
#
# RATCHETED DOWNWARD: the defect count must not exceed
# test/fixtures/diagnostic_line_parity.baseline. Lower it as cases close; never raise it.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
FIXTURES="${DIAGNOSTIC_DIFF_FIXTURES:-$REPO_ROOT/test/fixtures/diagnostics}"
BASELINE="$REPO_ROOT/test/fixtures/diagnostic_line_parity.baseline"

source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

ELISACORE_BIN="$ELISACORE_BIN" \
ELISA_PARSE_REPORT="${ELISA_PARSE_REPORT:-$REPO_ROOT/build/parse_report}" \
LINE_PARITY_FIXTURES="$FIXTURES" LINE_PARITY_BASELINE="$BASELINE" \
python3 - <<'PYEOF'
import os, re, subprocess, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

STAGE0 = os.environ["ELISACORE_BIN"]
REPORT = os.environ["ELISA_PARSE_REPORT"]
FIXTURES = os.environ["LINE_PARITY_FIXTURES"]
BASELINE = os.environ["LINE_PARITY_BASELINE"]
VERBOSE = os.environ.get("ELISA_LINE_PARITY_VERBOSE", "1") != "0"

# `path:LINE:COL[-COL[:LINE]]: message`, and the `path:LINE: message` short form.
STAGE0_ROW = re.compile(r"^[^:]*:(\d+)(?::\d+(?:-\d+(?::\d+)?)?)?: (.*)$")
STAGE1_ROW = re.compile(r"^  L(\d+) (.*)$")

def stage0_rows(path):
    proc = subprocess.run([STAGE0, "-emit", "semantic", path],
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    rows = Counter()
    for raw in proc.stderr.decode("utf-8", "replace").splitlines():
        match = STAGE0_ROW.match(raw)
        if not match:
            continue
        message = match.group(2)
        # Warnings and notes are not errors, and stage1's reporter does not carry them.
        if message.startswith("warning: ") or message.startswith("note: "):
            continue
        rows[(int(match.group(1)), message)] += 1
    return rows

def stage1_rows(path):
    with open(path, "rb") as handle:
        proc = subprocess.run([REPORT], stdin=handle,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    rows, in_diagnostics = Counter(), False
    for raw in proc.stdout.decode("utf-8", "replace").splitlines():
        if re.match(r"^D \d+$", raw):
            in_diagnostics = True
            continue
        if not in_diagnostics:
            continue
        match = STAGE1_ROW.match(raw)
        if match:
            rows[(int(match.group(1)), match.group(2))] += 1
    return rows

def compare(path):
    s0 = stage0_rows(path)
    if not s0:
        return 0, 0, []
    s1 = stage1_rows(path)
    spoken = {message for (_, message) in s1}          # messages stage1 emits at all
    total = agree = 0
    defects = []
    for (line, message), count in sorted(s0.items()):
        if message not in spoken:
            continue                                    # diagnostics_diff's business
        total += count
        matched = min(count, s1[(line, message)])
        agree += matched
        for _ in range(count - matched):
            elsewhere = sorted({l for (l, m) in s1 if m == message})
            defects.append((os.path.basename(path), line, elsewhere, message))
    return total, agree, defects

paths = sorted(os.path.join(FIXTURES, name)
               for name in os.listdir(FIXTURES) if name.endswith(".elisa"))
workers = min(8, (os.cpu_count() or 4))
total = agree = 0
all_defects = []
with ThreadPoolExecutor(max_workers=workers) as pool:
    for fixture_total, fixture_agree, defects in pool.map(compare, paths):
        total += fixture_total
        agree += fixture_agree
        all_defects.extend(defects)

if VERBOSE:
    for name, line, elsewhere, message in all_defects:
        where = ",".join(str(l) for l in elsewhere) or "-"
        sys.stderr.write("LINE %s: stage0=%d stage1=%s | %s\n" % (name, line, where, message[:90]))

try:
    baseline = int(open(BASELINE).read().strip())
except (IOError, ValueError):
    baseline = 0
print("diagnostic line parity: %d stage0 messages, %d agree, %d at the wrong line or missing "
      "a repeat (ratchet <= %d)" % (total, agree, len(all_defects), baseline))
if len(all_defects) > baseline:
    sys.stderr.write("diagnostic line parity FAILED: %d defect(s) exceeds the ratchet %d\n"
                     % (len(all_defects), baseline))
    sys.exit(1)
if len(all_defects) < baseline:
    print("  ratchet can be lowered to %d (edit %s)" % (len(all_defects), BASELINE))
PYEOF
