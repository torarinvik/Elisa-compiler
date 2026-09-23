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

    for name, source in GRANTED_CASTS.items():
        granted = analyze_case(reporter, f"granted_{name.replace(' ', '_')}", source, strict=True)
        output = granted.stdout + granted.stderr
        assert granted.returncode == 0 and "pointer cast requires can[Unsafe]" not in output, (
            name, granted.returncode, output[-5000:]
        )
        print(f"{name}: explicit grant accepted PASS", flush=True)

    warning = analyze_case(reporter, "default_warning", BAD_CASTS["numeric_conversion_to_generic"], strict=False)
    output = warning.stdout + warning.stderr
    assert warning.returncode == 0 and "warning:" in output and "pointer cast requires can[Unsafe]" in output, (
        warning.returncode, output[-5000:]
    )
    print("default-mode warning: PASS", flush=True)


if __name__ == "__main__":
    main()
