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
#include <string.h>

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
        /* Whole-program resolution: concatenate all files into one buffer so a single
           combined symbol table sees every module + cross-file declaration, then
           resolve once. This is the cross-file self-resolve measurement. */
        size_t cap = 1 << 20, len = 0; int files = 0;
        uint8_t *buf = (uint8_t *)malloc(cap);
        for (int i = 1; i < argc; i++) {
            size_t n = 0; uint8_t *s = slurp(argv[i], &n);
            if (!s) { fprintf(stderr, "read failed: %s\n", argv[i]); return 3; }
            while (len + n + 1 > cap) { cap <<= 1; buf = (uint8_t *)realloc(buf, cap); }
            for (size_t j = 0; j < n; j++) buf[len++] = s[j];
            buf[len++] = '\n';
            files++;
            free(s);
        }
        uint64_t total = 0;
        resolve_smoke_export(buf, len, &total);
        free(buf);
        printf("%llu %d\n", (unsigned long long)total, files);
        return 0;
    }
    /* helper (global), a (param), y (local) all resolve; undefined_thing does not.
       classify() exercises match-arm PATTERN bindings: `val` (a Variant field
       subpattern) and `other` (a bare binding) are used in their arm bodies, so they
       must resolve. Before the resolver gathered pattern bindings these counted as
       two spurious unresolved refs — keeping the total at 2 proves the fix.
       nested_mod exercises Decl.Module recursion: inside() calls the file-global
       helper (must resolve across the module boundary) and references
       undefined_in_module (must be caught — if resolve_decls treated Decl.Module as
       a no-op, this reference would never be walked at all, silently DECREASING the
       total instead of correctly adding to it).
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
        /* Pattern forms the frontend doesn't use itself (so unexercised by self-parse) —
           covered here by crafted arms. Each binds names that are USED in the arm body, so
           if the pattern fell back to `Other` (no bindings gathered) the uses would become
           unresolved and the total would exceed 1. Keeping the total at 1 proves the
           struct/tuple/or/type-binder patterns are structurally decomposed.
           struct_pat: `Foo{a, b: c}` binds `a` (shorthand) and `c` (labeled subpattern).
           tuple_pat: `x, y` binds both tuple elements.
           binder_pat: `Statement s` (category arm) binds `s`.
           or_pat: `A(p) | B(p)` binds `p` in each alternative; used in the body. */
        "def struct_pat(node: int) -> int:\n"
        "    match node:\n"
        "        Shape{a, b: c}:\n"
        "            return helper(a) + helper(c)\n"
        "        _:\n"
        "            return 0\n"
        "\n"
        "def tuple_pat(node: int) -> int:\n"
        "    match node:\n"
        "        x, y:\n"
        "            return helper(x) + helper(y)\n"
        "\n"
        "def binder_pat(node: int) -> int:\n"
        "    match node:\n"
        "        Statement s:\n"
        "            return helper(s)\n"
        "        _:\n"
        "            return 0\n"
        "\n"
        "def or_pat(node: int) -> int:\n"
        "    match node:\n"
        "        Stmt.A(p) | Stmt.B(p):\n"
        "            return helper(p)\n"
        "        _:\n"
        "            return 0\n"
        "\n"
        /* extern declarations register the external name as a symbol. `ext_fn` is called
           below; if the extern decl were dropped (the old placeholder behavior) the call
           would be unresolved and the total would exceed 1. */
        "extern ext_fn(x: int) -> int\n"
        "\n"
        "def use_extern(a: int) -> int:\n"
        "    return ext_fn(a)\n"
        "\n"
        /* nested_mod exercises Decl.Module recursion in resolve_decls: a function body
           INSIDE a module must still be walked. `helper` is a file-global, so calling
           it here proves cross-module resolution works; `undefined_in_module` is
           deliberately undefined and must be caught ONLY if the module's body is
           actually recursed into (if Decl.Module were a no-op, this reference would
           never be walked and would silently vanish from the count instead of adding
           1 to it). */
        "module nested_mod:\n"
        "    def inside(a: int) -> int:\n"
        "        return helper(a) + undefined_in_module\n"
        "\n"
        "def main(a: int) -> int:\n"
        "    y: int = helper(a)\n"
        "    return y + undefined_thing\n";
    size_t n = 0; while (src[n]) n++;
    uint64_t unresolved = 0;
    resolve_smoke_export((uint8_t *)src, n, &unresolved);

    /* Diagnostics-layer position check: the checker must report the UndefinedName
       diagnostic at the right source line. `missing` is undefined on line 2. */
    const char *dsrc = "def f(a: int) -> int:\n    return missing\n";
    size_t dn = 0; while (dsrc[dn]) dn++;
    uint64_t dcount = 0; uint32_t dline = 0;
    diag_probe_export((uint8_t *)dsrc, dn, &dcount, &dline);
    if (dcount != 1 || dline != 2) {
        fprintf(stderr, "diag probe FAILED: count=%llu line=%u (want count=1 line=2)\n",
                (unsigned long long)dcount, dline);
        return 4;
    }

    /* Duplicate-declaration check: the checker must report a DuplicateDecl at the
       redefinition's line. `dup` is defined twice; the second def is on line 4, and
       exactly one duplicate must be reported (guards add_symbol's duplicate path). */
    const char *usrc =
        "def dup(a: int) -> int:\n"
        "    return a\n"
        "\n"
        "def dup(b: int) -> int:\n"
        "    return b\n";
    size_t un = 0; while (usrc[un]) un++;
    uint64_t ucount = 0; uint32_t uline = 0;
    dup_probe_export((uint8_t *)usrc, un, &ucount, &uline);
    if (ucount != 1 || uline != 4) {
        fprintf(stderr, "dup probe FAILED: count=%llu line=%u (want count=1 line=4)\n",
                (unsigned long long)ucount, uline);
        return 6;
    }

    /* Diagnostic wording/severity source-of-truth (diagnostic_message /
       diagnostic_severity). No end-to-end probe reads these, so guard them here:
       every kind's message must be non-empty, the two semantic kinds must be
       worded distinctly with the expected prefix (catches an arm swap), and all
       kinds are severity 1 (Error). */
    {
        char msg[6][128];
        size_t mlen[6];
        for (uint32_t k = 0; k < 6; k++) {
            mlen[k] = (size_t)diag_message_probe_export(k, (uint8_t *)msg[k], sizeof(msg[k]) - 1);
            msg[k][mlen[k]] = 0;
            if (mlen[k] == 0) {
                fprintf(stderr, "diag message probe FAILED: kind %u empty\n", k);
                return 7;
            }
            if (diag_severity_probe_export(k) != 1) {
                fprintf(stderr, "diag severity probe FAILED: kind %u not Error\n", k);
                return 7;
            }
        }
        if (strncmp(msg[0], "undefined name", 14) != 0) {
            fprintf(stderr, "diag message probe FAILED: UndefinedName wording=%s\n", msg[0]);
            return 7;
        }
        if (strncmp(msg[1], "duplicate declaration", 21) != 0) {
            fprintf(stderr, "diag message probe FAILED: DuplicateDecl wording=%s\n", msg[1]);
            return 7;
        }
    }

    /* Syntax-error folding: a malformed source must surface syntax diagnostics
       through check() (append_parse_errors folds them in; parse_error_kind maps
       ParseErrorKind -> DiagnosticKind). A function header missing its `:`
       yields (first) a SyntaxExpectedDeclaration finding (code 4). Asserting the
       code guards the mapping; asserting count>=1 guards the folding. */
    {
        const char *ssrc = "def f(a: int) -> int\n    return a\n";
        size_t sn = 0; while (ssrc[sn]) sn++;
        uint64_t scount = 0; uint32_t skind = 0;
        syntax_probe_export((uint8_t *)ssrc, sn, &scount, &skind);
        if (scount < 1 || skind != 4) {
            fprintf(stderr, "syntax probe FAILED: count=%llu first_kind=%u (want count>=1 first_kind=4)\n",
                    (unsigned long long)scount, skind);
            return 8;
        }
    }

    /* Hash-index collision path: a manually-seeded name_primary slot must read back
       as occupied, and an untouched hash must not. Guards against `hash_occupied`
       regressing to always-false, which would silently overwrite name_primary on a
       real hash collision instead of routing to name_overflow (see symbols.elisa). */
    if (hash_occupied_probe_export(0x1234) != 1 || hash_occupied_probe_empty_export(0x1234) != 0) {
        fprintf(stderr, "hash_occupied probe FAILED\n");
        return 5;
    }

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
if [[ "$got" != "2" ]]; then
	echo "resolve smoke FAILED: unresolved=$got (want 2)" >&2
	exit 1
fi
echo "resolve smoke OK: unresolved=2" >&2

# Self-resolve diagnostic: run the resolver over the frontend's OWN source —
# WHOLE-PROGRAM (all files concatenated into one combined symbol table), so
# cross-file and module-qualified references (`Lexer::foo`, `Ast::Node`) resolve.
# This dogfooding measurement drove the resolver to ~zero (788 per-file -> 5):
# modeling cross-file modules, struct-literal field labels (labels are selectors,
# not references), and seeding language builtins. The residual 5 are degenerate
# zero-ish identifier leaves produced at flat-concatenation file boundaries (not
# real references; they do not occur under the real include structure).
# GATING on a budget ceiling (RESOLVE_SELF_MAX, default 5) to lock in the result.
FRONTEND_FILES=()
for f in "$REPO_ROOT"/src/bytes.elisa "$REPO_ROOT"/src/lexer/*.elisa "$REPO_ROOT"/src/parser/*.elisa "$REPO_ROOT"/src/semantic/*.elisa; do
	[[ -f "$f" ]] && FRONTEND_FILES+=("$f")
done
if [[ ${#FRONTEND_FILES[@]} -gt 0 ]]; then
	read -r self_unresolved self_files < <("$WORK/run" "${FRONTEND_FILES[@]}")
	echo "resolve self-resolve: $self_unresolved unresolved across $self_files frontend files (whole-program)" >&2
	if [[ "$self_unresolved" -gt "${RESOLVE_SELF_MAX:-5}" ]]; then
		echo "resolve self-resolve FAILED: $self_unresolved > RESOLVE_SELF_MAX=${RESOLVE_SELF_MAX:-5}" >&2
		exit 1
	fi
fi
