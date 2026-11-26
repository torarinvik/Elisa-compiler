# Elisa documentation

Start with the [quickstart](../README.md#run-your-first-program) and
[language style guide](../STYLE_GUIDE.md) if you are new to Elisa.

## Language and interop

- [Language notes](language/) cover integer behavior, regions, concurrency, and other language features, including [optional borrows](language/optional-borrows.md), [refinements and contracts](language/refinements-and-contracts.md), and [returning a grown container](language/returning-grown-containers.md).
- [Automatic memory management](automatic-memory-management.md) explains lifetime and allocation rules.
- [Expression forms](119_expression_unification.md) describes how value-producing blocks and control flow fit together.
- [Python extensions](interop/python.md) and [WebAssembly](interop/wasm.md) have runnable examples.

## Working on the compiler

- [Contributor guide](development/) covers verification, runtime synchronization, and generated files.
- [Compiler internals](compiler/) covers the self-hosted implementation and incremental compilation.
- [Qualification](qualification/) contains diagnostic and proof qualification material.
- [Roadmap](development/roadmap.md) records planned work and measurements.
- [Historical notes](history/) and [measurements](measurements/) record past experiments. The [porting gaps](PORTING_GAPS.md), [backend port notes](backend_port_notes.md), and [Stage1 performance notes](stage1_performance.md) also describe specific historical revisions.
