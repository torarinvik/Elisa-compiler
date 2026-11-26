# Guard condition lists

An existing postfix statement guard can replace its single condition with a colon
and an indented, nonempty list of expressions:

```elisa
return null if:
    slot >= generics.names.count
    slot >= generics.decls.count

continue if:
    item.hidden
    item.disabled

break if:
    done
    remaining == 0
```

Each line must evaluate to `bool`. Conditions are evaluated in source order with
short-circuit `or`: the guarded statement runs when any condition is true. Later
conditions are skipped once a true condition is found. The returned value or
guarded action is evaluated only when the guard succeeds. This is the same
behavior as writing the conditions joined by `or` on one line.

## Negated lists: `if not:`

`if not:` takes the same indented list and runs the guarded statement unless every
condition holds. The conditions are evaluated in source order with short-circuit
`and`, and the result is negated: evaluation stops at the first false condition,
and the statement then runs.

```elisa
return false if not:
    header_matches(cached, expected)
    valid_path(artifact)

continue if not:
    item.visible
    item.enabled
```

This is the same as writing `return false if not (a and b)` on one line. It works
for every guard that takes `if:`.

## What a list may hold

Declarations, assignments, and statements are not condition entries. Empty lists
are rejected. Normal calls, comparisons, and boolean expressions are allowed.
The syntax also works for other existing statement guards, including call,
mutation, panic, and bare-return guards.

The canonical return spelling puts the keyword first: `return value if condition`
or `return value if:`. The accepted `value return if ...` spelling produces a
nonfatal style suggestion, and formatting uses the canonical form. Ternary
expressions keep their existing spelling, `value if condition else alternative`.
The prefix value-if form, `return if condition: value else: alternative`, is also
unchanged; its condition follows `if`, whereas a condition-list guard has an
immediate colon (or `not:`) after `if`.
