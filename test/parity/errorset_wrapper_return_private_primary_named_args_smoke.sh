#!/usr/bin/env bash
# Named arguments disable Core's receiver rewrite; private primary callables must
# block EWR from falling through to later public generic declarations.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_private_primary_named_args.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || {
  printf 'EWR private-primary smoke expected Core to reject private primary callables:\n%s\n' "$stage0_output" >&2
  exit 1
}
grep -qF 'Provider.choose" is private to module' <<< "$stage0_output" || {
  printf 'Core did not keep the private fallible primary callable:\n%s\n' "$stage0_output" >&2
  exit 1
}
grep -qF 'Provider.plain" is private to module' <<< "$stage0_output" || {
  printf 'Core did not keep the private infallible primary callable:\n%s\n' "$stage0_output" >&2
  exit 1
}

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" || {
  printf 'Stage1 did not parse named arguments in the private-primary fixture:\n%s\n' "$stage1_output" >&2
  exit 1
}
grep -qF '"Provider.choose" is private to module "Provider"' <<< "$stage1_output" || {
  printf 'Stage1 did not reject the private fallible primary callable:\n%s\n' "$stage1_output" >&2
  exit 1
}
grep -qF '"Provider.plain" is private to module "Provider"' <<< "$stage1_output" || {
  printf 'Stage1 did not reject the private infallible primary callable:\n%s\n' "$stage1_output" >&2
  exit 1
}
grep -q '^D 4$' <<< "$stage1_output" || {
  printf 'Stage1 diagnostics differ from the two privacy errors and their invalid-call cascades:\n%s\n' "$stage1_output" >&2
  exit 1
}
! grep -q 'cannot propagate' <<< "$stage1_output" || {
  printf 'EWR fell through to a later public generic after a private primary:\n%s\n' "$stage1_output" >&2
  exit 1
}

printf 'errorset wrapper private-primary named-argument smoke OK\n'
