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
This is a stage1 frontend feature; separately built frontend consumers need a
rebuild from these parser sources. Stage0 and vendored ElisaScript parsers are
not changed by this feature.
