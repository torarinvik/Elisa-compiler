#!/usr/bin/env python3
"""Bind the unchanged-edge generation refresh to the query graph's safety gates."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/incremental_function_facts.elisa"


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^([ \t]*)def {re.escape(name)}(?:\[[^\]\n]*\])?\(", text)
    if not match:
        raise SystemExit(f"missing {name}")
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\]\n]*\])?\(", text[match.end():])
    return text[match.start():match.end() + following.start() if following else len(text)]


def ordered(source: str, name: str, fragments: tuple[str, ...]) -> None:
    body = compact(section(source, name))
    cursor = 0
    for fragment in fragments:
        needle = compact(fragment)
        found = body.find(needle, cursor)
        if found < 0:
            raise SystemExit(f"{name} lost the required refresh/replacement ordering: {fragment}")
        cursor = found + len(needle)


if not SOURCE.is_file():
    raise SystemExit(f"missing query graph source: {SOURCE}")
source = SOURCE.read_text()
compact_source = compact(source)
dependencies = compact(section(source, "ifq_query_dependencies_check"))
apply_dependencies = compact(section(source, "ifq_apply_dependency_set"))
refresh = compact(section(source, "ifq_refresh_dependency_generations"))
commit = compact(section(source, "ifq_query_commit"))

for fragment in (
    "dependencies.count > INCREMENTAL_SEMANTIC_QUERY_PER_DEPENDENCY_LIMIT",
    "check.all_dependencies_green <- false if dependency_node.status != IncrementalSemanticQueryStatus.Green",
    "check.results_current <- false if edge.observed_result_generation != dependency_node.result_generation",
    "check.equal <- false if not found",
    "check.dependency_ids.push(dependency)",
):
    if compact(fragment) not in dependencies:
        raise SystemExit(f"dependency validation no longer proves refresh eligibility: {fragment}")

if "check.old_count <- steps" not in section(source, "ifq_query_dependencies_check"):
    raise SystemExit("old dependency count must use the validated edge-chain traversal")
if "matched_old:mutabledarray[bool]=[]" not in dependencies or "ifmatched_old[candidate]:" not in dependencies:
    raise SystemExit("old edge multiplicity must be checked by the bounded membership pass")
for forbidden in ("old_ids", "duplicate_old"):
    if forbidden in dependencies:
        raise SystemExit(f"old edge validation retained a separate quadratic duplicate scan: {forbidden}")

if "forpreviousin0..<index" in apply_dependencies or "continueifduplicate" in apply_dependencies:
    raise SystemExit("dependency application must rely on the unique IDs produced by dependency validation")

for fragment in (
    "expected_count > INCREMENTAL_SEMANTIC_QUERY_PER_DEPENDENCY_LIMIT",
    "if not ifq_edge_links_are_valid(session, edge_cursor):",
    "dependency_node.status != IncrementalSemanticQueryStatus.Green",
    "if steps > expected_count:",
    "session.query_edges[edge_cursor.value.usize()].observed_result_generation <- dependency_node.result_generation",
    "if steps != expected_count:",
):
    if compact(fragment) not in refresh:
        raise SystemExit(f"generation refresh lost its bounded all-Green edge check: {fragment}")
for forbidden in ("ifq_apply_dependency_set(", "ifq_query_note_incoming_edge_change(", "free_query_edges"):
    if forbidden in refresh:
        raise SystemExit(f"generation refresh must leave dependency adjacency untouched: {forbidden}")

ordered(source, "ifq_query_commit", (
    "if not check.all_dependencies_green:",
    "dependency_replacement_required: bool = not check.equal",
    "dependency_generation_refresh_required: bool = check.equal and not check.results_current and check.all_dependencies_green",
    "if dependency_replacement_required:",
    "walk: IncrementalSemanticQueryWalkResult = ifq_query_walk_path(session, check.dependency_ids[index], query_id)",
    "if dependency_replacement_required and not ifq_free_query_edges_valid_for_replacement(session, check.unique_count, check.old_count):",
    "extra_free_edges: usize = check.old_count if dependency_replacement_required else 0",
    "extra_edges: usize = append_edges if dependency_replacement_required else 0",
    "if dependency_replacement_required:",
    "return false if not ifq_apply_dependency_set(session, query_id, check.dependency_ids)",
    "session.query_nodes[query_id.value.usize()].result_generation <- session.query_nodes[query_id.value.usize()].result_generation + 1 if result_changed",
    "if dependency_generation_refresh_required and not ifq_refresh_dependency_generations(session, query_id, check.unique_count):",
    "session.query_nodes[query_id.value.usize()].status <- IncrementalSemanticQueryStatus.Green",
))

if compact("if result_changed and not ifq_mark_reverse_closure(session, query_id, IncrementalSemanticQueryStatus.PotentiallyDirty):") not in commit:
    raise SystemExit("result changes must still dirty dependers through the reverse closure")
if "if dependency_generation_refresh_required:" in commit and "ifq_apply_dependency_set" in commit[commit.find("if dependency_generation_refresh_required:"):]:
    raise SystemExit("unchanged dependency IDs must refresh generations without replacing edges")

print("source-bound query generation refresh OK")
