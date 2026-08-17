#!/usr/bin/env bash
# The DRIVER's own include expansion, exercised through the CLI with no wrapper in front.
#
# Nothing used to cover this. Every other gate reaches the driver through
# scripts/elisac_stage1.sh, which flattens `include` directives in bash/Python before the
# binary runs — so `expand_includes` in elisac.elisa, the driver's own copy of that logic,
# was only ever reached by a user typing `elisac-stage1 file.elisa` directly. It was broken
# in two ways that no gate could see:
#
#   * A line longer than ~519 bytes PANICKED in the arena. The per-line accumulator grew
#     while the output and seen-path buffers were already live below it, and the driver's
#     arena can only grow its TAIL allocation, so arena_realloc panicked with "cannot grow
#     in place: not the tail allocation". That is most of the compiler's own sources.
#   * Paths were recorded as given rather than absolutised, so the same file reached by two
#     different relative spellings did not dedup: the closure over src/driver/elisac.elisa
#     reported 575 files where stage0 reports 509.
#
# The checks below are the two failure modes plus byte-parity of the resulting closure.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 300 "$@"; else "$@"; fi; }
set -u
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"

[ -x "$BIN" ] || { echo "cli_includes_smoke SKIP: no stage1 binary at $BIN"; exit 0; }
[ -x "$ELISACORE_BIN" ] || { echo "cli_includes_smoke SKIP: no elisac at $ELISACORE_BIN"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

pass=0; total=0
ok()   { pass=$((pass + 1)); }
fail() { echo "  FAIL $1"; }

# --- 1. Long lines ----------------------------------------------------------------------
# 519 bytes was the last width that worked and 522 the first that panicked, so the pair
# brackets the old boundary; the 8000-byte case is well past any plausible re-introduction.
for width in 400 522 8000; do
    total=$((total + 1))
    python3 - "$WORK/long_$width.elisa" "$width" <<'PY'
import sys
path, width = sys.argv[1], int(sys.argv[2])
pad = "x" * max(width - 30, 1)
open(path, "w").write("# %s\ndef main() -> i64:\n    return 0\n" % pad)
PY
    if RUN "$BIN" -emit deps -o "$WORK/long_$width.deps" "$WORK/long_$width.elisa" >/dev/null 2>&1; then
        ok
    else
        fail "long_line_$width: the CLI could not read a file with a ${width}-byte line (arena panic?)"
    fi
done

# --- 2. Dedup across differing relative spellings -----------------------------------------
# `sub/../shared.elisa` and `shared.elisa` are the same file. Recorded verbatim they are two
# entries; absolutised they are one. stage0 lists it once.
total=$((total + 1))
mkdir -p "$WORK/dedup/sub"
printf 'def shared() -> i64:\n    return 1\n' > "$WORK/dedup/shared.elisa"
printf 'include "../shared.elisa"\ndef mid() -> i64:\n    return shared()\n' > "$WORK/dedup/sub/mid.elisa"
printf 'include "./shared.elisa"\ninclude "./sub/mid.elisa"\ndef main() -> i64:\n    return mid()\n' > "$WORK/dedup/root.elisa"
"$ELISACORE_BIN" -emit deps -o "$WORK/dedup.s0" "$WORK/dedup/root.elisa" >/dev/null 2>&1
if RUN "$BIN" -emit deps -o "$WORK/dedup.s1" "$WORK/dedup/root.elisa" >/dev/null 2>&1 \
   && cmp -s "$WORK/dedup.s0" "$WORK/dedup.s1"; then
    ok
else
    echo "  FAIL dedup_relative_spellings: stage0 $(wc -l < "$WORK/dedup.s0" 2>/dev/null) entries, stage1 $(wc -l < "$WORK/dedup.s1" 2>/dev/null)"
fi

# --- 3. Byte-parity of the closure over the compiler's OWN sources -------------------------
# Real graphs, including the 509-file closure of the driver itself. A RELATIVE root path is
# used deliberately: absolutisation is the thing under test, and an absolute argument would
# pass even with it removed.
for root in src/lexer/lexer.elisa src/parser/parser.elisa src/backend/codegen.elisa \
            src/semantic/semantic.elisa src/driver/elisac.elisa; do
    for mode in deps deps-json; do
        total=$((total + 1))
        name="$(basename "$root" .elisa)_$mode"
        ( cd "$ROOT" && "$ELISACORE_BIN" -emit "$mode" -o "$WORK/$name.s0" "$root" >/dev/null 2>&1 )
        if ( cd "$ROOT" && RUN "$BIN" -emit "$mode" -o "$WORK/$name.s1" "$root" >/dev/null 2>&1 ) \
           && cmp -s "$WORK/$name.s0" "$WORK/$name.s1"; then
            ok
        else
            fail "$name: closure differs from stage0 ($(wc -l < "$WORK/$name.s0" 2>/dev/null) vs $(wc -l < "$WORK/$name.s1" 2>/dev/null) entries)"
        fi
    done
done

# --- 4. The CLI compiles the compiler ------------------------------------------------------
# The end the other three serve: `elisac-stage1 src/driver/elisac.elisa` with no wrapper and
# no pre-flattening. Asserts a non-trivial object rather than just rc=0, because an empty
# object would also exit 0.
total=$((total + 1))
if ( cd "$ROOT" && RUN "$BIN" -o "$WORK/self.o" src/driver/elisac.elisa >/dev/null 2>&1 ) \
   && [ -s "$WORK/self.o" ] \
   && [ "$(wc -c < "$WORK/self.o")" -gt 1000000 ]; then
    ok
else
    fail "self_compile: the CLI could not compile src/driver/elisac.elisa unaided"
fi

# --- 5. The driver's flattening and the wrapper's agree, BYTE FOR BYTE ---------------------
# Both routes compile the same sources; the only difference is who expanded the includes. The
# objects must therefore be identical. They were not: the driver's expansion emitted one extra
# blank line per included file, which shifted every subsequent line and so renamed the
# internal loop-lambda symbols that carry a line number (3 of 22548 differed over the
# compiler's own sources). This is the check that has to hold before the wrapper's flattening
# can be deleted, so it is asserted rather than left as a footnote.
total=$((total + 1))
( cd "$ROOT" && RUN "$BIN" -o "$WORK/flat_cli.o" src/driver/elisac.elisa >/dev/null 2>&1 )
( cd "$ROOT" && RUN bash scripts/elisac_stage1.sh -o "$WORK/flat_wrap.o" src/driver/elisac.elisa >/dev/null 2>&1 )
if [ -s "$WORK/flat_cli.o" ] && [ -s "$WORK/flat_wrap.o" ] && cmp -s "$WORK/flat_cli.o" "$WORK/flat_wrap.o"; then
    pass=$((pass + 1))
else
    echo "  FAIL flattening_agrees: driver-flattened and wrapper-flattened objects differ"
    echo "    $(wc -c < "$WORK/flat_cli.o" 2>/dev/null) vs $(wc -c < "$WORK/flat_wrap.o" 2>/dev/null) bytes; differing symbols: $(diff <(nm "$WORK/flat_wrap.o" 2>/dev/null | awk '{print $2,$3}' | sort) <(nm "$WORK/flat_cli.o" 2>/dev/null | awk '{print $2,$3}' | sort) | grep -c '^[<>]')"
fi

if [ "$pass" -ne "$total" ]; then
    echo "cli_includes_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
echo "cli_includes_smoke OK: $pass/$total (driver-side include expansion, no wrapper)"
