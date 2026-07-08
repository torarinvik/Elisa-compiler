#!/usr/bin/env bash
# tools/new_diagnostic.sh — scaffold a new stage1 semantic DiagnosticKind.
#
# Adding a new semantic diagnostic to the stage1 self-hosted compiler requires six
# coordinated edits (see docs / MEMORY for the "six wiring points"):
#   1. A variant in `DiagnosticKind` (src/semantic/semantic_types.elisa)
#   2. A render case in `diagnostic_message` (src/semantic/semantic_api.elisa)
#   3. A severity case in `diagnostic_severity` (src/semantic/semantic_api.elisa)
#   4. An `include "./check_<name>.elisa"` line (src/semantic/semantic.elisa)
#   5. A `table <- check_<name>(...)` call in `def check` (src/semantic/semantic_api.elisa)
#   6. A code mapping in `code_of_diag_kind` (test/parity/resolve_smoke.elisa)
#
# This script performs all six, idempotently, plus stamps out a compiling skeleton
# `src/semantic/check_<name>.elisa` that fires nothing until you fill in the logic.
#
# Usage:
#   tools/new_diagnostic.sh <snake_case_name> [--severity error|warning] [--message "..."]
#
# The FILE name and the public entry point are both derived from <snake_case_name>
# (check_<name>.elisa / check_<name>(...)) so they can never drift apart — the
# real bug this script exists to prevent was an entry point named after the enum
# variant instead of after the file.

set -euo pipefail

usage() {
    echo "usage: $0 <snake_case_name> [--severity error|warning] [--message \"...\"]" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

NAME=""
SEVERITY="error"
MESSAGE=""

if [ "$#" -lt 1 ]; then
    usage
fi

NAME="$1"
shift

while [ "$#" -gt 0 ]; do
    case "$1" in
        --severity)
            [ "$#" -ge 2 ] || usage
            SEVERITY="$2"
            shift 2
            ;;
        --message)
            [ "$#" -ge 2 ] || usage
            MESSAGE="$2"
            shift 2
            ;;
        *)
            echo "error: unknown argument '$1'" >&2
            usage
            ;;
    esac
done

if ! [[ "$NAME" =~ ^[a-z][a-z0-9_]*$ ]]; then
    echo "error: name must be snake_case, matching ^[a-z][a-z0-9_]*\$ (got '$NAME')" >&2
    exit 1
fi

case "$SEVERITY" in
    error)   SEVERITY_NUM=1 ;;
    warning) SEVERITY_NUM=2 ;;
    *)
        echo "error: --severity must be 'error' or 'warning' (got '$SEVERITY')" >&2
        exit 1
        ;;
esac

if [ -z "$MESSAGE" ]; then
    MESSAGE="TODO: describe when this fires"
fi
if [[ "$MESSAGE" == *'"'* ]]; then
    echo "error: --message may not contain a double-quote character" >&2
    exit 1
fi

# snake_case -> PascalCase, e.g. sample_scaffold_probe -> SampleScaffoldProbe
PASCAL=""
IFS='_' read -r -a NAME_PARTS <<< "$NAME"
for part in "${NAME_PARTS[@]}"; do
    PASCAL+="$(tr '[:lower:]' '[:upper:]' <<< "${part:0:1}")${part:1}"
done

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TYPES_FILE="$REPO_ROOT/src/semantic/semantic_types.elisa"
API_FILE="$REPO_ROOT/src/semantic/semantic_api.elisa"
FACADE_FILE="$REPO_ROOT/src/semantic/semantic.elisa"
SMOKE_FILE="$REPO_ROOT/test/parity/resolve_smoke.elisa"
CHECK_FILE="$REPO_ROOT/src/semantic/check_${NAME}.elisa"

for f in "$TYPES_FILE" "$API_FILE" "$FACADE_FILE" "$SMOKE_FILE"; do
    if [ ! -f "$f" ]; then
        echo "error: expected file not found: $f" >&2
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Duplicate guard — check ALL six sites (plus the skeleton file) before touching
# anything, so a failed run never leaves a partially-wired diagnostic.
# ---------------------------------------------------------------------------

dup_found=0

if grep -qE "^            ${PASCAL}\$" "$TYPES_FILE"; then
    echo "error: DiagnosticKind.${PASCAL} already declared in $TYPES_FILE" >&2
    dup_found=1
fi
if grep -qF "DiagnosticKind.${PASCAL}:" "$API_FILE"; then
    echo "error: DiagnosticKind.${PASCAL} already handled in $API_FILE" >&2
    dup_found=1
fi
if [ -f "$CHECK_FILE" ]; then
    echo "error: $CHECK_FILE already exists" >&2
    dup_found=1
fi
if grep -qF "check_${NAME}.elisa" "$FACADE_FILE"; then
    echo "error: check_${NAME}.elisa already included in $FACADE_FILE" >&2
    dup_found=1
fi
if grep -qF "check_${NAME}(file.top_decls, table)" "$API_FILE"; then
    echo "error: check_${NAME} already called in $API_FILE" >&2
    dup_found=1
fi
if grep -qF "DiagnosticKind.${PASCAL}:" "$SMOKE_FILE"; then
    echo "error: DiagnosticKind.${PASCAL} already mapped in $SMOKE_FILE" >&2
    dup_found=1
fi

if [ "$dup_found" -ne 0 ]; then
    echo "aborting — no files touched." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Small awk-based line-splice helpers. Both take a 1-based line number and a
# (possibly multi-line) content string, and rewrite the file in place.
# ---------------------------------------------------------------------------

# NOTE: content is passed through the environment (not -v) because this
# platform's awk (BWK/one-true-awk) rejects raw embedded newlines in a -v
# assignment ("newline in string ... at source line 1").
insert_after_line() {
    local file="$1" line_no="$2" content="$3"
    NEW_DIAG_INS="$content" awk -v n="$line_no" '
        { print }
        NR==n { print ENVIRON["NEW_DIAG_INS"] }
    ' "$file" > "${file}.new_diag.tmp" && mv "${file}.new_diag.tmp" "$file"
}

insert_before_line() {
    local file="$1" line_no="$2" content="$3"
    NEW_DIAG_INS="$content" awk -v n="$line_no" '
        NR==n { print ENVIRON["NEW_DIAG_INS"] }
        { print }
    ' "$file" > "${file}.new_diag.tmp" && mv "${file}.new_diag.tmp" "$file"
}

# ---------------------------------------------------------------------------
# Site 1 — enum variant in semantic_types.elisa
#
# Anchor: `const enum DiagnosticKind of u8:` ends right before `struct Diagnostic:`.
# We locate `struct Diagnostic:` and scan backward for the LAST bare-identifier
# variant line (12-space indent, no trailing punctuation/comment) — that is the
# current last variant, regardless of which one it is.
# ---------------------------------------------------------------------------

struct_line=$(grep -n '^        struct Diagnostic:$' "$TYPES_FILE" | head -1 | cut -d: -f1)
if [ -z "$struct_line" ]; then
    echo "error: could not find 'struct Diagnostic:' anchor in $TYPES_FILE" >&2
    exit 1
fi
last_variant_line=$(awk -v end="$struct_line" '
    NR<end && /^            [A-Za-z_][A-Za-z0-9_]*$/ { last=NR }
    END { print last+0 }
' "$TYPES_FILE")
if [ "$last_variant_line" -eq 0 ]; then
    echo "error: could not find the last DiagnosticKind variant in $TYPES_FILE" >&2
    exit 1
fi

variant_block=$(printf '            # %s.\n            %s' "$MESSAGE" "$PASCAL")
insert_after_line "$TYPES_FILE" "$last_variant_line" "$variant_block"

# ---------------------------------------------------------------------------
# Site 2 — render case in diagnostic_message (semantic_api.elisa)
#
# Anchor: the (unique) "                return buffer" that closes the match —
# insert the new case immediately above it.
# ---------------------------------------------------------------------------

return_buffer_line=$(grep -n '^                return buffer$' "$API_FILE" | head -1 | cut -d: -f1)
if [ -z "$return_buffer_line" ]; then
    echo "error: could not find 'return buffer' anchor in $API_FILE" >&2
    exit 1
fi
message_case=$(printf '                    DiagnosticKind.%s:\n                        push_str(buffer, "%s")' "$PASCAL" "$MESSAGE")
insert_before_line "$API_FILE" "$return_buffer_line" "$message_case"

# Recompute line numbers below — the file just grew by 2 lines above this point,
# so anything located below return_buffer_line has shifted by +2.

# ---------------------------------------------------------------------------
# Site 3 — severity case in diagnostic_severity (semantic_api.elisa)
#
# Anchor: the last non-blank line before the NEXT "extend Semantic:" that
# follows `def diagnostic_severity` — i.e. the current last severity case.
# ---------------------------------------------------------------------------

sev_def_line=$(grep -n '^        def diagnostic_severity' "$API_FILE" | head -1 | cut -d: -f1)
if [ -z "$sev_def_line" ]; then
    echo "error: could not find 'def diagnostic_severity' anchor in $API_FILE" >&2
    exit 1
fi
next_extend_line=$(awk -v start="$sev_def_line" 'NR>start && /^extend Semantic:$/ { print NR; exit }' "$API_FILE")
if [ -z "$next_extend_line" ]; then
    echo "error: could not find the 'extend Semantic:' block following diagnostic_severity in $API_FILE" >&2
    exit 1
fi
last_sev_case_line=$(awk -v end="$next_extend_line" 'NR<end && /^                    DiagnosticKind\.[A-Za-z0-9_]+:/ { last=NR } END { print last+0 }' "$API_FILE")
if [ "$last_sev_case_line" -eq 0 ]; then
    echo "error: could not find the last diagnostic_severity case in $API_FILE" >&2
    exit 1
fi
severity_case=$(printf '                    DiagnosticKind.%s:            %s' "$PASCAL" "$SEVERITY_NUM")
insert_after_line "$API_FILE" "$last_sev_case_line" "$severity_case"

# ---------------------------------------------------------------------------
# Site 5 — check-call in `def check` (semantic_api.elisa)
#
# Anchor: the first "                return table" after `def check(file: ...)`
# — i.e. the end of the check-call chain in that specific function (there are
# several unrelated `return table`s elsewhere in the file).
# ---------------------------------------------------------------------------

check_def_line=$(grep -n '^        def check(file: Ast::File&)' "$API_FILE" | head -1 | cut -d: -f1)
if [ -z "$check_def_line" ]; then
    echo "error: could not find 'def check(file: Ast::File&)' anchor in $API_FILE" >&2
    exit 1
fi
check_return_line=$(awk -v start="$check_def_line" 'NR>start && /^                return table$/ { print NR; exit }' "$API_FILE")
if [ -z "$check_return_line" ]; then
    echo "error: could not find the closing 'return table' of def check in $API_FILE" >&2
    exit 1
fi
check_call=$(printf '                    table <- check_%s(file.top_decls, table)' "$NAME")
insert_before_line "$API_FILE" "$check_return_line" "$check_call"

# ---------------------------------------------------------------------------
# Site 4 — include line in semantic.elisa
#
# Anchor: the (unique) include of semantic_api.elisa itself — the new include
# must land immediately before it (semantic_api.elisa references every check_*
# entry point, so it must be included last).
# ---------------------------------------------------------------------------

api_include_line=$(grep -n '^include "\./semantic_api\.elisa"$' "$FACADE_FILE" | head -1 | cut -d: -f1)
if [ -z "$api_include_line" ]; then
    echo "error: could not find the semantic_api.elisa include anchor in $FACADE_FILE" >&2
    exit 1
fi
include_line="include \"./check_${NAME}.elisa\""
insert_before_line "$FACADE_FILE" "$api_include_line" "$include_line"

# ---------------------------------------------------------------------------
# Site 6 — code mapping in code_of_diag_kind (test/parity/resolve_smoke.elisa)
#
# Anchor: the last non-blank line before the NEXT top-level `def ` that follows
# `def code_of_diag_kind` — i.e. the current last mapping. The new numeric code
# is one past the highest code already assigned anywhere in that block.
# ---------------------------------------------------------------------------

cod_def_line=$(grep -n '^def code_of_diag_kind' "$SMOKE_FILE" | head -1 | cut -d: -f1)
if [ -z "$cod_def_line" ]; then
    echo "error: could not find 'def code_of_diag_kind' anchor in $SMOKE_FILE" >&2
    exit 1
fi
next_def_line=$(awk -v start="$cod_def_line" 'NR>start && /^def / { print NR; exit }' "$SMOKE_FILE")
if [ -z "$next_def_line" ]; then
    echo "error: could not find the end of code_of_diag_kind in $SMOKE_FILE" >&2
    exit 1
fi
last_map_line=$(awk -v end="$next_def_line" 'NR<end && /^            Semantic::DiagnosticKind\.[A-Za-z0-9_]+:/ { last=NR } END { print last+0 }' "$SMOKE_FILE")
if [ "$last_map_line" -eq 0 ]; then
    echo "error: could not find the last code_of_diag_kind mapping in $SMOKE_FILE" >&2
    exit 1
fi
max_code=$(sed -n "$((cod_def_line + 1)),$((next_def_line - 1))p" "$SMOKE_FILE" \
    | grep -oE 'Semantic::DiagnosticKind\.[A-Za-z0-9_]+: *[0-9]+$' \
    | grep -oE '[0-9]+$' \
    | sort -n | tail -1)
max_code=${max_code:-0}
new_code=$((max_code + 1))
map_line=$(printf '            Semantic::DiagnosticKind.%s:      %s' "$PASCAL" "$new_code")
insert_after_line "$SMOKE_FILE" "$last_map_line" "$map_line"

# ---------------------------------------------------------------------------
# Stamp the starter check_<name>.elisa skeleton — a compiling, no-op pass
# modeled on check_self_assignment.elisa (the simplest existing check). It
# walks every declaration/statement but pushes no diagnostic; fill in the
# firing logic where marked TODO.
# ---------------------------------------------------------------------------

cat > "$CHECK_FILE" <<ELISA
# ${PASCAL} check — ${MESSAGE}.
#
# Scaffolded by tools/new_diagnostic.sh. This skeleton compiles and is wired
# into all six diagnostic sites, but fires NOTHING yet — it walks every
# declaration and statement and returns \`table\` unchanged. Replace the no-op
# arms below with real detection, pushing a diagnostic via:
#
#   table.diagnostics <- table.diagnostics.push(Diagnostic{
#       kind: DiagnosticKind.${PASCAL}, name: <sview>, line: <u32>,
#       expected: "", actual: "",
#   })
#
# See check_self_assignment.elisa / check_literal_comparison_impossible.elisa
# for worked examples of this shape.

extend Semantic:
    private:
        # Walk statements looking for the pattern this check should flag.
        # TODO: recognize the offending shape and push a Diagnostic above.
        def check_${NAME}_statements(statements: darray[Ast::Stmt], table: lmut SymbolTable) -> void:
            can Memory.Allocate, Abort.Panic:
                for statement in statements |table| -> table:
                    match statement:
                        Stmt.Expr(expression, line):
                            table
                        Stmt.VarDecl(name, type_expression, value, line):
                            table
                        Stmt.Assign(target, operator, value, line):
                            table
                        Stmt.If(condition, then_body, else_body, line):
                            table <- check_${NAME}_statements(then_body, table)
                            table <- check_${NAME}_statements(else_body, table)
                        Stmt.While(condition, body, line):
                            table <- check_${NAME}_statements(body, table)
                        Stmt.For(bind, variables, iterable, body, line):
                            table <- check_${NAME}_statements(body, table)
                        Stmt.Block(kind, clause, binding, body, line):
                            table <- check_${NAME}_statements(body, table)
                        Stmt.Match(scrutinee, arms, line):
                            for arm in arms |table| -> table:
                                table <- check_${NAME}_statements(arm.body, table)
                        Stmt.Return(value, line):
                            table
                        Stmt.Contract(kind, expression, line):
                            table
                        Stmt.Invalid:
                            table
                        Stmt.Break(label, line):
                            table
                        Stmt.Continue(label, line):
                            table

    public:
        # Public entry point — name MUST agree with this file's name
        # (check_${NAME}.elisa / check_${NAME}) so the central call site
        # in semantic_api.elisa's \`def check\` always resolves.
        def check_${NAME}(declarations: darray[Ast::Decl], table: lmut SymbolTable) -> void:
            can Memory.Allocate, Abort.Panic:
                for declaration in declarations |table| -> table:
                    match declaration:
                        Decl.Func(name, parameters, return_type, body, effects, decorators, line):
                            table <- check_${NAME}_statements(body, table)
                        Decl.Module(name, body, line):
                            table <- check_${NAME}(body, table)
                        Decl.Scoped(body, line):
                            table <- check_${NAME}(body, table)
                        _:
                            table
ELISA

echo "wired DiagnosticKind.${PASCAL} (check_${NAME}) into all 6 sites:"
echo "  1. $TYPES_FILE"
echo "  2/3. $API_FILE"
echo "  4/5. $FACADE_FILE / $API_FILE"
echo "  6. $SMOKE_FILE (code ${new_code})"
echo "  skeleton: $CHECK_FILE"
