#!/usr/bin/env python3
"""Compare recorded semantic phases without treating truncated spans as completed.

Inputs must be from source-matched runs to attribute differences to build options.
Independent authority spans are excluded from the sequential sem:* subtotal.
"""
import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import re

TIMING = re.compile(r"^stage1-timing: (\S+) wall_ms=([\d.]+) cpu_ms=([\d.]+)$")
COUNTER = re.compile(r"^stage1-counter: authority:(report|inference|summary)_functions_progress count=(\d+)$")


@dataclass
class Profile:
    phases: dict = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0]))
    preauthority: list = field(default_factory=lambda: [0.0, 0.0])
    progress: dict = field(default_factory=lambda: defaultdict(list))
    summary_round_wall: list = field(default_factory=list)
    last_phase: str = "none"
    unfinished: str = "not established"


def parse_profile(source):
    result = Profile()
    authority_started = summary_finished = False
    for line in source.splitlines():
        match = TIMING.fullmatch(line)
        if match:
            name, wall, cpu = match.groups()
            values = float(wall), float(cpu)
            result.last_phase = name
            for index, value in enumerate(values):
                result.phases[name][index] += value
                if not authority_started and name.startswith("sem:"):
                    result.preauthority[index] += value
            if name == "authority:return_summary_round":
                result.summary_round_wall.append(values[0])
            if name == "authority:collect_setup":
                authority_started = True
                result.unfinished = "return summaries (no end row observed)"
            elif name == "authority:return_summaries":
                summary_finished = True
                result.unfinished = "inference (no end row observed)"
            elif name == "authority:inference_walk":
                result.unfinished = "after inference; inspect last completed phase"
            elif name in ("sem:check_global_authority", "sem:check_mutable_global_authority"):
                result.unfinished = "authority completed"
            continue
        match = COUNTER.fullmatch(line)
        if match:
            kind, count = match.groups()
            # Historical counters used 'report' for quiet summary walks too.
            if kind == "report" and authority_started and not summary_finished:
                kind = "summary"
            count = int(count)
            runs = result.progress[kind]
            if not runs or count <= runs[-1]:
                runs.append(count)
            else:
                runs[-1] = count
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()
    profiles = [parse_profile(path.read_text()) for path in (args.before, args.after)]
    for label, profile in zip(("before", "after"), profiles):
        print(f"{label}: sequential sem:* before authority: wall={profile.preauthority[0]:.1f}ms cpu={profile.preauthority[1]:.1f}ms")
        print(f"  last completed row: {profile.last_phase}; {profile.unfinished}")
        if profile.summary_round_wall:
            print(f"  recorded summary round wall times (ms): {profile.summary_round_wall}")
        for kind, runs in sorted(profile.progress.items()):
            print(f"  {kind}: {len(runs)} observed sweep(s), function-count lower bounds {runs}")
    common = profiles[0].phases.keys() & profiles[1].phases.keys()
    names = sorted(common, key=lambda name: abs(profiles[1].phases[name][0] - profiles[0].phases[name][0]), reverse=True)
    print("\nCompleted rows in both logs (wall milliseconds; nested spans are not additive):")
    print("before    after     delta  phase")
    for name in names[:max(0, args.top)]:
        before, after = (profile.phases[name][0] for profile in profiles)
        print(f"{before:8.1f} {after:8.1f} {after-before:+9.1f}  {name}")
    for label, own, other in (("before", profiles[0], profiles[1]), ("after", profiles[1], profiles[0])):
        missing = sorted(own.phases.keys() - other.phases.keys())
        if missing:
            print(f"Completed only in {label}: {', '.join(missing)}")
    print("No whole-run speedup is established by truncated logs; verify matching source/input independently.")


if __name__ == "__main__":
    main()
