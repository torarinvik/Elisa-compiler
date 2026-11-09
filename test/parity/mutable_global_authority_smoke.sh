#!/usr/bin/env bash
# Default mutable-global authority: direct operations and transitive callers must
# reject without a local member grant. No #globals/-Wglobals opt-in is used.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
if [ "${ELISA_GLOBAL_AUTHORITY_REPORTER_PREBUILT:-0}" != 1 ]; then
    source "$REPO_ROOT/test/parity/build_parse_report.sh"
fi
RPT="${ELISA_PARSE_REPORT:-$REPO_ROOT/build/parse_report}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
cases=0
run_case() {
    local name="$1" expected="$2" output
    cases=$((cases+1))
    cat > "$WORK/$name.elisa"
    output="$("$RPT" < "$WORK/$name.elisa")"
    if ! printf '%s\n' "$output" | grep -q '^P 0$'; then
        printf 'FAIL %s: source did not parse\n%s\n' "$name" "$output" >&2
        failed=$((failed+1))
        return
    fi
    if [ "$expected" = clean ]; then
        if ! printf '%s\n' "$output" | grep -q '^D 0$'; then
            printf 'FAIL %s: expected no diagnostics\n%s\n' "$name" "$output" >&2
            failed=$((failed+1))
        fi
    elif ! printf '%s\n' "$output" | grep -Fq "$expected"; then
        printf 'FAIL %s: missing %s\n%s\n' "$name" "$expected" "$output" >&2
        failed=$((failed+1))
    fi
    if printf '%s\n' "$output" | grep -q '^S '; then
        if ! printf '%s\n' "$output" | awk -v expected="$expected" -v name="$name" '/^S /{severity=$2} /requires can\[Global\]|accesses a global mutable binding without Global\./{if(severity==1)global_error=1} /requires can\[Unsafe\]/{if(severity==1)unsafe_error=1} END{if((expected ~ /requires can\[Global\]/ || expected ~ /accesses a global mutable binding without Global\./) && name!="immutable_call_legacy_opt_in" && !global_error)exit 1; if(expected ~ /requires can\[Unsafe\]/ && !unsafe_error)exit 1}'; then
            printf 'FAIL %s: mandatory effect diagnostic is not severity 1\n%s\n' "$name" "$output" >&2
            failed=$((failed+1))
        fi
    fi
}
source "$REPO_ROOT/test/parity/mutable_global_inline_and_field_cases.sh"
source "$REPO_ROOT/test/parity/mutable_global_reference_and_module_cases.sh"
source "$REPO_ROOT/test/parity/mutable_global_call_and_effect_cases.sh"
if ! ELISA_PARSE_REPORT="$RPT" python3 "$REPO_ROOT/test/proofs/check_global_authority_field_chain.py"; then
    failed=$((failed+1))
fi
cases=$((cases+1))
[ "$failed" -eq 0 ] || exit 1
echo "mutable global authority smoke OK: $cases cases" >&2
