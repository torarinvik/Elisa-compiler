"""Validate benchmark inputs and untimed correctness controls."""
import csv
import hashlib
import json
import math
import os
import platform
import resource
import shlex
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path


def run_once(_context, binary):
    try:
        proc = subprocess.Popen(
            [str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
    except OSError as error:
        raise RuntimeError(f"could not start correctness preflight program {binary}: {error}") from error
    try:
        stdout, stderr = proc.communicate(timeout=_context['timeout_seconds'])
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise RuntimeError(f"{binary} exceeded {_context['timeout_seconds']}s correctness preflight timeout; process group killed") from error
    if proc.returncode < 0:
        raise RuntimeError(f"{binary} terminated by signal {-proc.returncode} during correctness preflight")
    if stdout and stderr:
        raise RuntimeError(f"{binary} wrote checksum data to both stdout and stderr")
    return proc.returncode, stdout, stderr

def correctness_preflight(_context, stage):
    results = {}
    for bench in _context['benches']:
        try:
            observed = {variant: _context['run_once'](_context['out'] / bench / variant) for variant in _context['variants']}
        except RuntimeError as error:
            _context['mark_aborted']("correctness preflight failed", f"{stage}: {error}")
        expected_output = f"{_context['expected_checksums'][bench]}\n".encode()
        expected_status = _context['expected_exit_statuses'][bench]
        accepted_streams = ((expected_output, b""), (b"", expected_output))
        invalid = {
            variant: (code, stdout, stderr)
            for variant, (code, stdout, stderr) in observed.items()
            if code != expected_status or (stdout, stderr) not in accepted_streams
        }
        if invalid:
            printable = {
                variant: (code, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace"))
                for variant, (code, stdout, stderr) in invalid.items()
            }
            _context['mark_aborted'](
                "correctness preflight failed",
                f"{stage}: expected exact checksum on one stream and exit status {expected_status} for {bench}; got {printable}",
            )
        results[bench] = {"checksum": expected_output.decode("utf-8"), "exit_status": expected_status}
    return results

def current_source_manifest(_context):
    sources = [_context['source_dir'] / "cross_language.sh", _context['source_dir'] / "process_counter.py"]
    for bench in _context['benches']:
        for suffix in ("elisa", "c", "rs", "zig"):
            sources.append(_context['source_dir'] / f"{bench}.{suffix}")
    for directory in (_context['root'] / "src", _context['root'] / "elisacore_std", _context['root'] / "scripts"):
        for source in directory.rglob("*"):
            if source.is_file() and source.suffix in (".elisa", ".elisai", ".c", ".h", ".sh", ".py"):
                sources.append(source)
    lines = []
    for source in sorted(set(sources)):
        relative = source.relative_to(_context['root'])
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}\n")
    return "".join(lines).encode("utf-8")

def assert_build_sources_unchanged(_context, stage):
    try:
        expected = (_context['out'] / "sources.sha256").read_bytes()
        current = _context['current_source_manifest']()
    except OSError as error:
        _context['mark_aborted']("source manifest check failed", f"{stage}: {error}")
    if current != expected:
        _context['mark_aborted']("source manifest changed", f"{stage}: sources differ from the files used for the preflight builds")
