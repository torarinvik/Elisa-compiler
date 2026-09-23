#!/usr/bin/env python3
"""Keep generic pointer reinterpretations checked without rejecting safe borrow weakening."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

BAD_CASTS = {
    "null_to_generic": """def nothing[T]() -> T:
    return null.cast[T]
""",
    "numeric_to_generic": """def forge[T](address: u64) -> T:
    return address.cast[T]
""",
    "numeric_conversion_to_generic": """def forge[T](address: u64) -> T:
    return address.T()
""",
    "generic_to_generic": """def swap[T, U](value: T) -> U:
    return value.cast[U]
""",
    "generic_to_pointer": """def launder[T](value: T) -> i64&:
    value.cast[i64&]
""",
    "generic_local_to_pointer": """def launder[T](value: T) -> i64&:
    local: T = value
    local.cast[i64&]
""",
    "generic_if_expression_to_pointer": """def hidden_if[T](value: T, flag: bool) -> i64&:
    return value.cast[i64&] if flag else null
""",
    "generic_match_statement_to_pointer": """def hidden_match[T](value: T, tag: i64) -> void:
    match tag:
        1:
            value.cast[i64&]
        _:
            pass
""",
    "generic_contract_to_pointer": """def hidden_contract[T](value: T) -> void:
    requires value.cast[i64&] != null
""",
    "generic_while_condition_to_pointer": """def hidden_while[T](value: T) -> void:
    while value.cast[bool]:
        break
""",
    "pointer_to_generic": """def reinterpret[T](value: i64&) -> T&:
    value.cast[T&]
""",
    "gain_mutability": """def writable[T](value: T&) -> mutable T&:
    value.cast[mutable T&]
""",
}

SAFE_CAST = """def readonly[T](value: mutable T&) -> T&:
    value.cast[T&]
"""

SAFE_IDENTITY_CAST = """def identity[T](value: mutable T&) -> mutable T&:
    value.cast[mutable T&]
"""

GRANTED_CASTS = {
    "generic cast": """def convert[T, U](value: T) -> U:
    can Unsafe.PointerCast:
        return value.cast[U]
""",
    "generic constructor conversion": """def convert[T](address: u64) -> T:
    can Unsafe.PointerCast:
        return address.T()
""",
}

# NUL facts from a short-lived branch snapshot are not promoted to the enclosing flow state.
# Pre-existing facts do survive joins when every path preserves them; a clear on one match arm
# invalidates them. This deliberately tests both the conservative warning and the no-escape rule.
NUL_FLOW_CASES = {
    "one_branch_terminator_does_not_escape": ("""def scan(bytes: mutable darray[u8]&, flag: bool) -> void:
    if flag:
        bytes.push(0)
    can Unsafe.PointerCast, Unsafe.BufferReinterpret:
        (&bytes[0]).cast[static u8&]
""", True),
    "new_terminator_in_every_branch_is_not_promoted": ("""def scan(bytes: mutable darray[u8]&, flag: bool) -> void:
    if flag:
        bytes.push(0)
    else:
        bytes.push(0)
    can Unsafe.PointerCast, Unsafe.BufferReinterpret:
        (&bytes[0]).cast[static u8&]
""", True),
    "zero_iteration_loop_terminator_does_not_escape": ("""def scan(bytes: mutable darray[u8]&, flag: bool) -> void:
    while flag:
        bytes.push(0)
    can Unsafe.PointerCast, Unsafe.BufferReinterpret:
        (&bytes[0]).cast[static u8&]
""", True),
    "one_match_arm_terminator_does_not_escape": ("""def scan(bytes: mutable darray[u8]&, tag: i64) -> void:
    match tag:
        0:
            bytes.push(0)
        _:
            pass
    can Unsafe.PointerCast, Unsafe.BufferReinterpret:
        (&bytes[0]).cast[static u8&]
""", True),
    "new_terminator_in_every_match_arm_is_not_promoted": ("""def scan(bytes: mutable darray[u8]&, tag: i64) -> void:
    match tag:
        0:
            bytes.push(0)
        _:
            bytes.push(0)
    can Unsafe.PointerCast, Unsafe.BufferReinterpret:
        (&bytes[0]).cast[static u8&]
""", True),
    "preexisting_terminator_survives_branch_join": ("""def scan(bytes: mutable darray[u8]&, flag: bool) -> void:
    bytes.push(0)
    if flag:
        pass
    else:
        pass
    can Unsafe.PointerCast, Unsafe.BufferReinterpret:
        (&bytes[0]).cast[static u8&]
""", False),
    "match_arm_invalidation_drops_preexisting_terminator": ("""def scan(bytes: mutable darray[u8]&, tag: i64) -> void:
    bytes.push(0)
    match tag:
        0:
            bytes.clear()
        _:
            pass
    can Unsafe.PointerCast, Unsafe.BufferReinterpret:
        (&bytes[0]).cast[static u8&]
""", True),
    "preexisting_terminator_survives_loop_join": ("""def scan(bytes: mutable darray[u8]&, flag: bool) -> void:
    bytes.push(0)
    while flag:
        pass
    can Unsafe.PointerCast, Unsafe.BufferReinterpret:
        (&bytes[0]).cast[static u8&]
""", False),
}


def build_reporter() -> Path:
    setup = subprocess.run(
        [
            "bash", "-c",
            'REPO_ROOT="$1"; source "$REPO_ROOT/test/parity/build_parse_report.sh"; printf "%s\\n" "$RPT"',
            "generic_cast_smoke", str(ROOT),
        ],
        env=os.environ.copy(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert setup.returncode == 0, setup.stderr[-5000:]
    return Path(setup.stdout.strip().splitlines()[-1])


def analyze_case(reporter: Path, name: str, source: str, strict: bool) -> subprocess.CompletedProcess[str]:
    header = "# strict\n" if strict else ""
    return subprocess.run(
        [str(reporter)], input=header + source + "\ndef main() -> i32:\n    return 0\n",
        env=os.environ.copy(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def main() -> None:
    reporter = build_reporter()
    for name, source in BAD_CASTS.items():
        result = analyze_case(reporter, name, source, strict=True)
        output = result.stdout + result.stderr
        assert result.returncode == 0 and "pointer cast requires can[Unsafe]" in output, (
            name, result.returncode, output[-5000:]
        )
        print(f"{name}: strict rejection PASS", flush=True)

    safe = analyze_case(reporter, "safe_mutability_drop", SAFE_CAST, strict=True)
    safe_output = safe.stdout + safe.stderr
    assert safe.returncode == 0 and "D 0" in safe_output, (safe.returncode, safe_output[-5000:])
    print("same-type mutability drop: accepted PASS", flush=True)

    identity = analyze_case(reporter, "same_type_mutable_identity", SAFE_IDENTITY_CAST, strict=True)
    identity_output = identity.stdout + identity.stderr
    assert identity.returncode == 0 and "D 0" in identity_output, (identity.returncode, identity_output[-5000:])
    print("same-type mutable reference: accepted PASS", flush=True)

    for name, source in GRANTED_CASTS.items():
        granted = analyze_case(reporter, f"granted_{name.replace(' ', '_')}", source, strict=True)
        output = granted.stdout + granted.stderr
        assert granted.returncode == 0 and "pointer cast requires can[Unsafe]" not in output, (
            name, granted.returncode, output[-5000:]
        )
        print(f"{name}: explicit grant accepted PASS", flush=True)

    for name, (source, should_warn) in NUL_FLOW_CASES.items():
        result = analyze_case(reporter, name, source, strict=True)
        output = result.stdout + result.stderr
        has_erasure_warning = "erases its length" in output
        assert result.returncode == 0 and has_erasure_warning == should_warn, (
            name, result.returncode, output[-5000:]
        )
        print(f"{name}: conservative NUL-flow join PASS", flush=True)

    warning = analyze_case(reporter, "default_warning", BAD_CASTS["numeric_conversion_to_generic"], strict=False)
    output = warning.stdout + warning.stderr
    assert warning.returncode == 0 and "warning:" in output and "pointer cast requires can[Unsafe]" in output, (
        warning.returncode, output[-5000:]
    )
    print("default-mode warning: PASS", flush=True)


if __name__ == "__main__":
    main()
