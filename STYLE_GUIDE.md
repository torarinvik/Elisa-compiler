# Elisa style guide: expression-based, scope-minimal code

Two principles, one idea:

1. **Every name should end where its job ends.** A local must not stay visible (or mutable)
   after its last use.
2. **Avoid plain statements whenever possible.** Prefer forms that produce a value over void
   statements whose effect is invisible at the use site.

This guide aligns with `docs/119_expression_unification.md` (value blocks, loop values,
captures); that document is the language reference, this one is the house style. The lint that
enforces principle 1 is `-Wnever-leak` (section 7).

Status key: **[working]** examples compile with stage1 today; **[in progress]** and
**[planned]** sections are design, not yet usable.

1. [Plain statements are the fallback](#1-plain-statements-are-the-fallback)
2. [Block expressions](#2-block-expressions)
3. [region blocks](#3-region-blocks)
4. [Loop header captures](#4-loop-header-captures)
5. [Loop expressions](#5-loop-expressions)
6. [Value-threading (planned)](#6-value-threading-planned)
7. [Borrow exclusivity](#7-borrow-exclusivity)
8. [Compiler flags and reading a diagnostic](#8-compiler-flags-and-reading-a-diagnostic)
9. [When not to apply the style](#9-when-not-to-apply-the-style)
10. [Adoption](#10-adoption)

## 1. Plain statements are the fallback

A plain statement (a call or assignment with no value to bind) changes state somewhere the
reader cannot see. Reach for a value form first: a block expression, a loop expression, a tuple
yield, or `x <- f(x)`. Use a plain statement only when no value form fits: side-effect-only
calls (`print`, `sink`), arenas, globals, data behind borrows. Then wrap it in
`region NAME_scope:` so its locals end with it.

Prefer (value form, nothing leaks):

```elisa
lol: i64 =
    bar: i64 = seed + 1
    baz(bar)
sink(lol)
```

Instead of (`bar` stays visible, and the real work hides in a call statement):

```elisa
bar: i64 = seed + 1
sink(baz(bar))
sink(seed)
```

Prefer, when the plain statement is unavoidable:

```elisa
region bar_scope:
    bar: i64 = seed + 1
    sink(baz(bar))
sink(seed)
```

The never-leak finding kind **plain** is the compiler's pointer to exactly these sites: a
local whose last use is a statement with no value to bind.

## 2. Block expressions

A binding whose initializer is an indented block; the last line is the value, and locals
declared inside vanish afterwards. **[working]**

Prefer:

```elisa
lol: i64 =
    bar: i64 = seed + 1
    baz(bar)
sink(lol)
```

Instead of:

```elisa
bar: i64 = seed + 1
lol: i64 = baz(bar)
sink(lol)
```

Rationale: `bar` has one job, feeding `lol`. After `lol` exists nothing can misuse it.

When the block updates an outer variable, list it in a `|count|` capture (it must be mutable):

```elisa
total: i64 = |count|
    step: i64 = seed * 3
    count <- count + 1
    step + count
```

To yield several values, bind a tuple and end the block with a tuple:

```elisa
lo, hi =
    base: i64 = seed * 2
    (base - 1, base + 1)
```

Reading outer bindings needs no capture; mutating one does. A trivial initializer needs no block.

## 3. region blocks

For statements that bind nothing, `region NAME_scope:` is the scope. Name it `<local>_scope`
after what it contains. **[working]**

Prefer:

```elisa
region bar_scope:
    bar: i64 = seed + 1
    sink(baz(bar))
sink(seed)
```

Instead of:

```elisa
bar: i64 = seed + 1
sink(baz(bar))
sink(seed)
```

A `region` also frees what its statements allocate when it ends. If something allocated inside
must outlive it, bind it with a block expression instead, or move the code into a helper.

## 4. Loop header captures

A counter belongs to its loop, so declare it in the loop header. **[working]**

Prefer:

```elisa
while index < limit |index: i64 = 0|:
    sink(index)
    index <- index + 1
```

Instead of:

```elisa
index: mutable i64 = 0
while index < limit:
    sink(index)
    index <- index + 1
```

The header binding is mutable inside the loop and invisible after it.

## 5. Loop expressions

A loop with a `-> yield` header is an expression; its result is the captures at loop exit, and
zero iterations yield the initial values. A bare `for`/`while` in value position is an error.
Loop expressions exist on main (see `test/differential/cases/loop_break_value.elisa`).
**[working]** The never-leak *accumulator* finding kind points you to these sites, and the
scoped form compiles to the same machine code as the `mutable` + loop form at -O0 and -O2
(`test/parity/loop_value_codegen_smoke.sh`). Gentle mode and `-Werror=never-leak` report only
accumulators with a rewrite; `-Wnever-leak=strict` also lists candidates no rewrite fits, with the
exact reason (read inside the loop, changed after it, not a scalar, outer `break`/`continue`).

Prefer:

```elisa
sum: usize =
    for num in numbers |sum: usize = 0| -> sum:
        sum += num
```

Instead of:

```elisa
sum: mutable usize = 0
for num in numbers:
    sum += num
```

Several accumulators yield a tuple:

```elisa
total, count =
    for x in xs |total: i64 = 0, count: usize = 0| -> (total, count):
        total += x
        count += 1
```

A search loop uses `break VALUE if COND`, which assigns the capture and exits. Optionals are
written `T?`:

```elisa
found: usize? =
    for i in 0..<xs.count |hit: usize? = null| -> hit:
        break i if xs[i] == want
```

If the loop finishes without breaking, `found` is `null`, the initial value.

## 6. Value-threading (planned)

**[planned, Phase 2: design only, does not compile today.]** For an owned value, thread it
through the call instead of lending it:

```text
Prefer:      arr <- arr.push(x)
Instead of:  push(&arr, x)

Prefer:      a, last = a.pop()
```

`&` stays for data reached through borrows, fields of borrowed structs, arenas, globals, and
side-effect-only functions. The two spellings must compile to identical machine code; this is a
readability and exclusivity win, not an optimisation. One form works today: a pure function can
already be threaded through a global (section 7).

## 7. Borrow exclusivity

The compiler now enforces (`src/semantic/check_call_argument_exclusivity*.elisa`) that no two
borrows overlap across one call, whether they come from direct `&place` arguments, ref locals,
call results returning `T&`, conditional refs (`&x if c else &y`), borrows stored in
structs/arrays/dicts, or fn values. `Unsafe.*` code is opaque to the check. Fixtures:
`test/fixtures/borrow_exclusivity/`.

Lending a global to a callee that writes it is an error:

```text
def f(a: mutable i64&) -> i64:   # also writes `g` by name
f(&g)                            # rejected
```

The message ends "pass the value and assign the result (g <- f(g))". Rewrite as value
threading. **[working]**

```elisa
def f(n: i64) -> i64:
    return n + 1

global mutable g: i64 = 0

def thread_global() -> void:
    can Global.Write, Global.Read:
        g <- f(g)
```

For two borrows, split them onto disjoint fields, or pass one by value.

## 8. Compiler flags and reading a diagnostic

`-Wnever-leak` is opt-in and stage1 only.

| Flag | Effect |
| --- | --- |
| `-Wnever-leak`, `-Wnever-leak=gentle` | warn at the default (gentle) level |
| `-Wnever-leak=strict` | warn, and also flag the gentle exemption below |
| `-Werror=never-leak[=gentle\|strict]` | same, but findings are errors |
| `-permissive` | turns the lint off |

The `-W GROUP` spelling also works (`-W never-leak=strict`). A bare `-Werror=never-leak` keeps
the level set by an earlier flag. Gentle accepts a local whose last use is the statement right
after its declaration; strict flags it too. Exempt in both: parameters, `_`-prefixed names,
pattern and loop binders, borrow-exempt locals.

Finding kinds:

| Kind | Meaning | Fix |
| --- | --- | --- |
| chain | last use binds another local | nest in a block expression |
| chain with a loop jump | as chain, but a `break`/`continue` lies between | helper function |
| plain | last use is a statement with no value | `region` block (section 1) |
| overlap | a later local declared in the range is needed after it | reorder, then nest |
| loop | last use is a loop it feeds | move into the loop header |
| accumulator | a `mutable` local only a loop writes and only later code reads | loop expression (section 5) |

A real diagnostic (`test/fixtures/never_leak/expected-strict.txt`):

```text
illegal.elisa:12: warning: local `bar` stays visible after its last use [-Wnever-leak]
  declared on line 12, last used on line 13; still visible across 1 later statement (line 14, starting with `sink(lol)`)
  kind: chain (its last use binds another local, so that binding can take the statements as a block expression)
  note: -Wnever-leak=gentle (the default) accepts this local: its last use is the statement right after its declaration
  fix: nest it in a block expression that ends with its last use:
          lol: i64 =
              bar: i64 = seed + 1
              baz(bar)
          sink(lol)
```

Read it as: first line says which name and where; "kind" says why; "fix" is built from your
own lines, so paste it. The `note:` line appears only in strict mode. Now a `plain` one:

```text
  kind: plain (its last use is a statement with no value to bind)
  fix: the last use `sink(total)` is a plain statement, which cannot end a block expression, and Elisa has no bare statement block; scope the statements in a `region` block:
          region total_scope:
              total: i64 = step + count
              sink(total)
          return count
```

## 9. When not to apply the style

- **Borrow-exempt sites.** A buffer backing a live view must stay visible; nesting it would
  dangle the view. The lint records these and does not warn:

  ```elisa
  buffer: darray[u8] = [104, 105]
  view: sview = view_of(buffer)
  return sview_len(view)
  ```

- **Arenas.** A `region` frees what it allocates; do not wrap code whose allocations must
  outlive the scope.
- **Loop jumps.** A `break`/`continue` between a local and its last use blocks nesting (kind
  "chain with a loop jump"). Extract a helper function instead of contorting the loop.
- **Side-effect-only calls and globals** stay plain statements (section 1), in a `region` when
  they have locals.

## 10. Adoption

- New code follows the guide by default.
- Port a file when you are already touching it; do not make style-only sweeps of whole files.
- Turn on `-Werror=never-leak=strict` per directory once it is clean (`test/fixtures/never_leak/
  legal.elisa` and `fixed.elisa` are clean under both levels, and show the target shape).
