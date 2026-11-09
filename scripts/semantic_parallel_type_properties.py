"""Type properties for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def copy_alias_view_base_type(_services, expression):
    """A view lifetime does not change its copyability or backing mutability."""
    if expression.startswith("sview") and re.fullmatch(
        r"sview\s*@(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*", expression
    ):
        return "sview"
    return expression

def type_is_copy_value(_services, type_expression, aliases, structs, seen=frozenset()):
    """Whether a type is safely copied, using an iterative alias/struct walk.

    Deep generated alias chains are common enough to avoid Python recursion here.
    The walk is O(V + E), memoized by terminal type name, and cycles fail closed.
    """
    def classify(expression):
        expression = expression.strip()
        while expression.startswith("(") and _services['matching_delimiter'](expression, 0) == len(expression) - 1:
            expression = expression[1:-1].strip()
        while expression.endswith("?"):
            expression = expression[:-1].rstrip()
        if "&" in expression:
            # Copying an immutable reference cannot mutate its referent. A mutable
            # reference alias remains tainted even when reached through a type alias.
            return ("value", expression.endswith("&") and not
                    _services['type_expression_is_mutable_ref'](expression, aliases))
        expression = re.sub(r"^(?:(?:mutable|static|heap|stack)\s+)+", "", expression)
        expression = _services['copy_alias_view_base_type'](expression)
        if "[" in expression or "{" in expression or "," in expression:
            return "invalid", None
        if not re.fullmatch(r"(?:\w+::)*\w+", expression):
            return "invalid", None
        name = expression.rsplit("::", 1)[-1]
        if name in _services['COPY_VALUE_TYPE_NAMES']:
            return "value", True
        return "name", name

    kind, root = classify(type_expression)
    if kind == "value":
        return root
    if kind == "invalid":
        return False

    memo = {}
    active = set(seen)
    frames = []

    def push(name):
        if name in memo:
            return
        if name in active:
            return
        active.add(name)
        candidates = aliases.get(name, ())
        if candidates:
            children = list(candidates)
        else:
            struct_candidates = structs.get(name, ())
            if not struct_candidates:
                memo[name] = False
                active.remove(name)
                return
            # A const enum has an empty field list and therefore copies by value.
            children = [
                field_type
                for fields in struct_candidates
                for field_type in (fields.values() if isinstance(fields, dict) else fields)
            ]
        frames.append([name, children, 0, True])

    push(root)
    while frames:
        name, children, index, result = frames[-1]
        if not result:
            memo[name] = False
            active.remove(name)
            frames.pop()
            if frames:
                # This child is one of the parent's required fields/alias targets.
                frames[-1][3] = False
            continue
        if index >= len(children):
            memo[name] = True
            active.remove(name)
            frames.pop()
            continue

        child_kind, child = classify(children[index])
        frames[-1][2] += 1
        if child_kind == "value":
            if not child:
                frames[-1][3] = False
        elif child_kind == "invalid" or child in active or child in seen:
            # Unknown types and recursive cycles are conservatively non-copy.
            frames[-1][3] = False
        elif child in memo:
            if not memo[child]:
                frames[-1][3] = False
        else:
            parent_frame = frames[-1]
            push(child)
            # Unknown names are memoized as non-copy values without adding a frame.
            # Propagate that result now; framed children propagate it when they pop.
            if child in memo and not memo[child]:
                parent_frame[3] = False

    return memo.get(root, False)

def type_may_contain_reference(_services, type_expression, aliases, structs):
    """Whether a copied type could still carry a reference into shared storage."""
    pending = [type_expression]
    visited = set()
    while pending:
        expression = pending.pop().strip()
        while expression.startswith("(") and _services['matching_delimiter'](expression, 0) == len(expression) - 1:
            expression = expression[1:-1].strip()
        while expression.endswith("?"):
            expression = expression[:-1].rstrip()
        if "&" in expression:
            return True
        expression = re.sub(r"^(?:(?:mutable|lmut|static|heap|stack)\s+)+", "", expression)
        expression = _services['copy_alias_view_base_type'](expression)
        if "[" in expression or "{" in expression or "," in expression:
            # Generic containers and compound types are not needed to prove the
            # copy-only return case; fail closed if the copy checker admits one.
            return True
        if not re.fullmatch(r"(?:\w+::)*\w+", expression):
            return True
        name = expression.rsplit("::", 1)[-1]
        if name == "sview":
            # sview is bitwise-copyable, but its data pointer can still refer into
            # shared storage and outlive the object that owns that backing.
            return True
        if name in _services['COPY_VALUE_TYPE_NAMES']:
            continue
        if name in visited:
            continue
        visited.add(name)
        candidates = aliases.get(name, ())
        if candidates:
            pending.extend(candidates)
            continue
        schemas = structs.get(name, ())
        if not schemas:
            return True
        for fields in schemas:
            if isinstance(fields, dict):
                pending.extend(fields.values())
            else:
                pending.extend(fields)
    return False

def type_may_contain_mutable_alias(_services, type_expression, aliases, structs):
    """Whether a copied value can retain mutable owned storage or a mutable borrow.

    Immutable views are allowed here: parallel semantic workers can read table-owned
    text for the duration of the synchronous join, while mutable containers and mutable
    references could expose writes or outlive a reallocated owner.
    """
    def classify(expression):
        expression = expression.strip()
        while expression.startswith("(") and _services['matching_delimiter'](expression, 0) == len(expression) - 1:
            expression = expression[1:-1].strip()
        while expression.endswith("?"):
            expression = expression[:-1].rstrip()
        if re.search(r"\blmut\b", expression):
            return "value", True
        if "&" in expression:
            return "value", _services['type_expression_is_mutable_ref'](expression, aliases)
        expression = re.sub(r"^(?:(?:mutable|lmut|static|heap|stack)\s+)+", "", expression)
        expression = _services['copy_alias_view_base_type'](expression)
        if "[" in expression or "{" in expression or "," in expression:
            return "invalid", True
        if not re.fullmatch(r"(?:\w+::)*\w+", expression):
            return "invalid", True
        name = expression.rsplit("::", 1)[-1]
        if name == "sview" or name in _services['COPY_VALUE_TYPE_NAMES']:
            return "value", False
        return "name", name

    kind, root = classify(type_expression)
    if kind == "value":
        return root
    if kind == "invalid":
        return True

    # A type is safe only after every alias/record edge has completed without
    # finding a mutable owner. An edge back to an active node is an unresolved
    # recursive cycle, so fail closed instead of treating it as an already-seen
    # safe type.
    state = {}
    memo = {}
    frames = []

    def push(name):
        candidates = list(aliases.get(name, ()))
        schemas = structs.get(name, ())
        children = candidates + [
            field_type
            for fields in schemas
            for field_type in (fields.values() if isinstance(fields, dict) else fields)
        ]
        if not candidates and not schemas:
            state[name] = 2
            memo[name] = True
            return
        state[name] = 1
        frames.append([name, children, 0, False])

    push(root)
    while frames:
        name, children, index, unsafe = frames[-1]
        if unsafe:
            memo[name] = True
            state[name] = 2
            frames.pop()
            if frames:
                frames[-1][3] = True
            continue
        if index >= len(children):
            memo[name] = False
            state[name] = 2
            frames.pop()
            continue

        child_kind, child = classify(children[index])
        frames[-1][2] += 1
        if child_kind == "value":
            if child:
                frames[-1][3] = True
        elif child_kind == "invalid":
            frames[-1][3] = True
        elif state.get(child) == 1:
            frames[-1][3] = True
        elif state.get(child) == 2:
            if memo[child]:
                frames[-1][3] = True
        else:
            parent = frames[-1]
            push(child)
            if state.get(child) == 2 and memo[child]:
                parent[3] = True

    return memo[root]

def type_is_top_level_reference(_services, type_expression, aliases):
    """Whether this value is itself a reference, including through simple aliases."""
    pending = [type_expression]
    visited = set()
    while pending:
        expression = pending.pop().strip()
        while expression.startswith("(") and _services['matching_delimiter'](expression, 0) == len(expression) - 1:
            expression = expression[1:-1].strip()
        while expression.endswith("?"):
            expression = expression[:-1].rstrip()
        if "&" in expression or re.search(r"\blmut\b", expression):
            return True
        expression = re.sub(r"^(?:(?:mutable|static|heap|stack)\s+)+", "", expression)
        if not re.fullmatch(r"(?:\w+::)*\w+", expression):
            continue
        name = expression.rsplit("::", 1)[-1]
        if name in visited:
            return True
        visited.add(name)
        pending.extend(aliases.get(name, ()))
    return False

def is_detached_copy_value(_services, type_expression, aliases, structs):
    """A by-value copy with no mutable owner alias and no top-level borrow."""
    return bool(
        type_expression
        and _services['type_is_copy_value'](type_expression, aliases, structs)
        and not _services['type_may_contain_mutable_alias'](type_expression, aliases, structs)
        and not _services['type_is_top_level_reference'](type_expression, aliases)
    )
