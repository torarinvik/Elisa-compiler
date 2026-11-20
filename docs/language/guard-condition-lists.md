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
immediate colon after `if`.
