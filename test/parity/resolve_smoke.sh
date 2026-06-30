#!/usr/bin/env bash
# Name-resolution smoke for the stage1 resolver.
#
# Builds lex -> parse -> resolve end-to-end and asserts that a fixture with exactly
# one undefined value-position identifier reports exactly one unresolved reference
# (all params/locals/globals resolve). Exercises the typed expr/stmt stores via the
# expression-tree walk and confirms the resolver result survives the region-poly return.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

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

int main(int argc, char **argv) {
    /* With file args: resolve each file and print "<total_unresolved> <file_count>"
       (per-file counts to stderr) — the self-resolve diagnostic. */
    if (argc >= 2) {
        uint64_t total = 0; int files = 0;
        for (int i = 1; i < argc; i++) {
            size_t n = 0; uint8_t *s = slurp(argv[i], &n);
            if (!s) { fprintf(stderr, "read failed: %s\n", argv[i]); return 3; }
            uint64_t u = 0;
            resolve_smoke_export(s, n, &u);
            fprintf(stderr, "  %s: %llu unresolved\n", argv[i], (unsigned long long)u);
            total += u; files++;
            free(s);
        }
        printf("%llu %d\n", (unsigned long long)total, files);
        return 0;
    }
    /* helper (global), a (param), y (local) all resolve; undefined_thing does not.
       classify() exercises match-arm PATTERN bindings: `val` (a Variant field
       subpattern) and `other` (a bare binding) are used in their arm bodies, so they
       must resolve. Before the resolver gathered pattern bindings these counted as
       two spurious unresolved refs — keeping the total at 1 proves the fix.
       pairs_use() exercises a destructuring `for k, v in ...` loop: both loop
       variables are used in the body, so both must resolve (before all loop vars
       were recorded, `v` was a spurious unresolved ref).
       refine() exercises `is` refinement bindings (bare `m`, variant `Stmt.Return(rv,
       ln)`) and an `as` cast: the bound names are used in the bodies and must resolve,
       and the `is`/`as` right operands (a binding target and a type) must NOT be
       counted as value references.
       has_match() exercises a quantifier `any x in items where x == needle`: the
       bound `x` is used in the `where` clause and must resolve (before quantifiers
       were modeled, `any` parsed as a bare ident and `x` was unresolved).
       recover() exercises prefix-clause bindings: a `catch` success arm `slot:`
       binds the result and `error e:` binds the error; both are used in their arm
       bodies and must resolve (before, the prefix was skipped and the binding lost). */
    const char *src =
        "def helper(x: int) -> int:\n"
        "    return x\n"
        "\n"
        "def classify(node: int) -> int:\n"
        "    match node:\n"
        "        Stmt.VarDecl(name, ty, val, ln):\n"
        "            return helper(val)\n"
        "        other:\n"
        "            return helper(other)\n"
        "\n"
        "def pairs_use(pairs: int) -> int:\n"
        "    total: int = 0\n"
        "    for k, v in pairs:\n"
        "        total <- total + helper(k) + helper(v)\n"
        "    return total\n"
        "\n"
        "def has_match(items: int, needle: int) -> bool:\n"
        "    return any x in items where x == needle\n"
        "\n"
        "def recover(arg: int) -> int:\n"
        "    catch helper(arg):\n"
        "        slot:\n"
        "            return helper(slot)\n"
        "        error e:\n"
        "            return helper(e)\n"
        "    return arg\n"
        "\n"
        "def refine(node: int) -> int:\n"
        "    if helper(node) is m:\n"
        "        return helper(m)\n"
        "    if node is Stmt.Return(rv, ln):\n"
        "        return helper(rv)\n"
        "    return helper(node as int)\n"
        "\n"
        "def main(a: int) -> int:\n"
        "    y: int = helper(a)\n"
        "    return y + undefined_thing\n";
    size_t n = 0; while (src[n]) n++;
    uint64_t unresolved = 0;
    resolve_smoke_export((uint8_t *)src, n, &unresolved);
    printf("%llu\n", (unsigned long long)unresolved);
    return 0;
}
EOF

"$ELISACORE_BIN" -emit header -o "$WORK/resolve_smoke.h" "$FIX" >/dev/null
"$ELISACORE_BIN" -emit obj -permissive -O2 -o "$WORK/resolve_smoke.o" "$FIX" >/dev/null

link_flags=(-O2 -I "$WORK" "$WORK/driver.c" "$WORK/resolve_smoke.o" -o "$WORK/run")
[[ "$(uname -s)" == "Darwin" ]] && link_flags=(-Wl,-undefined,dynamic_lookup "${link_flags[@]}")
[[ "$(uname -s)" == "Linux" ]] && link_flags=(-no-pie "${link_flags[@]}")
clang "${link_flags[@]}"

got="$("$WORK/run")"
if [[ "$got" != "1" ]]; then
	echo "resolve smoke FAILED: unresolved=$got (want 1)" >&2
	exit 1
fi
echo "resolve smoke OK: unresolved=1" >&2

# Self-resolve diagnostic: run the resolver over the frontend's OWN source and
# report per-file unresolved counts. This is the dogfooding measurement that drives
# the remaining resolver work to zero. It is GATING only on a budget ceiling (set
# RESOLVE_SELF_MAX, default unlimited) so it surfaces regressions without blocking
# while unmodeled binders (comprehensions/quantifiers, prefix-clause `catch e`)
# still produce known false-positives.
FRONTEND_FILES=()
for f in "$REPO_ROOT"/src/lexer/*.elisa "$REPO_ROOT"/src/parser/*.elisa "$REPO_ROOT"/src/sema/*.elisa; do
	[[ -f "$f" ]] && FRONTEND_FILES+=("$f")
done
if [[ ${#FRONTEND_FILES[@]} -gt 0 ]]; then
	read -r self_unresolved self_files < <("$WORK/run" "${FRONTEND_FILES[@]}")
	echo "resolve self-resolve: $self_unresolved unresolved across $self_files frontend files" >&2
	if [[ -n "${RESOLVE_SELF_MAX:-}" && "$self_unresolved" -gt "$RESOLVE_SELF_MAX" ]]; then
		echo "resolve self-resolve FAILED: $self_unresolved > RESOLVE_SELF_MAX=$RESOLVE_SELF_MAX" >&2
		exit 1
	fi
fi
