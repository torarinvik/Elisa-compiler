#!/usr/bin/env bash
# Replay stage0's FULL internal semantic test suite (src/semantic, ~2.4k tests)
# through stage1 and require accept/reject agreement, with a ratcheting baseline.
#
# The oracle snapshot is committed at test/fixtures/semantic_internal_oracle.tsv.gz.
# Regenerate it (stage0 checkout required, ~8 min) with:
#   cd "$ELISA_CORE/compiler" && \
#     ELISA_SEMANTIC_INTERNAL_PARITY_OUT=/tmp/internal_oracle.tsv go test ./src/semantic -count=1 && \
#     gzip -c /tmp/internal_oracle.tsv > <repo>/test/fixtures/semantic_internal_oracle.tsv.gz
#
# Row format (b64 = base64):
#   b64(filename) \t errors \t warnings \t b64(options-fingerprint) \t b64(source) \t b64(messages)
#
# Tier 1 (gated): clean-vs-diagnostic class must agree, EXCEPT rows whose options
# fingerprint enables stage0-only channels stage1 does not model yet (SMT, perf
# lints, overlay layouts, ...): those are counted separately and ratcheted, not
# required. The baseline file holds the allowed mismatch count; going ABOVE it
# fails, going below prints the new number to commit.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SNAPSHOT="$REPO_ROOT/test/fixtures/semantic_internal_oracle.tsv.gz"
BASELINE_FILE="$REPO_ROOT/test/fixtures/semantic_internal.baseline"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -f "$SNAPSHOT" ]] || { echo "semantic internal diff FAILED: missing $SNAPSHOT" >&2; exit 1; }
[[ -f "$BASELINE_FILE" ]] || { echo "semantic internal diff FAILED: missing $BASELINE_FILE" >&2; exit 1; }
baseline="$(tr -d '[:space:]' < "$BASELINE_FILE")"

ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

ORACLE="$WORK/oracle.tsv"
gunzip -c "$SNAPSHOT" > "$ORACLE"

# Dedupe by (fingerprint, source); keep the MAX diagnostic count per key. stage0
# analyzes some sources twice under one options struct (a speculative pre-pass
# records an empty result before the real pass appends diagnostics), so a plain
# `sort -u` keeps an arbitrary row and can crown the empty pre-pass — making a
# correctly-diagnosing stage1 look like a false positive.
sort -t$'\t' -k4,4 -k5,5 "$ORACLE" | awk -F'\t' '
    function flush() { if (key != "") print best }
    {
        k = $4 "\t" $5
        if (k != key) { flush(); key = k; best = $0; bestn = $2 + $3; next }
        if ($2 + $3 > bestn) { best = $0; bestn = $2 + $3 }
    }
    END { flush() }
' > "$WORK/deduped.tsv"

total=0
mismatches=0
: > "$WORK/mismatches.tsv"

# Trusted-stdlib basenames (mirrors semantic/permissions_validation.go's runtimeStdBaseNames):
# a source with one of these names, or under an elisacore_std/ directory, is exempt from
# user-only passes (raw-atomic-surface removal). Replayed via a `# std` header.
is_runtime_std() {
    local path="$1"
    case "$(dirname -- "$path")" in
        */elisacore_std|elisacore_std) return 0 ;;
    esac
    case "$(basename -- "$path")" in
        allocator.elisa|arena.elisa|collections.elisa|debug_referee.elisa|deque.elisa|\
        elisacore_runtime.elisa|elisacore_runtime_concurrency.elisa|elisacore_runtime_prelude.elisa|\
        elisacore_runtime_strings.elisa|elisacore_runtime_system_bridge.elisa|heap.elisa|names.elisa|\
        native_runtime_support.elisa|runtime.elisa|stores.elisa|stores_core.elisa|\
        stores_packed_dense.elisa|stores_packed_encoding.elisa|stores_packed_sparse.elisa|\
        stores_rows.elisa|stores_types.elisa|test.elisa) return 0 ;;
    esac
    return 1
}
while IFS=$'\t' read -r fname_b64 errors warnings opts_b64 src_b64 msgs_b64 overlay_b64; do
    total=$((total + 1))
    opts="$(printf '%s' "$opts_b64" | openssl base64 -d -A)"
    hdr=""
    case "$opts" in
        *FlowLintMode:2*) hdr+=$'# flow-strict\n' ;;
        *FlowLintMode:1*) hdr+=$'# flow\n' ;;
    esac
    case "$opts" in
        *EnforceUnsafePermissions:true*|*EnforceStrictProofs:true*) hdr+=$'# strict\n' ;;
    esac
    # Pure EnforceUnsafePermissions is a NARROWER axis than the `# strict` union above:
    # stage0 gates the raw-extern-call obligation on it ALONE, so a proof-only case must
    # not inherit that obligation. Emitted as an extra header.
    case "$opts" in
        *EnforceUnsafePermissions:true*) hdr+=$'# unsafe\n' ;;
    esac
    case "$opts" in
        *EnableSMT:true*) hdr+=$'# smt\n' ;;
    esac
    case "$opts" in
        *EmitProofHoleHints:true*) hdr+=$'# proofhole\n' ;;
    esac
    case "$opts" in
        *WarnDiscardedValues:true*) hdr+=$'# warn-discard\n' ;;
    esac
    case "$opts" in
        *EnforceProgressSafety:true*) hdr+=$'# progress\n' ;;
    esac
    case "$opts" in
        *RequireExternContracts:true*) hdr+=$'# strict-externs\n' ;;
    esac
    # regionStackCap is recorded in the fingerprint (an analyzer global some region-lifetime
    # tests override from the production default 64). Replay a NON-DEFAULT cap as a
    # `# regioncap N` header so stage1's region checker uses the same budget; the default 64
    # is stage1's own default and needs no header.
    case "$opts" in
        *regionStackCap=64*) : ;;
        *regionStackCap=*)
            rc="${opts##*regionStackCap=}"; rc="${rc%%[!0-9]*}"
            [ -n "$rc" ] && hdr+="# regioncap ${rc}"$'\n' ;;
    esac
    fname="$(printf '%s' "$fname_b64" | openssl base64 -d -A 2>/dev/null)"
    is_runtime_std "$fname" && hdr+=$'# std\n'
    # Option-injected overlay layouts (7th column) are replayed as their IN-SOURCE
    # spelling: `struct L layout(guest[, size: N]):` with `field: u<W*8> at OFF` lines.
    overlay_src=""
    if [[ -n "${overlay_b64:-}" ]]; then
        overlay_src="$(printf '%s' "$overlay_b64" | openssl base64 -d -A 2>/dev/null | awk -F'|' 'NF>=4 {
            hdr = "struct " $1 " layout(guest"
            if ($2+0 > 0) hdr = hdr ", size: " $2
            if ($3+0 > 0) hdr = hdr ", stride: " $3
            print hdr "):"
            n = split($4, fs, ",")
            for (i = 1; i <= n; i++) {
                split(fs[i], parts, ":")
                w = parts[3] + 0; bits = (w > 0 ? w * 8 : 64)
                line = "\t" parts[1] ": u" bits " at " parts[2]
                if (parts[4] + 0 > 0) line = line " requires size >= " parts[4]
                print line
            }
            print ""
        }')"
    fi
    out="$({ printf '%s' "$hdr"; if [[ -n "$overlay_src" ]]; then printf '%s\n' "$overlay_src"; fi; printf '%s' "$src_b64" | openssl base64 -d -A; } | "$RPT")"
    parse_errors="$(printf '%s\n' "$out" | awk '$1 == "P" { print $2; exit }')"
    diagnostics="$(printf '%s\n' "$out" | awk '$1 == "D" { print $2; exit }')"
    [[ -n "$parse_errors" ]] || parse_errors=999999
    [[ -n "$diagnostics" ]] || diagnostics=999999
    expected_class=0
    actual_class=0
    [[ $((errors + warnings)) -gt 0 ]] && expected_class=1
    [[ $((parse_errors + diagnostics)) -gt 0 ]] && actual_class=1
    if [[ "$expected_class" != "$actual_class" ]]; then
        mismatches=$((mismatches + 1))
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$fname_b64" "$errors" "$warnings" "$opts_b64" "$src_b64" "$msgs_b64" >> "$WORK/mismatches.tsv"
    fi
done < "$WORK/deduped.tsv"

# Optional persistent dump for burn-down work (not part of the gate).
if [[ -n "${ELISA_INTERNAL_MISMATCH_OUT:-}" ]]; then
    cp "$WORK/mismatches.tsv" "$ELISA_INTERNAL_MISMATCH_OUT"
fi

if [[ "$mismatches" -gt "$baseline" ]]; then
    echo "semantic internal diff FAILED: $mismatches/$total mismatches exceeds baseline $baseline" >&2
    echo "first 20 mismatching sources:" >&2
    head -20 "$WORK/mismatches.tsv" | while IFS=$'\t' read -r f e w o s m; do
        echo "--- expected errors=$e warnings=$w opts=$(printf '%s' "$o" | openssl base64 -d -A)" >&2
        printf '%s' "$s" | openssl base64 -d -A | head -12 >&2
        echo >&2
    done
    exit 1
fi
if [[ "$mismatches" -lt "$baseline" ]]; then
    echo "semantic internal diff: IMPROVED to $mismatches/$total (baseline $baseline) — commit the new baseline: echo $mismatches > test/fixtures/semantic_internal.baseline" >&2
fi
echo "semantic internal diff OK: $mismatches/$total mismatches (baseline $baseline)" >&2
