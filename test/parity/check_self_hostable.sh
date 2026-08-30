#!/usr/bin/env bash
# Early-warning check: does the stage1 frontend's OWN name resolver resolve its OWN
# source? Run this after adding/porting any semantic check, BEFORE the full parity
# suite, to catch "runtime-only helper" leaks locally instead of at the last step.
#
# Why this can differ from a green parse_report/breadth build: parse_report.elisa is
# built with the CURRENT (stage0, Go) ELISACORE_BIN, which does real compilation —
# it knows every runtime/stdlib symbol (elisacore_std) and links against the actual
# runtime, so a call to a runtime-only helper (e.g. `sview_dirname`, declared in
# elisacore_std/elisacore_runtime_strings.elisa) resolves fine. This script instead
# exercises the stage1 frontend's OWN self-hosted resolver (Semantic::unresolved_table
# in src/semantic/), which only knows names from a small hardcoded builtin whitelist
# (seed_builtins, src/semantic/symbols.elisa) plus whatever is declared inside
# src/lexer/*.elisa, src/parser/*.elisa, src/semantic/*.elisa (see FRONTEND_FILES
# below — deliberately NOT including elisacore_std). A check file that calls a
# runtime/stdlib-only helper without redeclaring it inside that glob passes
# parse_report + the breadth sweep but is invisible to this resolver, and used to
# only surface as "N unresolved" at the very end of resolve_smoke.sh's self-resolve
# gate. This script isolates and runs just that gate, fast, and NAMES the offending
# identifiers instead of just counting them.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"

source "$REPO_ROOT/test/parity/resolve_elisac.sh"

command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

FIX="$REPO_ROOT/test/parity/resolve_smoke.elisa"
[[ -f "$FIX" ]] || { echo "error: missing resolve smoke fixture: $FIX" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/driver.c" <<'EOF'
#include "resolve_smoke.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static uint8_t *slurp(const char *path, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = (uint8_t *)malloc((size_t)n + 1);
    if (!b) { fclose(f); return NULL; }
    if (fread(b, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(b); return NULL; }
    fclose(f); b[n] = 0; *out_len = (size_t)n; return b;
}

/* Whole-program self-resolve: concatenate every file argument into one combined
   buffer (mirroring resolve_smoke.sh's self-resolve gate) so a single combined
   symbol table sees every module + cross-file declaration, then resolve once.
   Prints "<total_unresolved>" on stdout, and (if any) the offending identifier
   names, one per line, on stderr — the actionable part a bare count can't give. */
int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s FILE...\n", argv[0]); return 2; }

    size_t cap = 1 << 20, len = 0;
    uint8_t *buf = (uint8_t *)malloc(cap);
    for (int i = 1; i < argc; i++) {
        size_t n = 0; uint8_t *s = slurp(argv[i], &n);
        if (!s) { fprintf(stderr, "read failed: %s\n", argv[i]); return 3; }
        while (len + n + 1 > cap) { cap <<= 1; buf = (uint8_t *)realloc(buf, cap); }
        for (size_t j = 0; j < n; j++) buf[len++] = s[j];
        buf[len++] = '\n';
        free(s);
    }

    uint64_t total = 0;
    resolve_smoke_export(buf, len, &total);

    if (total > 0) {
        size_t names_cap = 1 << 16;
        uint8_t *names = (uint8_t *)malloc(names_cap);
        uint64_t names_len = undef_names_probe_export(buf, len, names, names_cap);
        fwrite(names, 1, names_len, stderr);
        free(names);
    }

    free(buf);
    printf("%llu\n", (unsigned long long)total);
    return 0;
}
EOF

"$ELISACORE_BIN" -emit header -o "$WORK/resolve_smoke.h" "$FIX" >/dev/null
"$ELISACORE_BIN" -emit obj -permissive -O2 -o "$WORK/resolve_smoke.o" "$FIX" >/dev/null

link_flags=(-O2 -I "$WORK" "$WORK/driver.c" "$WORK/resolve_smoke.o" -o "$WORK/run")
[[ "$(uname -s)" == "Darwin" ]] && link_flags=(-Wl,-undefined,dynamic_lookup "${link_flags[@]}")
[[ "$(uname -s)" == "Linux" ]] && link_flags=(-no-pie "${link_flags[@]}")
clang "${link_flags[@]}"

FRONTEND_FILES=()
for f in "$REPO_ROOT"/src/lexer/*.elisa "$REPO_ROOT"/src/parser/*.elisa "$REPO_ROOT"/src/semantic/*.elisa; do
	[[ -f "$f" ]] && FRONTEND_FILES+=("$f")
done
if [[ ${#FRONTEND_FILES[@]} -eq 0 ]]; then
	echo "error: no frontend files found under src/{lexer,parser,semantic}" >&2
	exit 2
fi

names_out="$WORK/names.txt"
unresolved="$("$WORK/run" "${FRONTEND_FILES[@]}" 2>"$names_out")"

RESOLVE_SELF_MAX="${RESOLVE_SELF_MAX:-0}"
if [[ "$unresolved" -gt "$RESOLVE_SELF_MAX" ]]; then
	echo "check_self_hostable FAILED: $unresolved unresolved (> RESOLVE_SELF_MAX=$RESOLVE_SELF_MAX) across ${#FRONTEND_FILES[@]} frontend files" >&2
	echo "unresolved identifiers:" >&2
	sort -u "$names_out" >&2
	exit 1
fi

echo "check_self_hostable OK: $unresolved unresolved (<= RESOLVE_SELF_MAX=$RESOLVE_SELF_MAX) across ${#FRONTEND_FILES[@]} frontend files" >&2
