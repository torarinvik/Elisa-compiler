# Protocol parameters and painter receivers

`P` in `def draw[P: Painter](painter: P)` is a type parameter. The caller supplies a painter value; the compiler specializes the function for its concrete type. Calls can infer that type: `draw(my_painter)`.

A protocol annotation in a function's value parameter is shorthand for an inferred constrained type:

```elisa
def draw(painter: Painter) -> void:
    painter.paint()
```

Each such parameter is independent. `def combine(a: Painter, b: Painter)` may receive two different implementing types. Use `def combine[P: Painter](a: P, b: P)` when the parameters must share one type. Reference and mutability qualifiers remain attached to the parameter.

The annotation does not introduce a dynamically dispatched, boxed protocol value. Protocols remain constraints; a protocol alone is not a concrete field or return type. Use a concrete implementation or an explicit generic type for those positions.

Receiverless protocol methods remain valid for operations that belong to a type. For instance operations, declare `self: Self` and pass a value. In elisa-ui, `UiPaint::replay(painter)` and `replay_range(painter, start, end)` now use the value receiver. Builtin backends expose `painter()` factories. AppKit and UIKit painter values capture their current graphics context; other backends retain their existing managed backend state.

Runtime regression checks: `bash test/parity/protocol_parameters_smoke.sh`. This executes both compilers' objects and checks rejected protocol uses. elisa-ui also has `test/painter_instance_test.elisa` and its existing Skia recorder suite.
