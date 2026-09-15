"""Time/output-bounded client for the optional Elisascript WASM export scanner.

The subprocess output buffer is capped, but this client does not impose an RSS limit on the
configured scanner process. POSIX cleanup targets its process group; detached descendants are
outside that guarantee.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from typing import Any


MAX_PROCESS_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_FLATTENED_SOURCE_BYTES = 8 * 1024 * 1024
MAX_EXPORTS = 65536
MAX_PARAMETERS_PER_EXPORT = 4096
MAX_TOTAL_PARAMETERS = 16384
PROCESS_TIMEOUT_SECONDS = 120
PROCESS_KILL_WAIT_SECONDS = 5
OUTPUT_DRAIN_GRACE_SECONDS = 1
OUTPUT_CHUNK_BYTES = 64 * 1024

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z", re.ASCII)
_TARGET = re.compile(r"[A-Za-z_][A-Za-z0-9_:]*\Z", re.ASCII)
_SCALAR_WASM_TYPES = {
    "i8": "i32",
    "u8": "i32",
    "i16": "i32",
    "u16": "i32",
    "i32": "i32",
    "u32": "i32",
    "i64": "i64",
    "u64": "i64",
    "int": "i32",
    "char": "i64",
    "isize": "i32",
    "usize": "i32",
    "uintptr": "i32",
    "f32": "f32",
    "f64": "f64",
    "bool": "i32",
    "void": "void",
}


class WasmExportScanClientError(RuntimeError):
    """The configured Elisascript scanner failed or broke its payload protocol."""


def _duplicate_key_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-standard JSON constant")


def _require_string(value: Any, label: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise WasmExportScanClientError(f"invalid scanner payload field: {label}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise WasmExportScanClientError(f"invalid UTF-8 scanner payload field: {label}") from error
    return value


def _require_identifier(value: Any, label: str) -> str:
    identifier = _require_string(value, label, nonempty=True)
    if _IDENTIFIER.fullmatch(identifier) is None:
        raise WasmExportScanClientError(f"invalid scanner payload field: {label}")
    return identifier


def _abi_for_type(type_name: str) -> tuple[str, str] | None:
    if type_name.endswith("?"):
        return None
    if type_name == "cstr":
        return "string", "i32"
    if type_name.endswith("&"):
        return "pointer", "i32"
    wasm_type = _SCALAR_WASM_TYPES.get(type_name)
    if wasm_type is None:
        return None
    return "scalar", wasm_type


def _validate_abi(type_name: str, binding: Any, wasm_type: Any, label: str) -> None:
    expected = _abi_for_type(type_name)
    if expected is None or (binding, wasm_type) != expected:
        raise WasmExportScanClientError(f"inconsistent scanner payload ABI: {label}")


def _validate_exports(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_EXPORTS:
        raise WasmExportScanClientError("invalid scanner payload field: exports")

    exports: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    total_parameters = 0
    for index, row in enumerate(value):
        label = f"exports[{index}]"
        if not isinstance(row, dict):
            raise WasmExportScanClientError(f"invalid scanner payload field: {label}")
        expected_keys = ["name", "target", "parameters", "return", "binding", "wasm_type", "line"]
        if "link_name" in row:
            expected_keys.append("link_name")
        if "implicit" in row:
            expected_keys.append("implicit")
        if list(row) != expected_keys:
            raise WasmExportScanClientError(f"invalid scanner payload field order: {label}")

        name = _require_identifier(row["name"], f"{label}.name")
        target = _require_string(row["target"], f"{label}.target", nonempty=True)
        if _TARGET.fullmatch(target) is None:
            raise WasmExportScanClientError(f"invalid scanner payload field: {label}.target")
        return_type = _require_string(row["return"], f"{label}.return", nonempty=True)
        if name in seen_names:
            raise WasmExportScanClientError("duplicate export name in scanner payload")
        seen_names.add(name)

        if not isinstance(row["binding"], str) or row["binding"] not in {
            "scalar", "string", "pointer"
        }:
            raise WasmExportScanClientError(f"invalid scanner payload field: {label}.binding")
        if not isinstance(row["wasm_type"], str) or row["wasm_type"] not in {
            "i32", "i64", "f32", "f64", "void"
        }:
            raise WasmExportScanClientError(f"invalid scanner payload field: {label}.wasm_type")
        _validate_abi(return_type, row["binding"], row["wasm_type"], f"{label}.return")
        if type(row["line"]) is not int or row["line"] < 1:
            raise WasmExportScanClientError(f"invalid scanner payload field: {label}.line")

        if "link_name" in row:
            # The scanner's source syntax permits an empty quoted link name.
            _require_string(row["link_name"], f"{label}.link_name")
        if "implicit" in row and row["implicit"] is not True:
            raise WasmExportScanClientError(f"invalid scanner payload field: {label}.implicit")

        parameters = row["parameters"]
        if not isinstance(parameters, list) or len(parameters) > MAX_PARAMETERS_PER_EXPORT:
            raise WasmExportScanClientError(f"invalid scanner payload field: {label}.parameters")
        if len(parameters) > MAX_TOTAL_PARAMETERS - total_parameters:
            raise WasmExportScanClientError("invalid scanner payload field: total parameters")
        total_parameters += len(parameters)
        seen_parameter_names: set[str] = set()
        for parameter_index, parameter in enumerate(parameters):
            parameter_label = f"{label}.parameters[{parameter_index}]"
            if not isinstance(parameter, dict) or list(parameter) != [
                "name", "type", "default", "binding", "wasm_type"
            ]:
                raise WasmExportScanClientError(
                    f"invalid scanner payload field order: {parameter_label}"
                )
            parameter_name = _require_identifier(
                parameter["name"], f"{parameter_label}.name"
            )
            if parameter_name in seen_parameter_names:
                raise WasmExportScanClientError(
                    f"duplicate parameter name in scanner payload: {parameter_label}"
                )
            seen_parameter_names.add(parameter_name)
            parameter_type = _require_string(
                parameter["type"], f"{parameter_label}.type", nonempty=True
            )
            if parameter["default"] is not None:
                _require_string(parameter["default"], f"{parameter_label}.default")
            if not isinstance(parameter["binding"], str) or parameter["binding"] not in {
                "scalar", "string", "pointer"
            }:
                raise WasmExportScanClientError(
                    f"invalid scanner payload field: {parameter_label}.binding"
                )
            if not isinstance(parameter["wasm_type"], str) or parameter["wasm_type"] not in {
                "i32", "i64", "f32", "f64", "void"
            }:
                raise WasmExportScanClientError(
                    f"invalid scanner payload field: {parameter_label}.wasm_type"
                )
            _validate_abi(
                parameter_type,
                parameter["binding"],
                parameter["wasm_type"],
                parameter_label,
            )
        exports.append(row)

    return exports


def _decode_build_payload(stdout: bytes) -> tuple[str, list[dict[str, Any]]]:
    if not stdout or len(stdout) > MAX_PROCESS_OUTPUT_BYTES or not stdout.endswith(b"\n"):
        raise WasmExportScanClientError("Elisascript scanner returned an invalid payload frame")
    json_bytes = stdout[:-1]
    if not json_bytes or b"\n" in json_bytes or b"\r" in json_bytes:
        raise WasmExportScanClientError("Elisascript scanner returned an invalid payload frame")
    try:
        payload = json.loads(
            json_bytes.decode("utf-8"),
            object_pairs_hook=_duplicate_key_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise WasmExportScanClientError("Elisascript scanner returned invalid JSON") from error

    if not isinstance(payload, dict) or list(payload) != [
        "version", "flattened_source", "exports"
    ]:
        raise WasmExportScanClientError("Elisascript scanner returned an invalid payload shape")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise WasmExportScanClientError("Elisascript scanner returned an unsupported payload version")
    flattened_source = _require_string(payload["flattened_source"], "flattened_source")
    try:
        source_bytes = len(flattened_source.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise WasmExportScanClientError(
            "Elisascript scanner returned invalid UTF-8 source"
        ) from error
    if source_bytes > MAX_FLATTENED_SOURCE_BYTES:
        raise WasmExportScanClientError("Elisascript scanner returned oversized flattened source")
    return flattened_source, _validate_exports(payload["exports"])


def _decode_flatten_payload(stdout: bytes) -> str:
    if not stdout or len(stdout) > MAX_PROCESS_OUTPUT_BYTES or not stdout.endswith(b"\n"):
        raise WasmExportScanClientError("Elisascript scanner returned an invalid payload frame")
    json_bytes = stdout[:-1]
    if not json_bytes or b"\n" in json_bytes or b"\r" in json_bytes:
        raise WasmExportScanClientError("Elisascript scanner returned an invalid payload frame")
    try:
        payload = json.loads(
            json_bytes.decode("utf-8"),
            object_pairs_hook=_duplicate_key_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise WasmExportScanClientError("Elisascript scanner returned invalid JSON") from error

    if not isinstance(payload, dict) or list(payload) != ["version", "flattened_source"]:
        raise WasmExportScanClientError("Elisascript scanner returned an invalid flatten payload shape")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise WasmExportScanClientError("Elisascript scanner returned an unsupported payload version")
    flattened_source = _require_string(payload["flattened_source"], "flattened_source")
    try:
        source_bytes = len(flattened_source.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise WasmExportScanClientError(
            "Elisascript scanner returned invalid UTF-8 source"
        ) from error
    if source_bytes > MAX_FLATTENED_SOURCE_BYTES:
        raise WasmExportScanClientError("Elisascript scanner returned oversized flattened source")
    return flattened_source


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            pass
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def _capture_process_output(command: list[str]) -> tuple[int, bytes, bytes]:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
            start_new_session=(os.name == "posix"),
            bufsize=0,
        )
    except (OSError, ValueError) as error:
        raise WasmExportScanClientError(f"unable to start Elisascript scanner: {error}") from error

    assert process.stdout is not None and process.stderr is not None
    stdout = bytearray()
    stderr = bytearray()
    captures = (stdout, stderr)
    lock = threading.Lock()
    overflow = threading.Event()
    reader_errors: list[Exception] = []

    def drain(stream: Any, destination: bytearray) -> None:
        try:
            while True:
                chunk = os.read(stream.fileno(), OUTPUT_CHUNK_BYTES)
                if not chunk:
                    return
                with lock:
                    total = len(captures[0]) + len(captures[1])
                    if total + len(chunk) > MAX_PROCESS_OUTPUT_BYTES:
                        overflow.set()
                    elif not overflow.is_set():
                        destination.extend(chunk)
        except (OSError, ValueError) as error:
            reader_errors.append(error)

    readers = [
        threading.Thread(target=drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True),
    ]
    deadline = time.monotonic() + PROCESS_TIMEOUT_SECONDS
    timed_out = False
    try:
        for reader in readers:
            reader.start()

        while process.poll() is None:
            if overflow.is_set():
                _kill_process_group(process)
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process_group(process)
                break
            try:
                process.wait(timeout=min(remaining, 0.05))
            except subprocess.TimeoutExpired:
                continue

        try:
            returncode = process.wait(timeout=PROCESS_KILL_WAIT_SECONDS)
        except subprocess.TimeoutExpired as error:
            _kill_process_group(process)
            raise WasmExportScanClientError(
                "unable to reap Elisascript scanner after termination"
            ) from error

        for reader in readers:
            reader.join(timeout=OUTPUT_DRAIN_GRACE_SECONDS)
        if any(reader.is_alive() for reader in readers):
            # A launcher must not leave descendants holding captured pipes open.
            _kill_process_group(process)
            for reader in readers:
                reader.join(timeout=OUTPUT_DRAIN_GRACE_SECONDS)

        if timed_out:
            raise WasmExportScanClientError(
                f"Elisascript scanner timed out after {PROCESS_TIMEOUT_SECONDS} seconds"
            )
        if overflow.is_set():
            raise WasmExportScanClientError("Elisascript scanner exceeded the 64 MiB output limit")
        if any(reader.is_alive() for reader in readers):
            # Do not close a pipe while a reader may be blocked in os.read: that
            # can wait on a reader lock. Daemon readers keep their own descriptors.
            raise WasmExportScanClientError(
                "Elisascript scanner left descendants holding output pipes open"
            )
        if reader_errors:
            raise WasmExportScanClientError(
                "unable to read Elisascript scanner output"
            ) from reader_errors[0]
        return returncode, bytes(stdout), bytes(stderr)
    finally:
        if process.poll() is None:
            _kill_process_group(process)
            try:
                process.wait(timeout=PROCESS_KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        if not any(reader.is_alive() for reader in readers):
            process.stdout.close()
            process.stderr.close()


def _scanner_failure(returncode: int, stdout: bytes, stderr: bytes) -> WasmExportScanClientError:
    prefix = b"wasm export scan: "
    if returncode == 1 and not stdout and stderr.startswith(prefix) and stderr.endswith(b"\n"):
        diagnostic = stderr[len(prefix):-1]
        if diagnostic:
            try:
                return WasmExportScanClientError(diagnostic.decode("utf-8"))
            except UnicodeDecodeError:
                pass
    detail = ""
    if stderr:
        detail = ": " + stderr.decode("utf-8", errors="replace").rstrip()
    return WasmExportScanClientError(
        f"Elisascript scanner exited with status {returncode}{detail}"
    )


def _scanner_command(
    launcher: str | os.PathLike[str],
    scanner_script: str | os.PathLike[str],
    source: Path,
    option: str,
) -> list[str]:
    launcher_path = Path(launcher)
    scanner_path = Path(scanner_script)
    if (
        not launcher_path.is_absolute()
        or not scanner_path.is_absolute()
        or not source.is_absolute()
    ):
        raise WasmExportScanClientError(
            "Elisascript scanner, script, and source paths must be absolute"
        )
    try:
        launcher_path = launcher_path.resolve(strict=True)
        scanner_path = scanner_path.resolve(strict=True)
    except (OSError, ValueError, RuntimeError) as error:
        raise WasmExportScanClientError("Elisascript scanner executable or script was not found") from error
    if not launcher_path.is_file() or not os.access(launcher_path, os.X_OK):
        raise WasmExportScanClientError("Elisascript scanner launcher is not an executable file")
    if not scanner_path.is_file():
        raise WasmExportScanClientError("Elisascript scanner script is not a regular file")

    return [
        os.fspath(launcher_path),
        os.fspath(scanner_path),
        option,
        os.fspath(source),
    ]


def run_export_scan(
    launcher: str | os.PathLike[str],
    scanner_script: str | os.PathLike[str],
    source: Path,
) -> tuple[str, list[dict[str, Any]]]:
    """Run the configured scanner and validate its versioned build payload."""
    command = _scanner_command(launcher, scanner_script, source, "--build-payload")
    returncode, stdout, stderr = _capture_process_output(command)
    if returncode != 0:
        raise _scanner_failure(returncode, stdout, stderr)
    if stderr:
        raise WasmExportScanClientError("Elisascript scanner wrote unexpected stderr on success")
    return _decode_build_payload(stdout)


def run_flatten_source(
    launcher: str | os.PathLike[str],
    scanner_script: str | os.PathLike[str],
    source: Path,
) -> str:
    """Run the bounded include flattener without requiring export declarations."""
    command = _scanner_command(launcher, scanner_script, source, "--flatten-payload")
    returncode, stdout, stderr = _capture_process_output(command)
    if returncode != 0:
        raise _scanner_failure(returncode, stdout, stderr)
    if stderr:
        raise WasmExportScanClientError("Elisascript scanner wrote unexpected stderr on success")
    return _decode_flatten_payload(stdout)


__all__ = ["WasmExportScanClientError", "run_export_scan", "run_flatten_source"]
