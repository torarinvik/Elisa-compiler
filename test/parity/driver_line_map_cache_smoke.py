#!/usr/bin/env python3
"""Compile the production line-map renderers and compare cached/uncached results.

ELISACORE_BIN selects the compiler. The fixture includes the runtime source.
Only the location functions are extracted, avoiding a whole compiler seed per test.
"""
import os
from pathlib import Path
import re
import subprocess
import statistics
import sys
import time
import textwrap
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMPILER = os.environ.get("ELISACORE_BIN", str(ROOT / "../../Go projects/Elisa-core/compiler/bin/elisac"))


def function(text, name):
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if re.match(rf" *def {name}\(", line))
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
            break
        end += 1
    return textwrap.dedent("".join(lines[start:end]))


diag = (ROOT / "src/driver/elisac_diagnostics.elisa").read_text()
source = f'global region source\ninclude "{ROOT}/elisacore_std/elisacore_runtime.elisa"\n'
# Compile only the publication API used by the driver, excluding unrelated tokenizer bodies.
lexer_cache = (ROOT / "src/lexer/lexer_line_map_cache.elisa").read_text()
source += lexer_cache[:lexer_cache.index("extend Lexer:")]
source += "module Lexer:\n    public:\n"
for name in ("line_map_publish", "line_map_override_copy", "line_map_suspend", "line_map_clear", "line_map_resume"):
    source += textwrap.indent(function(lexer_cache, name), "        ")
source += "    private:\n" + textwrap.indent(function((ROOT / "src/lexer/lexer.elisa").read_text(), "source_line_map_value"), "        ")
source += lexer_cache[lexer_cache.index('@link_name("unsetenv")'):]
source += function((ROOT / "src/driver/elisac_cli.elisa").read_text(), "env_value")
for name in ("append_decimal", "push_source_path", "driver_line_map_value"):
    source += function(diag, name)
source += diag[diag.index("def source_line_of("):diag.index("def report_diagnostic(")]
source += r'''
def compare_locations() -> i32 can[Abort.Panic, Memory.Allocate, Unsafe.PointerCast, Global.Read]:
    can Global.Read:
        for line in 0..<40:
            flat: u32 = line.u32()
            return 1 if source_line_of(flat) != source_line_of_uncached(flat)
            cached: mutable darray[u8] = []
            uncached: mutable darray[u8] = []
            push_diagnostic_location(&cached, flat)
            push_diagnostic_location_uncached(&uncached, flat)
            return 2 if cached.count != uncached.count
            for index in 0..<cached.count:
                return 3 if cached[index] != uncached[index]
        return 0

def main() -> i32 can[Abort.Panic, Memory.Allocate, Unsafe.PointerCast, Global{Read,Write}]:
    can Global{Read,Write}:
        Lexer::line_map_clear()
        return 10 if compare_locations() != 0
        driver_line_map_refresh()
        return 11 if compare_locations() != 0
        first: mutable darray[u8] = []
        # Unsorted entries, duplicate FLAT (last wins), zero FLAT, empty path, no final newline.
        first.extend("1:20:first.elisa\n15:7:other.elisa\n5:30:old.elisa\n5:40:new.elisa\n0:9:zero.elisa\n25:8:")
        Lexer::line_map_publish(first)
        return 12 if driver_line_map_cached()
        return 13 if compare_locations() != 0
        driver_line_map_refresh()
        return 14 if not driver_line_map_cached()
        return 15 if compare_locations() != 0
        return 16 if source_line_of(5) != 40
        return 17 if source_line_of(15) != 7
        second: mutable darray[u8] = []
        second.extend("1:99:next.elisa")
        Lexer::line_map_publish(second)
        return 18 if driver_line_map_cached()
        return 19 if source_line_of(5) != 103
        driver_line_map_refresh()
        return 20 if compare_locations() != 0
        Lexer::line_map_publish(second)
        return 21 if not driver_line_map_cached()
        saved: mutable darray[u8] = []
        suspended: bool = Lexer::line_map_suspend(&saved)
        return 22 if driver_line_map_cached()
        driver_line_map_refresh()
        return 23 if compare_locations() != 0
        Lexer::line_map_resume(&saved, suspended)
        return 24 if driver_line_map_cached()
        return 25 if source_line_of(5) != 103
        driver_line_map_refresh()
        return 26 if compare_locations() != 0
        empty: mutable darray[u8] = []
        Lexer::line_map_publish(empty)
        driver_line_map_refresh()
        return 27 if source_line_of(5) != 5
        return 28 if compare_locations() != 0
        sorted_map: mutable darray[u8] = []
        sorted_map.extend("0:9:zero.elisa\n1:20:first.elisa\n5:30:old.elisa\n5:40:new.elisa\n15:7:other.elisa\n25:8:")
        Lexer::line_map_publish(sorted_map)
        return 31 if driver_line_map_cached()
        driver_line_map_refresh()
        return 32 if not driver_line_map_cached()
        return 33 if compare_locations() != 0
        return 34 if source_line_of(5) != 40
        return 35 if source_line_of(15) != 7
        Lexer::line_map_clear()
        return 29 if driver_line_map_cached()
        return 30 if compare_locations() != 0
        return 0
'''
if "--benchmark" in sys.argv:
    source = source.replace("def main()", "def regression_main()")
    source += r'''
def main() -> i32 can[Abort.Panic, Memory.Allocate, Unsafe.PointerCast]:
    can Global{Read,Write}:
        map: mutable darray[u8] = []
        for row in 1..<2001 |map|:
            append_decimal(&map, row.u32())
            map.extend(":1:/compiler/source/semantic/representative_long_module_path.elisa\n")
        Lexer::line_map_publish(map)
        cached: bool = getenv("ELISA_LINE_MAP_BENCH_CACHED") is value
        driver_line_map_refresh() if cached
        buffer: mutable darray[u8] = []
        for row in 1..<501 |buffer, cached|:
            buffer.truncate(0)
            if cached:
                push_diagnostic_location(&buffer, row.u32())
            else:
                push_diagnostic_location_uncached(&buffer, row.u32())
        return 0
'''
with tempfile.TemporaryDirectory(prefix="elisa-driver-line-map-") as work:
    work = Path(work)
    fixture = work / "probe.elisa"
    fixture.write_text(source)
    compiled = subprocess.run([COMPILER, "-emit", "obj", "-o", str(work / "probe.o"), str(fixture)],
                              capture_output=True, text=True)
    if compiled.returncode:
        raise SystemExit("\n".join(line for line in (compiled.stdout + compiled.stderr).splitlines() if "warning:" not in line))
    hooks = work / "hooks.c"
    hooks.write_text(subprocess.check_output(["bash", str(ROOT / "scripts/write_profiler_hook_fallbacks.sh")], text=True))
    link_flags = ["-Wl,-dead_strip"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
    subprocess.run(["clang", *link_flags, "-o", str(work / "probe"), str(work / "probe.o"), str(hooks)], check=True)
    if "--benchmark" in sys.argv:
        for cached in (False, True):
            env = {k: v for k, v in os.environ.items() if k != "ELISA_LINE_MAP_BENCH_CACHED"}
            if cached:
                env["ELISA_LINE_MAP_BENCH_CACHED"] = "1"
            samples = []
            for _ in range(3):
                started = time.perf_counter()
                subprocess.run([str(work / "probe")], env=env, check=True)
                samples.append(time.perf_counter() - started)
            print(f"{'cached' if cached else 'uncached'}: {statistics.median(samples):.4f}s median, 500 locations / 2000 map entries")
    else:
        result = subprocess.run([str(work / "probe")], env={**os.environ, "ELISA_STAGE1_SOURCE_PATH": "root.elisa"})
        if result.returncode:
            raise SystemExit(f"driver line-map cache failed at check {result.returncode}")
        print("driver_line_map_cache_smoke: ok")
