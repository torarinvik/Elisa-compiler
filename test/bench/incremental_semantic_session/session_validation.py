"""Validate paired semantic session results and counters."""
from __future__ import annotations

from typing import Any

from session_workload import mode_environment


def validate_pair(off: dict[str, Any], on: dict[str, Any], functions: int, workload: str, *, require_reports: bool = True) -> None:
    off_requests = off["requests"]
    on_requests = on["requests"]
    if len(off_requests) != len(on_requests):
        raise RuntimeError(f"{workload}: graph-on/off request counts differ")
    for index, (left, right) in enumerate(zip(off_requests, on_requests)):
        if left["label"] != right["label"]:
            raise RuntimeError(f"{workload}: graph-on/off request {index} labels differ")
        if left["status"] != right["status"]:
            raise RuntimeError(f"{workload}: graph-on/off request {index} status differs")
        if left["diagnostics"] != right["diagnostics"]:
            raise RuntimeError(f"{workload}: graph-on/off request {index} diagnostics/transcript differ")
        if not require_reports:
            continue
        empty_fact_fields = (
            "complete_empty_body_eligible",
            "complete_empty_body_restored",
            "complete_empty_body_publish_skips",
            "complete_empty_body_commits",
        )
        if any(field not in left["cache"] or field not in right["cache"] for field in empty_fact_fields):
            raise RuntimeError(f"{workload}: request {index} omitted complete-empty query counters")
        expected_empty_eligible = {
            "zero-fact": functions + 1,
            "call-facts": functions + 2,
            "shared-calls": 3,
        }[workload]
        empty_label = left["label"]
        if empty_label in {"declaration-surface-edit", "post-surface-body-edit"}:
            expected_empty_eligible += 1
        if empty_label == "post-surface-body-edit" and workload in {"call-facts", "shared-calls"}:
            expected_empty_eligible += 1
        for mode, request in (("graph-off", left), ("graph-on", right)):
            cache = request["cache"]
            if empty_label == "exact-repeat":
                expected_for_request = 0
            else:
                expected_for_request = expected_empty_eligible
            if int(cache["complete_empty_body_eligible"]) != expected_for_request:
                raise RuntimeError(
                    f"{workload}: {mode} {empty_label} classified "
                    f"{cache['complete_empty_body_eligible']} complete-empty bodies; "
                    f"expected {expected_for_request}"
                )
            for field in ("complete_empty_body_restored", "complete_empty_body_publish_skips", "complete_empty_body_commits"):
                if mode == "graph-off" and int(cache[field]) != 0:
                    raise RuntimeError(f"{workload}: graph-off {empty_label} unexpectedly reported {field}={cache[field]}")
        if empty_label == "prime":
            expected_empty_restored = 0
            expected_empty_commits = expected_empty_eligible
        elif empty_label == "exact-repeat":
            expected_empty_restored = 0
            expected_empty_commits = 0
        elif empty_label.startswith("body-edit-") or empty_label == "post-surface-body-edit":
            changed_body_is_empty = workload == "zero-fact" or (
                empty_label == "post-surface-body-edit" and workload in {"call-facts", "shared-calls"}
            )
            expected_empty_restored = expected_empty_eligible - (1 if changed_body_is_empty else 0)
            expected_empty_commits = 1 if changed_body_is_empty else 0
        elif empty_label == "declaration-surface-edit":
            # This version repeats the final body-edit value, so all existing
            # complete-empty bodies remain exact and only the newly added function
            # needs a query commit.
            expected_empty_restored = expected_empty_eligible - 1
            expected_empty_commits = 1
        else:
            expected_empty_restored = 0
            expected_empty_commits = 0
        graph_on_empty = right["cache"]
        if int(graph_on_empty["complete_empty_body_restored"]) != expected_empty_restored:
            raise RuntimeError(
                f"{workload}: graph-on {empty_label} restored "
                f"{graph_on_empty['complete_empty_body_restored']} independent empty bodies; "
                f"expected {expected_empty_restored}"
            )
        if int(graph_on_empty["complete_empty_body_publish_skips"]) != expected_empty_restored:
            raise RuntimeError(
                f"{workload}: graph-on {empty_label} skipped publication for "
                f"{graph_on_empty['complete_empty_body_publish_skips']} empty bodies; "
                f"expected {expected_empty_restored}"
            )
        if int(graph_on_empty["complete_empty_body_commits"]) != expected_empty_commits:
            raise RuntimeError(
                f"{workload}: graph-on {empty_label} committed "
                f"{graph_on_empty['complete_empty_body_commits']} empty query values; "
                f"expected {expected_empty_commits}"
            )
        metric_fields = ("name_lookup_hits", "name_lookup_classification_chain_visits")
        if any(field not in left["cache"] or field not in right["cache"] for field in metric_fields):
            raise RuntimeError(f"{workload}: request {index} omitted NameLookup measurement counters")
        reverse_mark_fields = (
            "reverse_mark_fast_skips",
            "reverse_mark_full_walks",
            "reverse_mark_nodes_visited",
            "reverse_mark_edges_visited",
        )
        if any(field not in left["cache"] or field not in right["cache"] for field in reverse_mark_fields):
            raise RuntimeError(f"{workload}: request {index} omitted reverse-closure measurement counters")
        if int(left["cache"]["name_lookup_hits"]) != 0:
            raise RuntimeError(f"{workload}: graph-off request {index} unexpectedly hit NameLookup")
        if any(int(left["cache"][field]) != 0 for field in reverse_mark_fields):
            raise RuntimeError(f"{workload}: graph-off request {index} unexpectedly marked a reverse closure")
        if right["label"] == "exact-repeat" and any(
            int(right["cache"][field]) != 0 for field in reverse_mark_fields
        ):
            raise RuntimeError(f"{workload}: graph-on exact-repeat unexpectedly marked a reverse closure")
        if workload in {"call-facts", "shared-calls"}:
            prime_hits = int(on_requests[0]["cache"]["name_lookup_hits"])
            on_visits = int(right["cache"]["name_lookup_classification_chain_visits"])
            if right["label"] == "prime" and on_visits <= 0:
                raise RuntimeError(f"{workload} graph-on prime did not record cold NameLookup chain visits")
            if (
                right["label"] == "exact-repeat"
                or right["label"].startswith("body-edit-")
                or right["label"] == "declaration-surface-edit"
                or right["label"] == "post-surface-body-edit"
            ):
                off_visits = int(left["cache"]["name_lookup_classification_chain_visits"])
                warm_hits = int(right["cache"]["name_lookup_hits"])
                if workload == "call-facts":
                    if right["label"] == "post-surface-body-edit":
                        same_request_baseline = functions - 1
                        if warm_hits <= same_request_baseline:
                            raise RuntimeError(
                                "call-facts graph-on post-surface-body-edit did not exceed its same-request duplicate baseline: "
                                f"baseline={same_request_baseline} warm={warm_hits}"
                            )
                    elif warm_hits <= prime_hits:
                        raise RuntimeError(
                            f"call-facts graph-on {right['label']} did not exceed its prime same-request hit baseline: "
                            f"prime={prime_hits} warm={warm_hits}"
                        )
                if workload == "shared-calls":
                    label = right["label"]
                    call_sites = functions - 1 if label == "post-surface-body-edit" else functions
                    if label.startswith("body-edit-"):
                        edit_index = int(label.rsplit("-", 1)[1])
                        uses_alternate_callee = edit_index % 2 == 1
                    elif label == "declaration-surface-edit":
                        edit_index = sum(
                            1 for request in on_requests if str(request["label"]).startswith("body-edit-")
                        )
                        uses_alternate_callee = edit_index % 2 == 1
                    else:
                        edit_index = 0
                        uses_alternate_callee = False
                    # Every direct call is classified twice. The cold same-request
                    # hit floor is total reads minus distinct callee spellings.
                    # `body-edit-N` labels use one-based N, and fixture() receives
                    # edit_version 100_000 + N for those requests. Since 100_000 is
                    # even, odd label suffixes select the alternate callee.
                    distinct_callees = 1 if label == "post-surface-body-edit" or not uses_alternate_callee else 2
                    same_request_baseline = 2 * call_sites - distinct_callees
                    if warm_hits <= same_request_baseline:
                        raise RuntimeError(
                            f"shared-calls graph-on {label} did not exceed its same-request duplicate baseline: "
                            f"baseline={same_request_baseline} warm={warm_hits}"
                        )
                if off_visits <= 0 or on_visits >= off_visits:
                    raise RuntimeError(
                        f"{workload} graph-on {right['label']} did not reduce classification-chain visits: "
                        f"graph_off={off_visits} graph_on={on_visits} hits={warm_hits} prime_hits={prime_hits}"
                    )
        for field in ("eligible_bodies", "matched_eligible_bodies"):
            if left["cache"].get(field) != right["cache"].get(field):
                raise RuntimeError(f"{workload}: graph-on/off request {index} has different {field} counts")
        if (
            left["cache"].get("name_lookup_direct_surface_classifications") != "0"
            or right["cache"].get("name_lookup_direct_surface_classifications") != "0"
        ):
            raise RuntimeError(f"{workload}: graph-off/on arm unexpectedly used direct-surface classification")
        expected_eligible = {
            "call-facts": functions * 2 + 2,
            "shared-calls": functions + 3,
            "zero-fact": functions + 1,
        }[workload]
        if left["label"] in {"declaration-surface-edit", "post-surface-body-edit"}:
            expected_eligible += 1
        eligible = int(left["cache"].get("eligible_bodies", "-1"))
        if eligible != expected_eligible:
            raise RuntimeError(
                f"{workload}: request {left['label']} admitted {eligible} cacheable bodies; "
                f"fixture expects {expected_eligible}"
            )
        if left["label"] == "declaration-surface-edit":
            graph_on = right["cache"]
            full_walks = int(graph_on["reverse_mark_full_walks"])
            fast_skips = int(graph_on["reverse_mark_fast_skips"])
            visited_nodes = int(graph_on["reverse_mark_nodes_visited"])
            visited_edges = int(graph_on["reverse_mark_edges_visited"])
            if full_walks <= 0 or visited_nodes <= 0 or visited_edges <= 0:
                raise RuntimeError(
                    f"{workload}: declaration-surface edit did not exercise a nonempty reverse closure: "
                    f"walks={full_walks} nodes={visited_nodes} edges={visited_edges}"
                )
            if fast_skips <= 0:
                raise RuntimeError(f"{workload}: declaration-surface edit did not reuse the repeated-mark shortcut")
        expected_direct_facts = functions if workload in {"call-facts", "shared-calls"} else 0
        if left["label"] == "post-surface-body-edit" and workload in {"call-facts", "shared-calls"}:
            expected_direct_facts -= 1
        for mode, request in (("graph-off", left), ("graph-on", right)):
            direct_facts = int(request["cache"].get("direct_fact_count", "-1"))
            if direct_facts != expected_direct_facts:
                raise RuntimeError(
                    f"{workload}: {mode} request {request['label']} recorded {direct_facts} direct facts; "
                    f"fixture expects {expected_direct_facts}"
                )
    if len(off_requests) < 3:
        raise RuntimeError(f"{workload}: benchmark needs at least one body edit")
    if not require_reports:
        return
    for index, (left, right) in enumerate(zip(off_requests, on_requests)):
        if not left["label"].startswith("body-edit-") and left["label"] != "post-surface-body-edit":
            continue
        off_cache = left["cache"]
        on_cache = right["cache"]
        if off_cache.get("source_input_admitted") != "no":
            raise RuntimeError(f"graph-off edit {index} unexpectedly admitted SourceInput")
        snapshot_fallbacks = int(off_cache.get("prior_snapshot_fact_fallbacks", "0"))
        if workload == "zero-fact":
            if snapshot_fallbacks != 0:
                raise RuntimeError(
                    f"graph-off zero-fact edit {index} unexpectedly used typed-snapshot fallback"
                )
        elif snapshot_fallbacks <= 0:
            raise RuntimeError(f"graph-off edit {index} skipped typed-snapshot fact fallback")
        expected_source_admission = "no" if workload == "zero-fact" else "yes"
        actual_source_admission = on_cache.get("source_input_admitted")
        if actual_source_admission != expected_source_admission:
            raise RuntimeError(
                f"graph-on {workload} edit {index} reported SourceInput admission "
                f"{actual_source_admission!r}; fixture expects {expected_source_admission!r}"
            )
        expected_restored = int(off_cache.get("eligible_bodies", "0")) - 1
        restored = int(on_cache.get("function_body_facts_restored", "0")) + int(
            on_cache.get("complete_empty_body_restored", "0")
        )
        if expected_restored <= 0 or restored != expected_restored:
            raise RuntimeError(
                f"graph-on edit {index} did not restore every unchanged cacheable body: "
                f"restored={restored} expected={expected_restored} functions={functions}"
            )
        publish_skips = int(on_cache.get("body_query_publish_skips", "-1")) + int(
            on_cache.get("complete_empty_body_publish_skips", "-1")
        )
        if publish_skips != restored:
            raise RuntimeError(
                f"graph-on edit {index} did not skip publication evaluation for each restored body: "
                f"skipped={publish_skips} restored={restored}"
            )
        off_publish_skips = int(off_cache.get("body_query_publish_skips", "-1")) + int(
            off_cache.get("complete_empty_body_publish_skips", "-1")
        )
        if off_publish_skips != 0:
            raise RuntimeError(f"graph-off edit {index} unexpectedly skipped body-query publication")
    surface_index = next(index for index, request in enumerate(off_requests) if request["label"] == "declaration-surface-edit")
    for mode, request in (("graph-off", off_requests[surface_index]), ("graph-on", on_requests[surface_index])):
        cache = request["cache"]
        if cache.get("source_input_admitted") != "no":
            raise RuntimeError(f"{mode} declaration-surface edit admitted stale SourceInput")
        if cache.get("function_body_facts_restored") != "0" or cache.get("prior_snapshot_fact_fallbacks") != "0":
            raise RuntimeError(f"{mode} declaration-surface edit reused body facts across changed declarations")
        if cache.get("body_query_publish_skips") != "0":
            raise RuntimeError(f"{mode} declaration-surface edit skipped publication after invalidation")

def validate_direct_surface_pair(
    graph_on: dict[str, Any], direct_surface: dict[str, Any], workload: str
) -> None:
    """Check semantic parity and prove the opt-in resolver route was selected."""
    graph_requests = graph_on["requests"]
    direct_requests = direct_surface["requests"]
    if len(graph_requests) != len(direct_requests):
        raise RuntimeError(f"{workload}: graph-on/direct-surface request counts differ")
    expected_graph_env = mode_environment("graph-on")
    expected_direct_env = mode_environment("direct-surface")
    if graph_on.get("mode_environment") != expected_graph_env:
        raise RuntimeError(f"{workload}: graph-on arm has unexpected environment switches")
    if direct_surface.get("mode_environment") != expected_direct_env:
        raise RuntimeError(f"{workload}: direct-surface arm has unexpected environment switches")

    body_cache_fields = (
        "eligible_bodies",
        "matched_eligible_bodies",
        "source_input_admitted",
        "function_body_facts_restored",
        "prior_snapshot_fact_fallbacks",
        "body_query_publish_skips",
        "complete_empty_body_eligible",
        "complete_empty_body_restored",
        "complete_empty_body_publish_skips",
        "complete_empty_body_commits",
        "direct_fact_count",
    )
    reverse_mark_fields = (
        "reverse_mark_fast_skips",
        "reverse_mark_full_walks",
        "reverse_mark_nodes_visited",
        "reverse_mark_edges_visited",
    )
    for index, (graph_request, direct_request) in enumerate(zip(graph_requests, direct_requests)):
        if graph_request["label"] != direct_request["label"]:
            raise RuntimeError(f"{workload}: graph-on/direct-surface request {index} labels differ")
        if graph_request["status"] != direct_request["status"]:
            raise RuntimeError(f"{workload}: graph-on/direct-surface request {index} status differs")
        if graph_request["diagnostics"] != direct_request["diagnostics"]:
            raise RuntimeError(f"{workload}: graph-on/direct-surface request {index} diagnostics/transcript differ")
        for mode, request in (("graph-on", graph_request), ("direct-surface", direct_request)):
            if any(field not in request["cache"] for field in reverse_mark_fields):
                raise RuntimeError(f"{workload}: {mode} request {index} omitted reverse-closure counters")
            if request["label"] == "exact-repeat" and any(
                int(request["cache"][field]) != 0 for field in reverse_mark_fields
            ):
                raise RuntimeError(f"{workload}: {mode} exact-repeat unexpectedly marked a reverse closure")
            if request["label"] == "declaration-surface-edit":
                values = {field: int(request["cache"][field]) for field in reverse_mark_fields}
                if any(value <= 0 for value in values.values()):
                    raise RuntimeError(
                        f"{workload}: {mode} declaration-surface edit missed reverse-closure work: {values}"
                    )
        for field in body_cache_fields:
            if graph_request["cache"].get(field) != direct_request["cache"].get(field):
                raise RuntimeError(
                    f"{workload}: direct-surface request {index} changed body-cache field {field}"
                )
        if graph_request["cache"].get("name_lookup_direct_surface_classifications") != "0":
            raise RuntimeError(f"{workload}: graph-on request {index} unexpectedly used direct surface classification")
        if direct_request["cache"].get("name_lookup_hits") != "0":
            raise RuntimeError(f"{workload}: direct-surface request {index} unexpectedly hit NameLookup graph")

    if workload in {"call-facts", "shared-calls"}:
        for request in direct_requests:
            direct_count = int(request["cache"].get("name_lookup_direct_surface_classifications", "0"))
            if direct_count <= 0:
                raise RuntimeError(
                    f"{workload} direct-surface {request['label']} did not classify finalized-surface names"
                )
            chain_visits = int(request["cache"].get("name_lookup_classification_chain_visits", "-1"))
            if chain_visits != 0:
                raise RuntimeError(
                    f"{workload} direct-surface {request['label']} unexpectedly used cold classifier chains: {chain_visits}"
                )
