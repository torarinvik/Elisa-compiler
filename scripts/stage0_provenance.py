"""Alias for the Stage0 provenance recipe.

The recipe lives only in the Stage0 repository (compiler/scripts/stage0_provenance.py
under ELISA_CORE). A second copy here let the two builds diverge, so this file loads
that module and exposes its attributes under this name. Callers that import or run
this file therefore use the same build and receipt logic as `make build` in Stage0.
"""
import importlib.util
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_CORE = _HERE.parents[2] / "Go projects" / "Elisa-core"
_CORE = Path(os.environ.get("ELISA_CORE") or _DEFAULT_CORE).expanduser().resolve()
_SOURCE = _CORE / "compiler" / "scripts" / "stage0_provenance.py"

_spec = importlib.util.spec_from_file_location("_stage0_provenance_recipe", _SOURCE)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load Stage0 provenance recipe: {_SOURCE}")
_recipe = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _recipe
_spec.loader.exec_module(_recipe)

for _name, _value in vars(_recipe).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

if __name__ == "__main__":
    raise SystemExit(_recipe.main())
