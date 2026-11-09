"""Read and rewrite the semantic pipeline while preserving its source fragment."""
from pathlib import Path


FRAGMENT = "pipeline_call_and_refinement_checks.elisa"
DIRECTIVE = f'include "./{FRAGMENT}"'
BEGIN = "                    # __parallel_pipeline_fragment_begin"
END = "                    # __parallel_pipeline_fragment_end"


def read_pipeline_source(path, *, annotated=False):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    count = text.splitlines().count(DIRECTIVE)
    if count == 0:
        return text
    if count != 1:
        raise ValueError("pipeline fragment include must appear exactly once")
    fragment = (path.parent / FRAGMENT).read_text(encoding="utf-8").rstrip("\n")
    replacement = f"{BEGIN}\n{fragment}\n{END}" if annotated else fragment
    return text.replace(DIRECTIVE, replacement, 1)


def write_pipeline_source(path, text):
    path = Path(path)
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line == BEGIN]
    ends = [i for i, line in enumerate(lines) if line == END]
    if not starts and not ends:
        if DIRECTIVE in path.read_text(encoding="utf-8").splitlines():
            raise ValueError("generated pipeline lost its fragment boundary")
        path.write_text(text, encoding="utf-8")
        return
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError("generated pipeline has invalid fragment boundaries")
    start, end = starts[0], ends[0]
    fragment = "\n".join(lines[start + 1:end]) + "\n"
    root = "\n".join(lines[:start] + [DIRECTIVE] + lines[end + 1:])
    if len(fragment.splitlines()) > 600 or len(root.splitlines()) > 600:
        raise ValueError("generated pipeline exceeds the source line limit")
    (path.parent / FRAGMENT).write_text(fragment, encoding="utf-8")
    path.write_text(root, encoding="utf-8")
