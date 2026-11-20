# Module-private struct fields

Struct fields remain public by default. Use visibility sections to make stored
state private while exporting the type and its constructor:

```elisa
module Counter:
    struct Counter:
        private:
            count: mutable i64
        public:
            tag: i64

    def Counter() -> Counter:
        Counter{count: 0, tag: 1}
```

The declaring module and its descendants may access private fields. Other modules
may pass the type and call its public operations. Private field reads, writes,
reference access, destructuring, and record updates are rejected. Brace literals
cannot initialize a private field implicitly by omitting it. `zeroed` also checks
private stored fields recursively; zeroing a pointer or empty dynamic container
does not initialize its targets.

Privacy is compile-time metadata. It changes neither layout nor calling convention
and introduces no runtime allocation or access check. Explicitly unsafe memory
operations remain outside this boundary. A module may be reopened; this is module
visibility, not a file-level sealing mechanism.

The semantic pass retains declaration owners across aliases and block results.
Lowering repeats checks for concrete types resolved through generic substitution.
`test/parity/private_fields_smoke.py` exercises both compiler front doors and
compares the generated LLVM for matching public/private layouts byte-for-byte.
