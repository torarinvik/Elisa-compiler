# Refinements and contracts

## Contracts

Contracts are statements at the top of a function body:

```elisa
def half(x: i64) -> i64:
    requires x > 1
    ensure result > 0
    return x / 2
```

- `requires` is checked at every call site. A call that provably breaks it (`half(1)`) is an
  error, with no flag needed.
- `ensure` states a fact about `result`. Proving it needs the SMT tier.
- `assert` adds a fact inside the body.

The SMT tier is opt-in: set `ELISA_STAGE1_SMT=1`, or put `# smt` on the file's first line. It
proves more (`ensure` goals, relations between parameters), so some code that warns without
it is clean with it.

## Refinement types

`T is Law[args]` is `T` restricted to values that satisfy a law:

```elisa
law InRange(self: i64, low: i64, high: i64) = self >= low and self <= high

type ExitStatus = i64 is InRange[0, 255]
```

The law must be in scope: declared in the file or brought in by an `include` of the standard
library. A predicate with no law is rejected ("refinement predicate "InRange" is not a law"),
including inside a `type` alias. A name with no law body cannot be checked, so it is never
silently accepted.

A refinement applies to parameters, returns, struct fields, locals and aliases. A
module-qualified alias (`-> Cli::ExitStatus`) is checked like a bare one.

## Moving between `T` and `T is P`

- **Refined to plain:** always allowed. `s: i64 = status()` needs no check.
- **Plain to refined:** the value must be proven. Either of these works:
  - A literal that satisfies the law.
  - A guard that establishes it: `if v >= 0 and v <= 255: return v`.
- **Proven wrong:** a literal outside the law, such as `return 300` into `InRange[0, 255]`, is
  an error.
- **Not proven:** an unguarded value, such as `return v`, gets "could not be proven statically".
  It falls back to a runtime check.

Under SMT, a `requires` that mentions the value can supply the proof.

Regression fixture: `test/parity/refinement_gaps_smoke.sh`.
