#!/usr/bin/env bash
# Two-compiler parity for a `::`-QUALIFIED error set in a function header.
#
# `error[Backend::SceneError]` names the set SceneError; Backend is a MODULE prefix. Four
# parser scans read the single Ident right after `[`, so every one of them recorded the
# module and dropped the set:
#   * header_error_family        -> the family a callee propagates
#   * capture_header_error_families -> the families the caller declares
#   * signature_error_set_name   -> the backend's error-ABI selection
#   * scan_legacy_error_syntax   -> the removed `error[Set.*]` deprecation
#   * the protocol-method scan    -> the families a protocol declares (3900000064)
# The first two together produced "cannot propagate Backend from a function returning
# SceneError" on code stage0 accepts -- and from inside a NESTED module the qualified
# spelling is the only one stage0 accepts, so this was not avoidable by rewriting. The
# protocol scan failed BOTH ways at once: it recorded every path segment, so a qualified
# IMPL method was flagged for raising `Backend`, while a genuinely extra family was masked
# by the widened set.
#
# Only the two sentences below are compared; whole-message-set parity lives in
# diagnostics_diff.sh.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
checked=0

# Line-tagged so a rule that reports the RIGHT count on the WRONG line still mismatches.
check_case() {
    local name="$1" source="$2"
    checked=$((checked + 1))
    printf '%s' "$source" > "$WORK/$name.elisa"
    local s0 s1
    s0="$("$ELISACORE_BIN" -emit semantic "$WORK/$name.elisa" 2>&1 >/dev/null \
        | grep -E 'cannot propagate |is no longer supported|not declared in the protocol' \
        | sed -E -e 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|error\[Set).*#\2 \1#' \
                 -e 's#^[^:]*:([0-9]+):[0-9]+[^ ]* impl method .*not declared in the protocol.*#implerror \1#' | sort)"
    s1="$("$REPO_ROOT/build/parse_report" < "$WORK/$name.elisa" \
        | grep -E 'cannot propagate |is no longer supported|not declared in the protocol' \
        | sed -E -e 's#^  L([0-9]+) (cannot propagate|error\[Set).*#\2 \1#' \
                 -e 's#^  L([0-9]+) impl method .*not declared in the protocol.*#implerror \1#' | sort)"
    if [ "$s0" != "$s1" ]; then
        failed=$((failed + 1))
        printf 'qualified-error-set mismatch: %s\n  stage0: %s\n  stage1: %s\n' \
            "$name" "${s0//$'\n'/ | }" "${s1//$'\n'/ | }" >&2
    fi
}

# SILENT: the qualified spelling names the same set the bare one does.
check_case nested_module_qualified $'module Backend:\n    public:\n        error SceneError:\n            Capacity\n\n    private:\n        module Recording:\n            public:\n                def record(n: i64) -> void error[Backend::SceneError]:\n                    raise Backend::SceneError.Capacity if n > 10\n\n    public:\n        def submit(n: i64) -> void error[SceneError]:\n            try Recording::record(n)\n\ndef main() -> i64:\n    return 0\n'
check_case qualified_both_sides $'module Backend:\n    public:\n        error SceneError:\n            Capacity\n\n        def record(n: i64) -> void error[Backend::SceneError]:\n            raise Backend::SceneError.Capacity if n > 10\n\ndef submit(n: i64) -> void error[Backend::SceneError]:\n    try Backend::record(n)\n\ndef main() -> i64:\n    return 0\n'
check_case qualified_multi_family $'module Net:\n    public:\n        error SendError:\n            Refused\n\n        error RecvError:\n            Empty\n\n        def send(n: i64) -> void error[Net::SendError]:\n            raise Net::SendError.Refused if n > 10\n\n        def recv(n: i64) -> void error[Net::RecvError]:\n            raise Net::RecvError.Empty if n > 10\n\ndef relay(n: i64) -> void error[Net::SendError, Net::RecvError]:\n    try Net::send(n)\n    try Net::recv(n)\n\ndef main() -> i64:\n    return 0\n'
check_case bare_unchanged $'error DiskError:\n    Full\n\ndef write_one(n: i64) -> void error[DiskError]:\n    raise DiskError.Full if n > 10\n\ndef write_all(n: i64) -> void error[DiskError]:\n    try write_one(n)\n\ndef main() -> i64:\n    return 0\n'

# FIRES: a genuine family mismatch must survive the tail rule -- two DIFFERENT sets whose
# module prefix is the same, which is exactly what reading the prefix used to conflate.
check_case qualified_real_mismatch $'module Store:\n    public:\n        error ReadError:\n            Missing\n\n        error WriteError:\n            Denied\n\n        def load(n: i64) -> void error[Store::ReadError]:\n            raise Store::ReadError.Missing if n > 10\n\ndef save(n: i64) -> void error[Store::WriteError]:\n    try Store::load(n)\n\ndef main() -> i64:\n    return 0\n'
check_case bare_real_mismatch $'error ReadError:\n    Missing\n\nerror WriteError:\n    Denied\n\ndef load(n: i64) -> void error[ReadError]:\n    raise ReadError.Missing if n > 10\n\ndef save(n: i64) -> void error[WriteError]:\n    try load(n)\n\ndef main() -> i64:\n    return 0\n'

# FIRES: the removed `error[Set.*]` wildcard sits after the whole PATH, not after the
# first segment, so the qualified spelling must be rejected exactly as the bare one is.
check_case wildcard_qualified $'module Backend:\n    public:\n        error SceneError:\n            Capacity\n\n        def go(n: i64) -> void error[Backend::SceneError.*]:\n            raise Backend::SceneError.Capacity if n > 10\n\ndef main() -> i64:\n    return 0\n'
check_case wildcard_bare $'error SceneError:\n    Capacity\n\ndef go(n: i64) -> void error[SceneError.*]:\n    raise SceneError.Capacity if n > 10\n\ndef main() -> i64:\n    return 0\n'

# The protocol error-set scan, both ways. stage0 names the offending VARIANT and stage1 the
# family, so only presence and line are compared here; the wording is diagnostics_diff's job.
check_case protocol_qualified_impl $'module Backend:\n    public:\n        error SceneError:\n            Capacity\n\n        protocol Sink:\n            def push(n: i64) -> void error[SceneError]\n\n        struct Log:\n            tag: i64\n\n        impl Sink for Log:\n            def push(n: i64) -> void error[Backend::SceneError]:\n                raise Backend::SceneError.Capacity if n > 10\n\ndef main() -> i64:\n    return 0\n'
check_case protocol_extra_family $'module Backend:\n    public:\n        error SceneError:\n            Capacity\n\n        error OtherError:\n            Nope\n\n        protocol Sink:\n            def push(n: i64) -> void error[Backend::SceneError]\n\n        struct Log:\n            tag: i64\n\n        impl Sink for Log:\n            def push(n: i64) -> void error[Backend::OtherError]:\n                raise Backend::OtherError.Nope if n > 10\n\ndef main() -> i64:\n    return 0\n'
check_case protocol_conforming $'module Backend:\n    public:\n        error SceneError:\n            Capacity\n\n        protocol Sink:\n            def push(n: i64) -> void error[Backend::SceneError]\n\n        struct Log:\n            tag: i64\n\n        impl Sink for Log:\n            def push(n: i64) -> void error[Backend::SceneError]:\n                raise Backend::SceneError.Capacity if n > 10\n\ndef main() -> i64:\n    return 0\n'

if [ "$failed" -ne 0 ]; then
    printf 'qualified-error-set smoke FAILED: %d/%d cases disagree\n' "$failed" "$checked" >&2
    exit 1
fi
printf 'qualified-error-set smoke OK: %d/%d cases agree with stage0\n' "$checked" "$checked"
