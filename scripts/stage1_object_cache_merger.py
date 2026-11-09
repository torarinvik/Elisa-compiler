"""Fingerprint environment and native object merger selection."""
import hashlib
import os
import shutil
import subprocess
import sys

from stage1_object_cache_files import canonical_json, read_regular_file


def environment_key(environ=None):
    """Serialize exact compiler environment records without line-boundary ambiguity."""
    if environ is None:
        environ = os.environb if os.supports_bytes_environ else {
            os.fsencode(name): os.fsencode(value) for name, value in os.environ.items()
        }
    records = [b"elisac-stage1-environment-v1\0"]
    for name, value in sorted(environ.items()):
        if (name.startswith((b"ELISA_", b"ELISACORE_"))
                and not name.startswith(b"ELISA_STAGE1_CACHE")):
            # OS environment names cannot contain '=' or NUL, and values cannot
            # contain NUL. Newlines and non-UTF-8 value bytes remain significant.
            records.append(name + b"=" + value + b"\0")
    return b"".join(records)

def parallel_emit_jobs(value):
    """Match the backend's ASCII digit-prefix parser, including its 64-job cap."""
    jobs = 0
    for byte in os.fsencode(value):
        if byte < 48 or byte > 57:
            break
        jobs = jobs * 10 + byte - 48
        if jobs > 64:
            return 64
    return max(1, jobs)

def native_merger_record(path):
    resolved = os.path.realpath(path)
    if not os.access(resolved, os.X_OK):
        raise ValueError("object merger is not executable")
    data = read_regular_file(resolved, 512 * 1024**2)
    if data[:4] not in (b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
                        b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
                        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
                        b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"):
        raise ValueError("object merger is not a native executable")
    if os.path.realpath(path) != resolved:
        raise OSError("object merger selection changed during fingerprinting")
    return {"selected": os.fspath(path), "resolved": resolved,
            "sha256": hashlib.sha256(data).hexdigest()}

def object_merger_key(environ=None, platform=None):
    """Attest the default linker after the wrapper's loader-override admission guard."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if parallel_emit_jobs(environ.get("ELISA_STAGE1_JOBS", "")) <= 1:
        return "serial-object-emission-v1"
    # getenv() in the backend distinguishes an empty setting from an unset one.
    if "ELISA_LD" in environ:
        raise ValueError("custom object merger dependency closure is not attested")
    # system("ld ...") can import shell functions independently of PATH lookup.
    if ("ENV" in environ or "BASH_ENV" in environ or
            any(name.startswith("BASH_FUNC_") or value.lstrip().startswith("()")
                for name, value in environ.items())):
        raise ValueError("shell functions can override object merger selection")
    selected = shutil.which("ld", path=environ.get("PATH", os.defpath))
    if selected is None:
        raise ValueError("default object merger not found")
    resolved = os.path.realpath(selected)
    records = []
    if platform == "darwin":
        if selected != "/usr/bin/ld" or resolved != selected:
            raise ValueError("non-system object merger launcher")
        records.extend((native_merger_record(selected), native_merger_record("/usr/bin/xcrun")))
        query = subprocess.run(["/usr/bin/xcrun", "--find", "ld"], env=environ,
                               check=True, capture_output=True, timeout=5)
        actual = os.fsdecode(query.stdout.strip())
        if not os.path.isabs(actual):
            raise ValueError("invalid selected toolchain linker")
        records.append(native_merger_record(actual))
    elif platform.startswith("linux"):
        if os.path.dirname(resolved) not in ("/usr/bin", "/bin"):
            raise ValueError("non-system object merger launcher")
        records.append(native_merger_record(selected))
    else:
        raise ValueError("unattested platform object merger")
    # Linker/dispatch settings also include non-Elisa variables (PATH, SDKROOT,
    # DEVELOPER_DIR, TOOLCHAINS, deployment settings). Over-key rather than omit
    # a native linker's environmental input. Frame raw bytes, never log values.
    environment = b"".join(os.fsencode(name) + b"=" + os.fsencode(value) + b"\0"
                           for name, value in sorted(environ.items())
                           if not name.startswith("ELISA_STAGE1_CACHE"))
    return hashlib.sha256(b"stage1-object-merger-v1\0" + canonical_json(records)
                          + b"\0" + environment).hexdigest()
