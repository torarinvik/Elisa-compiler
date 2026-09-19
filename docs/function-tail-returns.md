# Function tail returns

Block-bodied functions with an explicit non-void return type return their final
expression. A final `if`/`elif`/`else` or `match` passes that return position into
its branch/arm bodies, recursively. Terminal `catch` arms also inherit return
position; `raise`, `panic`, and `error` retain their terminating statement form. Explicit returns remain valid.

```elisa
def next(x: i64) -> i64:
    x + 1

def absolute(x: i64) -> i64:
    if x < 0:
        -x
    else:
        x
```

This infers the returned value, not the signature's return type. Functions with
no return annotation or `-> void` retain statement semantics. Non-final
expressions, loop bodies, and generic scoped/deferred blocks are not implicit
return positions in this initial implementation. Use explicit return inside
those scoped blocks. A missing branch still fails return coverage; wrong tail
types use the normal return-type diagnostic.

The parser normalizes tails to `Stmt.Return` before type checking, flow analysis,
proof analysis, and code generation. Source positions are retained. No new AST or
backend ABI is needed.

Regression fixtures: `backend/function_tail_error.elisa` checks fallible tails
and catch success/error paths (exit 0). Other fixtures: `backend/function_tail_returns.elisa` (exit 0), and
`diagnostics/function_tail_{type,missing_branch,loop}.neg.elisa` (reject).
The Go stage0 parser implements the same normalization, so the bootstrap compiler
and the self-hosted compiler agree on these tails. Separately built frontend
consumers still need a rebuild from their parser sources. The stage0 regression is
committed in the compiler repository as `26a06695`, with the void/unannotated
correction in `3a5520d`.

## Tuple tails

A bare comma-separated tuple can be the final expression of a function or of
its terminal branches, just as it can be the result of a value block:

```elisa
def adjacent(n: i64) -> (first: i64, second: i64):
    n, n + 1

def totals(n: i64) -> (sum: i64, count: i64):
    for index in 0..<n |sum: i64 = 0, count: i64 = 0| -> sum, count:
        sum <- sum + index
        count <- count + 1
```

The tuple uses the existing multi-value return representation; it introduces no
heap wrapper. Non-tail bare tuple lines outside value blocks remain rejected.
`test/differential/cases/tuple_function_tail.elisa` covers direct, branch, match,
block and loop results, empty loops, and deferred cleanup. The block-expression
parity gate runs it through both compilers at O0/O2 and compares optimized LLVM
for implicit and explicit tuple returns.

Tuple-valued calls and locals can also be destructured directly or as a block's
result. The backend evaluates the aggregate once, extracts its fields, and binds
or updates the destination variables. This is distinct from `lmut` thread claims;
ordinary struct results retain the existing claim behavior. Tests cover discarded
fields and reassignment, including a counter that detects repeated evaluation.
