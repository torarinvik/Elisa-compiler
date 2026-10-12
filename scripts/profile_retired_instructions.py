#!/usr/bin/env python3
"""Run a macOS command under Instruments Processor Trace and report retired work.

Usage:
    python3 scripts/profile_retired_instructions.py [--trace /tmp/run.trace] -- \
        bin/elisac-stage1 -emit ir -O2 test/bench/example.elisa

Pass target-only environment variables before `--`, repeating `--env NAME=VALUE`
as needed (for example, for a dynamic-library search path).

The executable is copied into a private temporary directory and ad-hoc signed
with com.apple.security.get-task-allow so Processor Trace can attach. The copy,
trace and exported XML are removed after the run unless --trace is supplied.
The count covers the launched process; child processes are excluded. Prefer a
single-process compiler mode such as `-emit check` for compiler comparisons.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def run_checked(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, **kwargs)


def export_trace(trace: Path, destination: Path, *, toc: bool) -> None:
    command = ["xcrun", "xctrace", "export", str(trace)]
    command.append("--toc" if toc else "--xpath")
    if not toc:
        command.append('/trace-toc/run/data/table[@schema="processor-trace-intervals"]')
    command.extend(["--output", str(destination)])
    run_checked(command, stdout=subprocess.DEVNULL)


def configure_xcode() -> None:
    candidates: list[Path] = []
    selected = os.environ.get("DEVELOPER_DIR")
    if selected:
        candidates.append(Path(selected))
    if shutil.which("xcode-select"):
        result = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            candidates.append(Path(result.stdout.strip()))
    applications = Path("/Applications")
    if applications.is_dir():
        candidates.extend(app / "Contents/Developer" for app in applications.glob("Xcode*.app"))
    for candidate in candidates:
        if (candidate / "usr/bin/xctrace").is_file():
            os.environ["DEVELOPER_DIR"] = str(candidate)
            return
    raise RuntimeError("Xcode with the xctrace Processor Trace template is required")


def process_target(toc_path: Path) -> tuple[str, str, str, str]:
    root = ET.parse(toc_path).getroot()
    target = root.find('./run/info/target/process[@type="launched"]')
    if target is None:
        raise RuntimeError("Processor Trace did not record a launched target process")
    name = target.attrib.get("name", "")
    pid = target.attrib.get("pid", "")
    exit_status = target.attrib.get("return-exit-status", "")
    end_reason_node = root.find("./run/info/summary/end-reason")
    end_reason = end_reason_node.text if end_reason_node is not None and end_reason_node.text else ""
    if not name or not pid:
        raise RuntimeError("Processor Trace output is missing the target name or pid")
    return name, pid, exit_status, end_reason


def instruction_totals(intervals_path: Path, name: str, pid: str) -> tuple[int, int, int]:
    processes: dict[str, str] = {}
    numbers: dict[str, int] = {}
    instructions = 0
    cycles = 0
    interval_count = 0
    uint64_columns: dict[str, int] | None = None
    stack: list[ET.Element] = []
    target_label = f"{name} ({pid})"

    for event, element in ET.iterparse(intervals_path, events=("start", "end")):
        if event == "start":
            stack.append(element)
            continue

        if element.tag == "process" and "id" in element.attrib:
            processes[element.attrib["id"]] = element.attrib.get("fmt", "")
        elif element.tag == "uint64" and "id" in element.attrib:
            numbers[element.attrib["id"]] = int(element.text or "0")
        elif element.tag == "schema" and element.attrib.get("name") == "processor-trace-intervals":
            uint64_columns = {}
            for column in element.findall("./col"):
                if column.findtext("engineering-type") != "uint64":
                    continue
                mnemonic = column.findtext("mnemonic") or ""
                if mnemonic in uint64_columns:
                    raise RuntimeError(f"Processor Trace schema repeats the {mnemonic!r} counter column")
                uint64_columns[mnemonic] = len(uint64_columns)
            if "self-instructions" not in uint64_columns or "self-cycles" not in uint64_columns:
                raise RuntimeError("Processor Trace schema is missing self-instructions or self-cycles counters")
        elif element.tag == "row":
            process = element.find("./process")
            values = element.findall("./uint64")
            if process is not None:
                if uint64_columns is None:
                    raise RuntimeError("Processor Trace data rows appeared before their counter schema")
                process_id = process.attrib.get("ref") or process.attrib.get("id", "")
                if processes.get(process_id) == target_label:
                    instruction_index = uint64_columns["self-instructions"]
                    cycle_index = uint64_columns["self-cycles"]
                    if instruction_index >= len(values) or cycle_index >= len(values):
                        raise RuntimeError("Processor Trace row has fewer counters than its schema")
                    instruction_value = numbers.get(values[instruction_index].attrib.get("ref", ""))
                    cycle_value = numbers.get(values[cycle_index].attrib.get("ref", ""))
                    if instruction_value is None and values[instruction_index].text is not None:
                        instruction_value = int(values[instruction_index].text)
                    if cycle_value is None and values[cycle_index].text is not None:
                        cycle_value = int(values[cycle_index].text)
                    if instruction_value is None or cycle_value is None:
                        raise RuntimeError("Processor Trace row references an unknown counter value")
                    instructions += instruction_value
                    cycles += cycle_value
                    interval_count += 1

        if stack:
            stack.pop()
            if element.tag == "row" and stack:
                stack[-1].remove(element)
                element.clear()
            elif element.tag == "node":
                element.clear()

    if uint64_columns is None:
        raise RuntimeError("Processor Trace output has no processor-trace-intervals schema")
    if interval_count == 0:
        raise RuntimeError(f"No Processor Trace intervals found for {target_label}")
    return instructions, cycles, interval_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, help="keep the .trace bundle at this path")
    parser.add_argument("--time-limit", default="30m", help="maximum trace duration (default: 30m)")
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="set an environment variable for the traced process (repeatable)",
    )
    args, remainder = parser.parse_known_args()
    command = remainder[1:] if remainder and remainder[0] == "--" else remainder
    if not command:
        parser.error("provide an executable and its arguments after --")
    for assignment in args.env:
        name, separator, _ = assignment.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            parser.error(f"invalid --env assignment {assignment!r}; expected NAME=VALUE")
    executable = Path(command[0]).expanduser().resolve(strict=True)
    if not executable.is_file():
        parser.error(f"executable is not a file: {executable}")
    if shutil.which("xcrun") is None or shutil.which("codesign") is None:
        parser.error("Xcode command-line tools with xctrace and codesign are required")
    try:
        configure_xcode()
    except RuntimeError as error:
        parser.error(str(error))

    profile_dir = Path(tempfile.mkdtemp(prefix="elisa-processor-trace-"))
    signed_executable = profile_dir / executable.name
    trace = args.trace.expanduser().resolve() if args.trace else profile_dir / "run.trace"
    toc_path = profile_dir / "toc.xml"
    intervals_path = profile_dir / "intervals.xml"
    entitlement_path = profile_dir / "entitlements.plist"
    trace.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Avoid inheriting restrictive file flags/xattrs and do not write beside
        # the original (which may live in a protected directory such as /usr/bin).
        shutil.copyfile(executable, signed_executable)
        signed_executable.chmod(0o700)
        entitlement_path.write_text(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
            "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
            "<plist version=\"1.0\"><dict>"
            "<key>com.apple.security.get-task-allow</key><true/>"
            "</dict></plist>\n",
            encoding="utf-8",
        )
        run_checked(
            [
                "codesign",
                "--force",
                "--sign",
                "-",
                "--entitlements",
                str(entitlement_path),
                str(signed_executable),
            ],
            stdout=subprocess.DEVNULL,
        )
        record_command = [
            "xcrun",
            "xctrace",
            "record",
            "--template",
            "Processor Trace",
            "--time-limit",
            args.time_limit,
            "--output",
            str(trace),
        ]
        for assignment in args.env:
            record_command.extend(["--env", assignment])
        record_command.extend(
            [
                "--launch",
                "--",
                str(signed_executable),
                *command[1:],
            ]
        )
        recorded = subprocess.run(
            record_command,
            check=False,
        )
        export_trace(trace, toc_path, toc=True)
        name, pid, target_status, end_reason = process_target(toc_path)
        export_trace(trace, intervals_path, toc=False)
        instructions, cycles, interval_count = instruction_totals(intervals_path, name, pid)
        print(
            json.dumps(
                {
                    "process": name,
                    "pid": int(pid),
                    "measurement": "Processor Trace self-instructions summed for the launched process",
                    "retired_instructions": instructions,
                    "cpu_cycles": cycles,
                    "trace_intervals": interval_count,
                    "trace_end_reason": end_reason,
                    "complete": end_reason == "Target app exited",
                    "target_exit_status": int(target_status) if target_status else None,
                    "trace": str(trace) if args.trace else None,
                },
                sort_keys=True,
            )
        )
        if recorded.returncode:
            return recorded.returncode
        if end_reason != "Target app exited":
            return 2
        return int(target_status) if target_status else 0
    finally:
        signed_executable.unlink(missing_ok=True)
        if not args.trace:
            shutil.rmtree(trace, ignore_errors=True)
        shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"profile_retired_instructions.py: {error}", file=sys.stderr)
        raise SystemExit(2)
