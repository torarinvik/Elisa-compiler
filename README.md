# Elisa compiler

Elisa is a statically typed programming language with indentation-based syntax. It compiles to native code and WebAssembly and can expose functions to Python as native extensions. The compiler checks types, memory lifetimes, and effects before it emits executable code.

This repository contains **Stage1**, the compiler written in Elisa. **Stage0** is the Go compiler in [Elisa-core](https://github.com/torarinvik/Elisa-core). Stage0 builds the first Stage1 binary, a step called *bootstrapping*. Once built, Stage1 compiles Elisa programs directly and can compile its own source.

## Run your first program

These steps use Bash on macOS or Linux. Install Git, Go, Make, Python 3, LLVM development libraries with `llvm-config`, Clang, and Z3. The [Elisa-core build instructions](https://github.com/torarinvik/Elisa-core#build-the-compiler) cover platform-specific setup.

From a directory where you keep your projects, clone both repositories and build Stage0 first:

```sh
git clone https://github.com/torarinvik/Elisa-core.git
git clone https://github.com/torarinvik/Elisa-compiler.git
make -C Elisa-core/compiler build

cd Elisa-compiler
export ELISA_CORE="$(cd ../Elisa-core && pwd)"
export ELISACORE_BIN="$ELISA_CORE/compiler/bin/elisac"
scripts/elisac_stage1.sh --seed
```

Adjust `ELISA_CORE` if your Elisa-core checkout lives elsewhere. Set `LLVM_CONFIG` to the path of your chosen `llvm-config` if the wrapper picks up a different LLVM installation.

The included [Hello, Elisa example](examples/hello.elisa) uses `extern` to declare the C function `puts`. The indented body of `main` prints a line and returns zero to indicate success.

```elisa
extern puts(message: cstr) -> i32

def main() -> i64:
    _ = puts("Hello, Elisa!")
    return 0
```

Compile and run it:

```sh
scripts/elisac_stage1.sh -emit exe -o build/hello examples/hello.elisa
./build/hello
```

```text
Hello, Elisa!
```

Use `-emit obj` for an object file or `-emit llvm` to inspect the generated LLVM IR. To install a snapshot as `elisac-stage1`, run `scripts/install_stage1.sh`. It installs under `~/.elisac` by default.

## Explore Elisa

- [Language style guide](STYLE_GUIDE.md) covers common syntax and idioms.
- [Python extensions](docs/interop/python.md) explains native modules and generated type stubs.
- [WebAssembly](docs/interop/wasm.md) shows how to export a function and call it from JavaScript.
- [Documentation index](docs/) links to language notes, compiler internals, and development guides.

## Find your way around the repository

| Path | Contents |
| --- | --- |
| [`examples/`](examples/) | Small programs you can compile and run |
| [`src/driver/`](src/driver/) | Command-line driver and build orchestration |
| [`src/lexer/`](src/lexer/), [`src/parser/`](src/parser/) | Source text, tokens, and syntax trees |
| [`src/semantic/`](src/semantic/), [`src/ir/`](src/ir/) | Semantic checks and intermediate representation |
| [`src/backend/`](src/backend/) | LLVM lowering and code generation |
| [`elisacore_std/`](elisacore_std/) | Standard library and runtime vendored from Elisa-core |
| [`scripts/`](scripts/), [`tools/`](tools/) | Build scripts and development utilities |
| [`test/`](test/) | Fixtures, regressions, parity tests, and benchmarks |

To check a seeded compiler, run `test/parity/stage1_product_smoke.sh`. For compiler changes, run the full parity suite with `test/parity/run_all.sh --profile full`. The suite uses Stage0 as a reference for comparing compiler behavior. See the [contributor guide](docs/development/README.md) for test prerequisites and runtime synchronization.
