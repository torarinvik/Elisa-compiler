#!/usr/bin/env bash
# Reproduce a single internal-oracle case through stage1's parse_report with the EXACT
# analyzer-option headers stage0 recorded — the reliable way to characterize a mismatch
# (a bare parse_report run uses different defaults and misleads).
#
# Usage: repro_internal_case.sh <fixture-name.elisa> [mismatch-dump.tsv]
# The dump is an ELISA_INTERNAL_MISMATCH_OUT file (cols: b64name errors warnings b64opts b64src b64msgs).
# Prints stage0's recorded errors/warnings + the option header + source + stage1's parse_report output.
name="$1"; tsv="${2:-/tmp/mm.tsv}"
enc=$(printf '%s' "$name" | openssl base64 -A)
row=$(grep -F "$enc"$'\t' "$tsv" | head -1)
[ -z "$row" ] && { echo "not found in $tsv"; exit 1; }
errors=$(printf '%s' "$row" | cut -f2); warnings=$(printf '%s' "$row" | cut -f3)
opts_b64=$(printf '%s' "$row" | cut -f4); src_b64=$(printf '%s' "$row" | cut -f5)
opts=$(printf '%s' "$opts_b64" | openssl base64 -d -A)
hdr=""
case "$opts" in *EnforceUnsafePermissions:true*|*EnforceStrictProofs:true*) hdr+=$'# strict\n';; esac
case "$opts" in *EnableSMT:true*) hdr+=$'# smt\n';; esac
case "$opts" in *FlowLintMode:2*) hdr+=$'# flow-strict\n';; *FlowLintMode:1*) hdr+=$'# flow\n';; esac
case "$opts" in *EnforceProgressSafety:true*) hdr+=$'# progress\n';; esac
echo "stage0: errors=$errors warnings=$warnings (expected_class=$([ $((errors+warnings)) -gt 0 ] && echo 1 || echo 0))"
echo "header: $(printf '%s' "$hdr" | tr '\n' ' ')"
echo "--- source ---"; printf '%s' "$src_b64" | openssl base64 -d -A
echo "--- stage1 parse_report ---"
{ printf '%s' "$hdr"; printf '%s' "$src_b64" | openssl base64 -d -A; } | "${ELISA_PARSE_REPORT:-build/parse_report}"
