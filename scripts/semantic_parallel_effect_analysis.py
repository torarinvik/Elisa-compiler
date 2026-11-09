"""Effect analysis for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def analyze(_services, 
    defs, globals_, mutable_ref_globals, type_aliases, table_field_types, struct_field_types,
    enum_variants=None, _build_cast_nodes=True,
):
    """Per definition name: (writes, reads_diagnostics, callees)."""
    glob_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, globals_))) + r")\b") if globals_ else None
    info = {}
    cast_nodes = {}
    enum_variants = enum_variants or {}
    for name, bodies in defs.items():
        writes, reads_diag, callees = set(), False, set()
        for d in bodies:
            text, code_text = _services['audit_normalize_field_dots'](_services['strip_comments']("".join(d["body"])))
            handled_cast_sites = set()
            tables = set(_services['TABLE_DECL_RE'].findall(d["params"])) | set(_services['TABLE_DECL_RE'].findall(text))
            table_aliases = _services['local_table_aliases'](text, tables)
            tables.update(table_aliases)
            global_aliases, borrowed_global_aliases = _services['local_global_aliases'](
                text, globals_, mutable_ref_globals
            )
            field_aliases, diagnostic_aliases, borrowed_field_aliases = _services['local_table_field_aliases'](
                text, tables, table_field_types, type_aliases, struct_field_types
            )
            immutable_borrow_starts = _services['immutable_table_field_borrow_starts'](code_text, tables)
            declared_return_type = _services['function_return_type'](d)
            for t in sorted(tables):
                te = re.escape(t)
                for m in re.finditer(te + r"\.(\w+)(?:(?:\.\w+)|(?:\[[^\]\n]*\]))*\s*<-", text):
                    if m.group(1) != "diagnostics":
                        writes.add(m.group(1))
                for m in re.finditer(te + r"\.(\w+)(?:(?:\.\w+)|(?:\[[^\]\n]*\]))*\.(?:" + _services['MUTATORS'] + r")\(", text):
                    if m.group(1) != "diagnostics":
                        writes.add(m.group(1))
                for m in re.finditer(r"\bin\s+" + te + r"\.(\w+)(?:(?:\.\w+)|(?:\[[^\]\n]*\]))*\s*:", text):
                    line_start = text.rfind("\n", 0, m.start()) + 1
                    # Iterating over a table field is read-only. The assignment
                    # form guarded here is a region entry, not `for x in field:`.
                    if re.search(r"\bfor\b[^:\n]*$", text[line_start:m.start()]):
                        continue
                    if m.group(1) != "diagnostics":
                        writes.add("in:" + m.group(1))
                if re.search(r"&\s*(?:\(\s*)*" + te + r"\b(?!\s*\.)", code_text):
                    writes.add("ref:whole-table")
                for m in re.finditer(r"&\s*" + te + r"\.(\w+)", code_text):
                    if m.start() not in immutable_borrow_starts:
                        writes.add("ref:" + m.group(1))
                # Only an in-place push extends diagnostics. A replacement can discard
                # earlier sequential results, and every other use reads them.
                for m in re.finditer(r"\b" + te + r"\.diagnostics\b", text):
                    after = text[m.end():]
                    before = text[:m.start(0)]
                    if re.match(r"\s*<-", after):
                        if re.match(
                            r"\s*<-\s*" + te + r"\.diagnostics\s*\.\s*push\s*\(",
                            after,
                        ):
                            continue
                        writes.add("diagnostics-replace")
                        continue
                    if re.match(r"\s*\.\s*push\s*\(", after) and re.search(
                        te + r"\.diagnostics\s*<-\s*$", before
                    ):
                        continue
                    reads_diag = True
            # Returning a table or one of its mutable fields lets callers carry the
            # alias beyond this function's local analysis. Mark that source helper as
            # effectful so every caller's audited closure fails closed. Scalar field
            # copies remain safe to return.
            for returned_expression in _services['returned_expressions'](code_text):
                expression = _services['return_value_before_guard'](
                    returned_expression.strip().rstrip(";").strip()
                )
                for expression in _services['returned_value_arms'](expression):
                    if not expression:
                        continue
                    if _services['argument_is_whole_table'](expression, tables, table_aliases):
                        writes.add("returned-whole-table-alias")
                        continue
                    unwrapped = expression
                    while unwrapped.startswith("(") and _services['matching_delimiter'](unwrapped, 0) == len(unwrapped) - 1:
                        unwrapped = unwrapped[1:-1].strip()
                    borrowed = unwrapped.startswith("&")
                    if borrowed:
                        unwrapped = unwrapped[1:].strip()
                        while unwrapped.startswith("(") and _services['matching_delimiter'](unwrapped, 0) == len(unwrapped) - 1:
                            unwrapped = unwrapped[1:-1].strip()
                    field_path = re.fullmatch(
                        r"(\w+)((?:\s*\.\s*\w+|\s*\[[^\]\n]*\])*)", unwrapped
                    )
                    direct_field = bool(field_path and field_path.group(1) in tables)
                    alias_derived = bool(
                        field_path
                        and field_path.group(1) in field_aliases | diagnostic_aliases
                    )
                    if direct_field or alias_derived:
                        value_type = _services['table_field_expression_type'](
                            unwrapped,
                            tables,
                            table_field_types,
                            type_aliases,
                            struct_field_types,
                        )
                        if alias_derived and not direct_field:
                            value_type = _services['local_path_expression_type'](
                                unwrapped, text, struct_field_types
                            )
                        copied_value_is_safe = bool(
                            value_type
                            and _services['type_is_copy_value'](value_type, type_aliases, struct_field_types)
                            and not _services['type_may_contain_reference'](
                                value_type, type_aliases, struct_field_types
                            )
                        )
                        if borrowed or not copied_value_is_safe:
                            writes.add("returned-table-field-alias")
                    elif any(
                        re.search(r"\b" + re.escape(alias) + r"\b", expression)
                        for alias in tables | table_aliases | field_aliases | diagnostic_aliases
                    ) and (
                        (
                            not declared_return_type
                            or not _services['type_is_copy_value'](
                                declared_return_type, type_aliases, struct_field_types
                            )
                            or _services['type_may_contain_reference'](
                                declared_return_type, type_aliases, struct_field_types
                            )
                        )
                        and not _services['returned_shared_paths_are_copies'](
                            expression,
                            text,
                            tables,
                            field_aliases,
                            diagnostic_aliases,
                            table_field_types,
                            type_aliases,
                            struct_field_types,
                        )
                    ):
                        # A computed/block return that mentions shared table state and
                        # could carry an alias cannot be proven to return a copy. A known
                        # scalar result remains safe even when computed from table fields.
                        writes.add("returned-unknown-table-alias")
            if glob_re is not None:
                for m in glob_re.finditer(text):
                    lead = text[max(0, m.start() - 2):m.start()]
                    allocates = re.search(r"\bin\s+$", text[max(0, m.start() - 4):m.start()]) is not None
                    tail_end = _services['global_path_write_tail'](text, m.end())
                    tail = text[tail_end:]
                    assigns_path = re.match(r"\s*<-", tail) is not None
                    mutates_path = re.match(r"\s*\.\s*(?:" + _services['MUTATORS'] + r")\s*\(", tail) is not None
                    if allocates or assigns_path or mutates_path or "&" in lead:
                        writes.add("global:" + m.group(1))
            for alias in sorted(global_aliases):
                ae = re.escape(alias)
                alias_part = r"(?:\s*\.\s*\w+|\s*\[[^\]\n]*\])"
                alias_path = r"\b" + ae + alias_part + r"*"
                if alias in borrowed_global_aliases and re.search(r"\b" + ae + r"\s*<-", text):
                    writes.add("global-alias:" + alias)
                if re.search(r"\b" + ae + alias_part + r"+\s*<-", text):
                    writes.add("global-alias:" + alias)
                if re.search(alias_path + r"\.(?:" + _services['MUTATORS'] + r")\(", text):
                    writes.add("global-alias:" + alias)
                if re.search(r"\bin\s+" + alias_path + r"\s*:", text) or re.search(r"&\s*" + alias_path, text):
                    writes.add("global-alias:" + alias)
            for site in _services['ast_constructions'](text):
                writes.add("ast:" + site)
            # A mutable-reference cast can turn an otherwise immutable view into
            # a write-capable pointer. Keep it out of the append-only closure even
            # when the view arrives inside a copied record from a caller.
            mutable_cast_sources = _services['mutable_cast_source_names'](
                d["params"], code_text, type_aliases, struct_field_types, globals_
            )
            cast_targets = re.compile(r"\.\s*cast\s*\[(?P<target>[^\]\n]+)\]")
            parsed_casts = {
                cast.start("target"): cast
                for cast in _services['MUTABLE_POINTER_CAST_RE'].finditer(code_text)
            }
            for cast in cast_targets.finditer(code_text):
                target_type = cast.group("target").strip()
                if _services['type_expression_is_mutable_ref'](target_type, type_aliases):
                    # The target alone proves the cast creates write capability. Do not
                    # depend on recognizing a field, index, or method-call receiver.
                    writes.add("mutable-view-pointer-cast")
                    break
                if _services['is_builtin_scalar_type'](target_type, type_aliases):
                    continue
                parsed = parsed_casts.get(cast.start("target"))
                if parsed is not None and parsed.group("root") in mutable_cast_sources:
                    writes.add("mutable-view-pointer-cast")
                    break
                line_start = code_text.rfind("\n", 0, cast.start()) + 1
                receiver_text = code_text[line_start:cast.start()]
                assignment = re.search(r"(?:<-|(?<![=!<>])=(?!=))", receiver_text)
                if assignment is not None:
                    receiver_text = receiver_text[assignment.end():]
                if any(
                    re.search(r"\b" + re.escape(source) + r"\b", receiver_text)
                    for source in mutable_cast_sources
                ) or (parsed is None and mutable_cast_sources):
                    # Complex call/index receivers are intentionally not parsed here.
                    # If one contains a known shared or reference-bearing source, or
                    # cannot be parsed at all in a function with such a source, fail
                    # closed instead of missing an alias hidden behind the call.
                    writes.add("mutable-view-pointer-cast")
                    break
            # A local diagnostics alias can be inspected or can replace/clear diagnostics
            # from earlier sequential passes. Treat any such alias as a dependency on the
            # accumulated diagnostics stream instead of trying to infer its use mode.
            if diagnostic_aliases:
                reads_diag = True
            # A raw pointer cast can let a value stored in the shared table escape as an
            # address. Catch direct paths too; the local alias pass below handles copied
            # reference-bearing fields such as `name: sview = table.current_name`.
            table_field_part = r"(?:\s*\.\s*\w+|\s*\[[^\]\n]*\])"
            for table in sorted(tables):
                te = re.escape(table)
                table_cast_source = re.compile(
                    _services['BORROWED_NAME_PREFIX'] + r"\b" + te + r"\b\s*\.\s*(?P<field>\w+)"
                    + table_field_part + r"*(?:\s*\))*\s*\.\s*cast\s*\["
                )
                if any(match.group("field") != "diagnostics" for match in table_cast_source.finditer(code_text)):
                    writes.add("table-backed-address-cast")
            for alias in sorted(field_aliases):
                ae = re.escape(alias)
                alias_part = table_field_part
                cast_source = _services['BORROWED_NAME_PREFIX'] + r"\b" + ae + r"\b" + alias_part + r"*(?:\s*\))*"
                # A copied `sview` is still a reference-bearing alias. Its `.data` pointer
                # can be cast and escape even though the local itself was not borrowed with `&`.
                if re.search(cast_source + r"\s*\.\s*cast\s*\[", code_text):
                    writes.add("table-backed-address-cast")
                alias_type = _services['local_path_expression_type'](alias, text, struct_field_types)
                if _services['is_detached_copy_value'](alias_type, type_aliases, struct_field_types):
                    # Keep the address-escape check above, but mutations and borrows
                    # of a detached local copy cannot write through to its table source.
                    continue
                alias_path = r"\b" + ae + alias_part + r"*"
                if alias in borrowed_field_aliases and re.search(r"\b" + ae + r"\s*<-", text):
                    writes.add("alias:" + alias)
                if re.search(r"\b" + ae + alias_part + r"+\s*<-", text):
                    writes.add("alias:" + alias)
                if re.search(alias_path + r"\.(?:" + _services['MUTATORS'] + r")\(", text):
                    writes.add("alias:" + alias)
                if re.search(r"\bin\s+" + alias_path + r"\s*:", text) or re.search(r"&\s*" + alias_path, text):
                    writes.add("alias:" + alias)
            for m in _services['CALL_RE'].finditer(code_text):
                callee = m.group(1)
                receiver = _services['receiver_before_call'](code_text, m.start())
                source_receiver_dispatch = bool(
                    receiver
                    and not _services['receiver_is_static_owner'](receiver)
                    and _services['receiver_method_has_source_dispatch'](
                        receiver,
                        callee,
                        text,
                        tables,
                        table_field_types,
                        type_aliases,
                        struct_field_types,
                        defs,
                    )
                )
                if (
                    callee in defs
                    and callee != name
                    and (receiver is None or _services['receiver_is_static_owner'](receiver) or source_receiver_dispatch)
                ):
                    callees.add(callee)
                if any(candidate.get("external") for candidate in defs.get(callee, ())):
                    writes.add("external-call:" + callee)
                if callee in globals_ or callee in global_aliases:
                    writes.add("global-callable:" + callee)
            for callee, receiver, arguments in _services['call_sites'](code_text):
                if (
                    receiver is None
                    and not defs.get(callee)
                    and callee not in _services['NON_CALL_KEYWORDS']
                    and callee not in _services['PURE_FREE_CALLS']
                ):
                    writes.add("unknown-call:" + callee)
                elif receiver is not None and callee in _services['BUILTIN_NUMERIC_CAST_METHODS']:
                    receiver_type = _services['receiver_expression_type'](
                        receiver,
                        text,
                        tables,
                        table_field_types,
                        type_aliases,
                        struct_field_types,
                        defs,
                    )
                    cast_candidates = defs.get("__cast__", ())
                    selected_cast_indexes = _services['matching_cast_candidate_indexes'](
                        cast_candidates, receiver_type, callee, type_aliases
                    ) if cast_candidates else []
                    selected_casts = [cast_candidates[index] for index in selected_cast_indexes]
                    if selected_casts:
                        if _build_cast_nodes:
                            for index, candidate in zip(selected_cast_indexes, selected_casts):
                                node = "__cast__@" + str(index)
                                callees.add(node)
                                cast_nodes[node] = candidate
                        else:
                            callees.add("__cast__")
                        if any(candidate.get("external") for candidate in selected_casts):
                            writes.add("external-call:__cast__")
                        if _services['mutable_actual_indexes']([receiver], selected_casts) and (
                            _services['argument_is_table_backed'](receiver, tables, table_aliases, field_aliases)
                            or _services['argument_global_names'](receiver, globals_, global_aliases)
                        ):
                            writes.add("mutable-or-unknown-table-field-argument:" + callee)
                        handled_cast_sites.add((callee, receiver))
                    elif (
                        receiver_type
                        and (
                            _services['is_builtin_scalar_type'](receiver_type, type_aliases)
                            or any(
                                fields == []
                                for fields in struct_field_types.get(
                                    receiver_type.rsplit("::", 1)[-1].rstrip("&?").strip(), ()
                                )
                            )
                        )
                    ) or (
                        (table_receiver_type := _services['table_field_expression_type'](
                            receiver,
                            tables,
                            table_field_types,
                            type_aliases,
                            struct_field_types,
                        ))
                        and _services['type_is_copy_value'](
                            table_receiver_type,
                            type_aliases,
                            struct_field_types,
                        )
                    ):
                        # With no matching user hook, scalar/const-enum conversions
                        # are built-in. A table-field receiver with a statically Copy
                        # value type is also safe to pass through this conversion: it
                        # cannot expose a mutable table alias. Exact __cast__ overloads
                        # were handled above using their selected-effect summaries.
                        handled_cast_sites.add((callee, receiver))
                if (
                    receiver is not None
                    and (callee, receiver) not in handled_cast_sites
                    and callee not in _services['NON_CALL_KEYWORDS']
                    and not (
                        callee == "push"
                        and _services['is_diagnostics_receiver'](receiver, tables, diagnostic_aliases)
                    )
                    and not (_services['receiver_is_static_owner'](receiver) and defs.get(callee))
                    and not _services['receiver_method_has_source_dispatch'](
                        receiver,
                        callee,
                        text,
                        tables,
                        table_field_types,
                        type_aliases,
                        struct_field_types,
                        defs,
                    )
                    and not _services['receiver_method_is_known_intrinsic'](
                        receiver,
                        callee,
                        text,
                        tables,
                        table_field_types,
                        type_aliases,
                        struct_field_types,
                        defs,
                        enum_variants,
                    )
                ):
                    writes.add("unknown-receiver-call:" + callee)
            # Reject calls through global function values, including nested indexing
            # and parenthesized callables which the name-only CALL_RE cannot resolve.
            writes.update("global-callable:" + name for name in _services['_global_callable_names'](text, globals_ | global_aliases))
            # A table field can be mutated through a helper's mutable container parameter
            # or a user method's mutable receiver without the helper receiving a
            # SymbolTable. The direct table-field checks above cannot see that alias, so
            # fail closed for such calls. The same applies when a local simply aliases a
            # table field. This intentionally accepts some false positives: those passes
            # run serially until the helper exposes an append-only contract.
            has_table_field_actual = bool(tables) and re.search(
                r"\b(?:" + "|".join(sorted(map(re.escape, tables))) + r")\b", text
            )
            has_alias_actual = bool(field_aliases)
            has_global_actual = bool(globals_) and glob_re.search(text)
            if has_table_field_actual or has_alias_actual or has_global_actual or global_aliases:
                for callee, receiver, arguments in _services['call_sites'](code_text):
                    if callee in _services['NON_CALL_KEYWORDS']:
                        continue
                    if callee in _services['READ_ONLY_TABLE_CALLS']:
                        continue
                    candidates = defs.get(callee)
                    actuals = list(arguments)
                    diagnostic_append = (
                        callee == "push"
                        and receiver is not None
                        and _services['is_diagnostics_receiver'](receiver, tables, diagnostic_aliases)
                    )
                    if diagnostic_append:
                        continue
                    if receiver is not None and (callee, receiver) in handled_cast_sites:
                        continue
                    table_receiver = bool(
                        receiver and _services['argument_is_table_backed'](
                            receiver, tables, table_aliases, field_aliases
                        )
                    )
                    derived_table_receiver = bool(
                        receiver
                        and not table_receiver
                        and any(
                            _services['argument_is_table_backed'](argument, tables, table_aliases, field_aliases)
                            for _inner_callee, _inner_receiver, inner_arguments in _services['call_sites'](receiver)
                            for argument in inner_arguments
                        )
                    )
                    global_receiver_names = (
                        _services['argument_global_names'](receiver, globals_, global_aliases)
                        if receiver else set()
                    )
                    if global_receiver_names:
                        # A method on shared global state can return a mutable alias even
                        # when its formal receiver is immutable. Without return-effect
                        # summaries, keep the caller out of parallel batches.
                        writes.add("global-receiver-call:" + callee)
                    if table_receiver and re.fullmatch(_services['MUTATORS'], callee):
                        writes.add("mutable-or-unknown-table-field-argument:" + callee)
                    if derived_table_receiver and (
                        re.fullmatch(_services['MUTATORS'], callee)
                        or not candidates
                        or callee not in _services['READ_ONLY_TABLE_METHODS']
                    ):
                        writes.add("mutable-or-unknown-table-field-argument:" + callee)
                    if (
                        receiver
                        and not diagnostic_append
                        and (
                            table_receiver or bool(global_receiver_names)
                        )
                        and (
                            global_receiver_names
                            or candidates
                            or re.fullmatch(_services['MUTATORS'], callee)
                            or callee not in _services['READ_ONLY_TABLE_METHODS']
                        )
                    ):
                        # Source-defined receiver methods are checked against their
                        # explicit first formal. Built-in mutators and unresolved
                        # methods have no source signature here, so conservatively
                        # treat the table-backed receiver as an argument to an
                        # unknown mutable effect. Known read-only built-ins are the
                        # narrow exception that preserves parallelism for lookups.
                        actuals.insert(0, receiver)
                    if _services['call_may_mutate_table_field'](
                        actuals,
                        candidates,
                        tables,
                        field_aliases,
                        table_field_types,
                        type_aliases,
                        struct_field_types,
                        text=text,
                        allow_copied_values=bool(
                            receiver and not table_receiver and callee == "push"
                        ),
                        builtin_value_push=bool(
                            receiver
                            and not table_receiver
                            and callee == "push"
                            and not candidates
                            and _services['is_builtin_darray_type'](
                                _services['local_path_expression_type'](receiver, text, struct_field_types),
                                type_aliases,
                            )
                        ),
                    ):
                        writes.add("mutable-or-unknown-table-field-argument:" + callee)
                    if any(
                        _services['argument_is_whole_table'](argument, tables, table_aliases)
                        for argument in actuals
                    ) and (
                        not candidates
                        or any(candidate.get("external") for candidate in candidates)
                    ):
                        writes.add("unknown-or-external-whole-table-argument:" + callee)
                    mutable_actuals = _services['mutable_actual_indexes'](actuals, candidates)
                    for index, argument in enumerate(actuals):
                        if index in mutable_actuals:
                            writes.update(
                                "mutable-global-argument:" + name
                                for name in _services['argument_global_names'](argument, globals_, global_aliases)
                            )
        info[name] = (writes, reads_diag, callees)
    if _build_cast_nodes:
        for node, candidate in cast_nodes.items():
            specialized_defs, nested_cast = _services['specialized_cast_definitions'](defs, candidate)
            specialized_info = _services['analyze'](
                specialized_defs,
                globals_,
                mutable_ref_globals,
                type_aliases,
                table_field_types,
                struct_field_types,
                enum_variants,
                _build_cast_nodes=False,
            )
            writes, reads_diag, callees = specialized_info.get("__cast__", (set(), False, set()))
            if nested_cast:
                writes = set(writes) | {"unknown-nested-cast"}
            info[node] = (writes, reads_diag, callees)
    return info
