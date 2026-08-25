# Elisa WebAssembly

WASM is a first-class product target. One command produces a browser- and Node-ready
module plus the small amount of glue that normally becomes an integration project:

```sh
scripts/elisac_stage1.sh -emit wasm -o build/hello.wasm examples/hello.elisa
```

That writes four colocated artifacts:

| File | Purpose |
| --- | --- |
| `hello.wasm` | Linked `wasm32` module with imported linear memory |
| `hello.mjs` | zero-dependency ESM loader and typed-friendly export facade |
| `hello.d.ts` | TypeScript declarations for the loader and exports |
| `hello.json` | stable manifest describing target, memory policy, and exports |

## Exporting Elisa functions

Expose a scalar or pointer-shaped adapter with an explicit export name:

```elisa
def add(a: i32, b: i32) -> i32:
    return a + b

export fn add_wasm(a: i32, b: i32) -> i32 = add
```

The generated facade normalizes the awkward parts of the WebAssembly JavaScript ABI:

- `i8`/`i16`/`i32` and `u8`/`u16`/`u32` use JavaScript `number` with correct signedness.
- `i64`, `u64`, `int`, and `char` use JavaScript `bigint`.
- `usize`, `isize`, and `uintptr` are compiled as 32-bit WASM values; unsigned values
  arrive normalized with `>>> 0`.
- `bool` is accepted as a JavaScript boolean and returned as a boolean.
- references and `cstr` are exposed as numeric pointers. For a pleasant public API,
  keep those behind Elisa adapters or add a project-specific wrapper around `memory`.

Aggregate exports are intentionally rejected with an actionable diagnostic. This keeps
the generated API stable instead of silently inventing a struct layout; Elisa-side scalar
and pointer adapters are the escape hatch for arrays, strings, and records.

## Loading the module

The generated loader works without a bundler:

```js
import loadWasm from "./hello.mjs";

const hello = await loadWasm();
console.log(hello.add_wasm(40, 2));
```

It accepts a URL/path, `Response`, `ArrayBuffer`, or typed array. Node can load the default
adjacent `.wasm` file; browsers fetch it relative to the module URL. The returned object is
immutable and exposes `memory` plus `raw` for deliberate low-level integrations.

The runtime imports memory from the `env` module. Custom imports win over the defaults:

```js
const hello = await loadWasm("./hello.wasm", {
  initialPages: 32,
  maximumPages: 4096,
  onPrint: (line) => console.log("Elisa:", line),
  env: { puts: (pointer) => { /* project-specific console bridge */ return 0; } },
});
```

The default import table includes a bump allocator, memory growth, common libc-shaped byte
helpers, `puts`, and a safe `exit` bridge. This makes the portable Elisa runtime usable in a
browser without requiring libc, Emscripten, or a JavaScript package manager.

## Tooling and targets

The wrapper locates `wasm-ld` next to `llvm-config`, on `PATH`, or through `WASM_LD` (or the
explicit `--wasm-ld` option). The current product target is `wasm32-unknown-unknown`; pass
another `wasm32-*` triple with `-target-triple` when a host/runtime profile needs one.

The generated manifest is deliberately simple JSON so build systems, the Elisa LSP, and
future devtools can consume it without parsing JavaScript. The end-to-end contract lives in
`test/parity/wasm_smoke.sh`.
