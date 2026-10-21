#!/usr/bin/env python3
"""Exercise current parser/backend in native code; cap every subprocess at 30s.

The emitter deliberately omits Semantic. Run compiler_atoms_smoke.py as well for
semantic registration, allowed selectors, and rejection checks. This is not a
replacement for a strict full compiler bootstrap. Set ELISA_NATIVE_EMITTER_OUT
to retain the linked emitter at a requested file path.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMPILER = os.environ.get("ELISACORE_BIN", str(ROOT / "../../Go projects/Elisa-core/compiler/bin/elisac"))
LLVM_CONFIG = os.environ.get("LLVM_CONFIG") or shutil.which("llvm-config") or "/opt/homebrew/opt/llvm/bin/llvm-config"


def run(command, **kwargs):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, **kwargs)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"30-second timeout: {command[0]}")
    if result.returncode:
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(map(str, command))}\n{result.stdout}\n{result.stderr}")
    return result.stdout


with tempfile.TemporaryDirectory(prefix="elisa-region-constant-") as directory:
    work = Path(directory)
    hooks = work / "hooks.c"
    hooks.write_text(run(["bash", str(ROOT / "scripts/write_profiler_hook_fallbacks.sh")]))
    environment = dict(os.environ)
    environment["ELISACORE_TRUSTED_RUNTIME_SOURCE"] = str(ROOT / "elisacore_std/elisacore_runtime_concurrency.elisa")
    environment.setdefault("ELISACORE_SMT_CACHE_DIR", str(Path.home() / ".cache/elisac-smt-proofs"))
    environment.setdefault("ELISACORE_SMT_CACHE_DECLINED", "1")
    obj, emitter = work / "emitter.o", work / "emitter"
    run([COMPILER, "-emit", "obj", "-permissive", "-O0", "-o", str(obj),
         str(ROOT / "test/breadth/emit_native.elisa")], env=environment, cwd=ROOT)
    libdir = run([LLVM_CONFIG, "--libdir"]).strip()
    libs = shlex.split(run([LLVM_CONFIG, "--libs", "--system-libs"]))
    run(["clang", "-Wl,-dead_strip", f"-L{libdir}", f"-Wl,-rpath,{libdir}",
         "-o", str(emitter), str(obj), str(hooks), *libs])
    retained_emitter = os.environ.get("ELISA_NATIVE_EMITTER_OUT")
    if retained_emitter:
        destination = Path(retained_emitter).expanduser()
        if destination.is_dir():
            raise SystemExit(f"ELISA_NATIVE_EMITTER_OUT must name a file: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(emitter, destination)
        print(f"native emitter retained: {destination.resolve()}")
    runtime = ROOT / "build/runtime/elisacore_runtime.o"
    if not runtime.exists():
        raise SystemExit(f"Build the runtime object first: {runtime}")
    for fixture in (
        "region_only_specialization",
        "region_only_generic_name_collision",
        "qualified_generic_return_width",
        "generic_return_declaring_module",
        "scalar_named_constant_match",
        "scalar_constant_or_match",
        "scalar_pin_width_match",
    ):
        source = ROOT / f"test/fixtures/self_parse_syntax/{fixture}.elisa"
        ir, obj, binary = (work / f"{fixture}{suffix}" for suffix in (".ll", ".o", ""))
        emitted_ir = run([str(emitter)], input=source.read_text())
        if fixture == "scalar_pin_width_match":
            for conversion in ("zext i8", "sext i8", "trunc i32"):
                if conversion not in emitted_ir:
                    raise SystemExit(f"pin-width IR is missing {conversion}")
        ir.write_text(emitted_ir)
        run(["clang", "-Wno-override-module", "-x", "ir", "-c", str(ir), "-o", str(obj)])
        run(["clang", str(obj), str(runtime), "-o", str(binary)])
        run([str(binary)])
        print(f"native {fixture}: ok")
