"""Keep recursive try-fallback walks' mutable value-block captures explicit."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_try_fallible.elisa"
text = SOURCE.read_text(encoding="utf-8")

# Annotation arrays are read-only references. docs/119 E10 permits only
# mutable bindings in a value-block capture list; those inputs stay ordinary reads.
required = {
    "table",
    "module_index",
    "error_index",
    "function_positions",
}

for item, sequence in (
    ("argument", "arguments"),
    ("statement", "statements"),
    ("arm", "arms"),
    ("declaration", "declarations"),
):
    pattern = rf"for {item} in {sequence} \|([^|]+)\| -> table:"
    matches = re.findall(pattern, text)
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one {item} fallback traversal, found {len(matches)}")
    captures = {name.strip() for name in matches[0].split(",")}
    readonly = captures & {"annotations", "module_annotations"}
    if readonly:
        raise SystemExit(f"{item} fallback traversal threads read-only inputs: {sorted(readonly)}")
    missing = required - captures
    if missing:
        raise SystemExit(f"{item} fallback traversal omits captures: {sorted(missing)}")

print("try fallback capture accounting: all four recursive value-block walks capture mutable indexes")
