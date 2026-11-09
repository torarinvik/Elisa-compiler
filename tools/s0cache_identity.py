"""Stable tool identities and certificate verification for the Stage0 cache."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile


NATIVE_TOOL_MAGICS = {
    b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}

def is_native_tool_image(path):
    descriptor = None
    try:
        nonblocking = getattr(os, "O_NONBLOCK", None)
        if nonblocking is None:
            return False
        flags = os.O_RDONLY | nonblocking
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return False
        with os.fdopen(descriptor, "rb") as executable:
            descriptor = None
            return executable.read(4) in NATIVE_TOOL_MAGICS
    except OSError:
        return False
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass

def binary_hash(real, *, require_native=False):
    """Hash one stable regular tool file, optionally requiring a native image."""
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns)
    before = os.stat(real)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("tool is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(real, flags)
    try:
        source = os.fdopen(descriptor, "rb")
        descriptor = None
        with source as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or identity(before) != identity(st):
                raise OSError("tool changed while opening")
            first_bytes = f.read(4)
            if require_native and first_bytes not in NATIVE_TOOL_MAGICS:
                raise OSError("tool is not a native image")
            f.seek(0)
            return _binary_hash_open_file(real, f, st, identity)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass

def _binary_hash_open_file(real, source, st, identity):
    root = cache_root()
    # mtime and size alone are not enough: replacing a same-size compiler binary
    # and restoring its mtime would otherwise keep returning the old content hash.
    # ctime changes on content updates, while device/inode catch atomic replacement.
    tag = (f"{os.path.abspath(real)}|{st.st_dev}|{st.st_ino}|{st.st_size}|"
           f"{st.st_mtime_ns}|{st.st_ctime_ns}")
    memo = os.path.join(root, "bin." + hashlib.sha256(tag.encode()).hexdigest()[:24])
    try:
        cached = read_cache_file_bounded(memo, 65).decode("ascii").strip()
        if (len(cached) == 64 and all(char in "0123456789abcdef" for char in cached)
                and identity(os.fstat(source.fileno())) == identity(st)
                and identity(os.stat(real)) == identity(st)):
            return cached
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    h = hashlib.sha256()
    for chunk in iter(lambda: source.read(1 << 20), b""):
        h.update(chunk)
    if identity(os.fstat(source.fileno())) != identity(st):
        raise OSError("tool changed while hashing")
    if identity(os.stat(real)) != identity(st):
        raise OSError("tool changed after hashing")
    digest = h.hexdigest()
    os.makedirs(root, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=root, prefix="bin-hash.", delete=False) as f:
            tmp = f.name
            f.write(digest)
        os.replace(tmp, memo)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return digest

def regular_file_identity(path):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)

def read_cache_file_bounded(path, maximum):
    """Read one stable regular cache file without trusting its recorded size."""
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError("invalid or oversized cache payload")
        data = source.read(maximum + 1)
        after = os.fstat(source.fileno())
    current = os.lstat(path)
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns)
    if (len(data) != before.st_size or len(data) > maximum or not stat.S_ISREG(current.st_mode)
            or identity(before) != identity(after) or identity(after) != identity(current)):
        raise ValueError("cache payload changed while reading")
    return data

def cache_root():
    path = os.environ.get("ELISA_S0_CACHE_DIR") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"),
        "elisa-s0cache")
    return os.path.realpath(path)

def valid_certificate(data, pid=None):
    try:
        certificate = json.loads(data)
        if certificate.get("version") != 3:
            return False
        certificate_pid = certificate.get("pid")
        # bool is an int subclass in Python and JSON true decodes to True.
        if type(certificate_pid) is not int:
            return False
        if certificate_pid <= 0 or (pid is not None and certificate_pid != pid):
            return False
        dependencies = certificate.get("dependencies")
        if not isinstance(dependencies, list) or not 1 <= len(dependencies) <= 16:
            return False
        for dependency in dependencies:
            path, digest = dependency["path"], dependency["sha256"]
            selector = dependency.get("selector", "")
            if not isinstance(path, str) or not os.path.isabs(path) or not isinstance(digest, str) or len(digest) != 64:
                return False
            if selector:
                if selector == "@llc":
                    selected = shutil.which("llc")
                    if selected is None:
                        selected = next((p for p in ("/opt/homebrew/opt/llvm/bin/llc", "/usr/local/opt/llvm/bin/llc")
                                         if os.path.isfile(p) and os.access(p, os.X_OK)), None)
                elif selector == "@merger":
                    fields = os.environ.get("ELISA_LD", "").split()
                    selected = shutil.which(fields[0] if fields else "ld")
                    if not fields and sys.platform == "darwin" and selected == "/usr/bin/ld":
                        try:
                            probe = subprocess.run(["/usr/bin/xcrun", "--find", "ld"],
                                                   capture_output=True, text=True, timeout=5, check=False)
                            candidate = probe.stdout.strip()
                            if (probe.returncode == 0 and os.path.isabs(candidate)
                                    and os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
                                selected = candidate
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                    if selected:
                        selected = os.path.realpath(selected)
                else:
                    selected = shutil.which(selector)
                if not selected or os.path.abspath(selected) != path:
                    return False
            if binary_hash(path, require_native=bool(selector)) != digest:
                # Hashing a script launcher cannot identify the executable it
                # delegates to. Such tool selectors are not certifiable here.
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        return False
