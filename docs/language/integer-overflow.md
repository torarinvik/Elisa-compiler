# Signed integer overflow

Signed `+`, `-` and `*` (`i8` to `i64`, `isize`) **trap** on two's-complement overflow by
default. This applies at every optimization level, `-O0` through `-O3`. The check lowers to
`llvm.s{add,sub,mul}.with.overflow` followed by a branch to `llvm.trap`, so an overflowing
program stops with `SIGTRAP` (exit status 133 in a shell). It never continues with a wrong
value.

Unsigned arithmetic wraps, as in stage0. Modular unsigned arithmetic is routinely
intentional, for example in hashes and ring counters. Division, remainder and shifts are
not affected by any of this.

## `-foverflow=trap|wrap`

| Mode | How to select it | Signed `+ - *` lowers to |
|---|---|---|
| `trap` (default) | no flag, `-foverflow=trap`, or `ELISACORE_OVERFLOW=trap` | checked intrinsic + trap |
| `wrap` | `-foverflow=wrap` or `ELISACORE_OVERFLOW=wrap` | plain `add`/`sub`/`mul`, **no `nsw`** |

- **Scope.** The mode applies to the whole compilation unit.
- **Wrap semantics.** `wrap` gives defined two's-complement wraparound. The flag deliberately
  omits `nsw`, which would turn an overflow into poison that the optimizer may exploit.
- **Env mirror.** `ELISACORE_OVERFLOW` is read by *value*. Only the exact string `wrap` turns
  checks off. An empty, misspelled (`Wrap`) or unknown value keeps the trapping default.
- **Precedence.** An explicit `-foverflow=trap` overrides an inherited `ELISACORE_OVERFLOW=wrap`.
- **Invalid modes.** Any other `-foverflow=` spelling is rejected as an unknown flag.

Use `wrap` only for a build whose arithmetic has been shown not to overflow, or where
wraparound is acceptable. It removes a runtime safety check. The static verifier's
"signed arithmetic does not overflow" assumption is backed at run time only in `trap`
mode.

## Difference from stage0

stage0 has no flag. It chooses by optimization level:

- It traps at `-O0`, or when contracts are forced.
- It wraps from `-O1` up.

This makes stage0 `-O0` equal to stage1's default, and stage0 `-O2` equal to stage1's
`-foverflow=wrap`. `test/parity/overflow_mode_smoke.sh` checks both pairings.

stage1 keeps trapping at `-O2` on purpose: an optimized build is not allowed to be less
safe than a debug build unless you explicitly ask for it.

## Tests

`test/parity/overflow_mode_smoke.sh` computes `i64::MAX + 1` from a runtime value and
checks all of the following:

- It traps under the default, under `-foverflow=trap`, and under `-foverflow=trap` with
  `ELISACORE_OVERFLOW=wrap` inherited. Each case is run at `-O0` and at `-O2`.
- It wraps to a negative value under `-foverflow=wrap` and under the env mirror.
- The IR in wrap mode has no `with.overflow` and no `nsw`.
- `-foverflow=saturate` is rejected.
