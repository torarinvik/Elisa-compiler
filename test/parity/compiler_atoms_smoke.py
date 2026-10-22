#!/usr/bin/env python3
"""Run focused compiler-function probes, with a 30-second cap per command.

Uses the selected stage0 compiler (ELISACORE_BIN) to compile the current Elisa
implementation. This checks runtime behavior of the sliced functions, not a
complete stage1 build. Most probes use -permissive for dependency contracts that
the isolated unit cannot prove; source checks and SMT remain enabled. The
pymodule_struct_typedef, try_fallback_source, authority_coverage,
authority_annotation_index, iterator_alias_resolution, lmut_scope,
loop_program_view, type_region_suffix, holder_view_depth, holder_view_wrappers, and
holder_comprehension_alias probes use -strict.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
COMPILER = os.environ.get("ELISACORE_BIN", str(ROOT / "../../Go projects/Elisa-core/compiler/bin/elisac"))
LLVM_CONFIG = os.environ.get("LLVM_CONFIG") or shutil.which("llvm-config") or "/opt/homebrew/opt/llvm/bin/llvm-config"
ATOMS = ("semantic", "backend", "borrow_replay", "thread_shareability", "exclusivity", "readonly_ref", "error_union", "or_constants", "region_assignment", "incremental_empty_body", "firm_extern_index", "pymodule_struct_typedef", "try_fallback_source", "authority_coverage", "authority_annotation_index", "iterator_alias_resolution", "lmut_scope", "loop_program_view", "type_region_suffix", "holder_view_depth", "holder_view_wrappers", "foreign_handle_flow", "holder_comprehension_alias")
selected_atoms = sys.argv[1:] or ATOMS
if any(atom not in ATOMS for atom in selected_atoms):
    raise SystemExit(f"Choose atom names from: {', '.join(ATOMS)}")


def run(args, **kwargs):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30, **kwargs)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"30-second timeout: {args[0]}")
    if result.returncode:
        output = result.stdout + result.stderr
        details = "\n".join(line for line in output.splitlines() if "warning:" not in line)
        raise SystemExit(f"command failed ({result.returncode}): {args[0]}\n{details}")
    return result.stdout


with tempfile.TemporaryDirectory(prefix="elisa-compiler-atoms-") as work:
    work = Path(work)
    hooks = work / "hooks.c"
    hooks.write_text(run(["bash", str(ROOT / "scripts/write_profiler_hook_fallbacks.sh")]))
    env = dict(os.environ)
    env["ELISACORE_TRUSTED_RUNTIME_SOURCE"] = str(ROOT / "elisacore_std/elisacore_runtime_concurrency.elisa")
    env.setdefault("ELISACORE_SMT_CACHE_DIR", str(Path.home() / ".cache/elisac-smt-proofs"))
    env.setdefault("ELISACORE_SMT_CACHE_DECLINED", "1")
    for atom in selected_atoms:
        started = time.perf_counter()
        unit = ROOT / ("src/backend/codegen.elisa" if atom == "backend" else "src/driver/elisac.elisa" if atom == "pymodule_struct_typedef" else "src/semantic/semantic.elisa")
        source, obj, binary = (work / f"{atom}{ext}" for ext in (".elisa", ".o", ""))
        probe = f"test/atoms/compiler_{atom}.elisa" if atom in ("semantic", "backend") else f"test/atoms/{atom}.elisa"
        run([sys.executable, str(ROOT / "scripts/compiler_atom_slice.py"), str(unit),
             str(ROOT / probe), str(source)])
        proof_mode = "-strict" if atom in ("pymodule_struct_typedef", "try_fallback_source", "authority_coverage", "authority_annotation_index", "iterator_alias_resolution", "lmut_scope", "loop_program_view", "type_region_suffix", "holder_view_depth", "holder_view_wrappers", "foreign_handle_flow", "holder_comprehension_alias") else "-permissive"
        run([COMPILER, "-emit", "obj", proof_mode, "-O0", "-o", str(obj), str(source)], env=env)
        flags = ["-Wl,-dead_strip"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
        if atom == "backend":
            libdir = run([LLVM_CONFIG, "--libdir"]).strip()
            flags += [f"-L{libdir}", f"-Wl,-rpath,{libdir}"] + run([LLVM_CONFIG, "--libs"]).split()
        run(["clang", *flags, "-o", str(binary), str(obj), str(hooks)])
        run([str(binary)])
        print(f"compiler {atom} atoms: ok ({time.perf_counter() - started:.2f}s)")
