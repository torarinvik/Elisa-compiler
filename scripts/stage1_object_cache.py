#!/usr/bin/env python3
"""Integrity and diagnostic replay for the opt-in object cache."""
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

SCHEMA = "elisac-stage1-object-integrity-v3"
MAX_OBJECT_BYTES = 2 * 1024**3
MAX_DIAGNOSTIC_BYTES = 64 * 1024**2
DEPENDENCY_INDEX_SCHEMA = "elisac-stage1-dependency-index-v3"
MAX_DEPENDENCY_INDEX_BYTES = 16 * 1024**2
MAX_DEPENDENCIES = 100_000


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


def file_identity(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def inode_identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode)


def open_regular(path, flags=os.O_RDONLY):
    """Open one regular file without following a swapped symlink or waiting on a FIFO."""
    safe_flags = flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(os.fspath(path), safe_flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("cache input is not a regular file")
        current = os.lstat(path)
        if file_identity(before) != file_identity(current):
            raise OSError("cache input changed while it was opened")
        return descriptor, before
    except BaseException:
        os.close(descriptor)
        raise


def read_regular_file(path, maximum, expected_identity=None):
    """Read a bounded, stable regular file with nonblocking, no-follow open semantics."""
    descriptor, before = open_regular(path)
    try:
        if expected_identity is not None and inode_identity(before) != expected_identity:
            raise OSError("cache staging file was replaced before it was read")
        if maximum is not None and before.st_size > maximum:
            raise ValueError("cache input exceeds its size limit")
        data = bytearray()
        while True:
            remaining = (1 << 20) if maximum is None else min(
                1 << 20, maximum + 1 - len(data)
            )
            if remaining <= 0:
                raise ValueError("cache input exceeds its size limit")
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            data.extend(chunk)
            if maximum is not None and len(data) > maximum:
                raise ValueError("cache input exceeds its size limit")
        after = os.fstat(descriptor)
        current = os.lstat(path)
        if (
            file_identity(before) != file_identity(after)
            or file_identity(after) != file_identity(current)
        ):
            raise OSError("cache input changed while it was read")
        if len(data) != after.st_size:
            raise OSError("cache input size changed while it was read")
        return bytes(data)
    finally:
        os.close(descriptor)


def write_regular_file(path, data, expected_identity=None):
    """Write a staging file without following or blocking on a replacement."""
    descriptor, before = open_regular(path, os.O_WRONLY)
    try:
        if expected_identity is not None and inode_identity(before) != expected_identity:
            raise OSError("cache metadata staging file was replaced")
        os.ftruncate(descriptor, 0)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while staging cache metadata")
            view = view[written:]
        after = os.fstat(descriptor)
        current = os.lstat(path)
        if (
            inode_identity(before) != inode_identity(after)
            or file_identity(after) != file_identity(current)
            or after.st_size != len(data)
        ):
            raise OSError("cache metadata staging file changed while it was written")
    finally:
        os.close(descriptor)


def chmod_regular_file(path, mode, expected_identity):
    """Change permissions only on the original staging inode."""
    descriptor, before = open_regular(path)
    try:
        if inode_identity(before) != expected_identity:
            raise OSError("cache staging file was replaced before chmod")
        os.fchmod(descriptor, mode)
        after = os.fstat(descriptor)
        current = os.lstat(path)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or stat.S_IFMT(after.st_mode) != stat.S_IFMT(before.st_mode)
            or file_identity(after) != file_identity(current)
            or stat.S_IMODE(after.st_mode) != mode
        ):
            raise OSError("cache staging file changed while permissions were set")
        return inode_identity(after)
    finally:
        os.close(descriptor)


def require_staged_path(path, expected_identity):
    current = os.lstat(path)
    if not stat.S_ISREG(current.st_mode) or inode_identity(current) != expected_identity:
        raise OSError("cache staging path was replaced before publication")


def descriptor_has_extended_acl(descriptor):
    """Return whether a macOS ACL is present, or None when it cannot be verified."""
    if sys.platform != "darwin":
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        get_acl = libc.acl_get_fd_np
        free_acl = libc.acl_free
    except AttributeError:
        return None
    get_acl.argtypes = (ctypes.c_int, ctypes.c_int)
    get_acl.restype = ctypes.c_void_p
    free_acl.argtypes = (ctypes.c_void_p,)
    free_acl.restype = ctypes.c_int
    ctypes.set_errno(0)
    acl = get_acl(descriptor, 0x00000100)  # ACL_TYPE_EXTENDED from sys/acl.h
    error = ctypes.get_errno()
    if acl:
        free_acl(acl)
        return True
    if error == errno.ENOENT:
        return False
    return None


def descriptor_has_xattrs(descriptor):
    """Check xattr presence without allocating a buffer proportional to its names."""
    if sys.platform == "darwin":
        argument_types = (ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    elif sys.platform.startswith("linux"):
        argument_types = (ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t)
    else:
        return None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        flistxattr = libc.flistxattr
    except (AttributeError, OSError):
        return None
    flistxattr.argtypes = argument_types
    flistxattr.restype = ctypes.c_ssize_t
    ctypes.set_errno(0)
    if sys.platform == "darwin":
        size = flistxattr(descriptor, None, 0, 0)
    else:
        size = flistxattr(descriptor, None, 0)
    if size < 0:
        return None
    if sys.platform == "darwin" and size == len(b"com.apple.provenance\0"):
        # macOS attaches this opaque provenance tag to ordinary new files.
        # Admit it only by name; restore separately requires its exact value
        # to match the existing destination before replacing that destination.
        names = ctypes.create_string_buffer(size)
        if flistxattr(descriptor, names, size, 0) != size:
            return None
        return names.raw != b"com.apple.provenance\0"
    return size > 0


def descriptor_provenance(descriptor):
    """Read the bounded macOS provenance tag, preserving it by exact comparison."""
    if sys.platform != "darwin":
        return None
    libc = ctypes.CDLL(None, use_errno=True)
    getxattr = libc.fgetxattr
    getxattr.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p,
                         ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int)
    getxattr.restype = ctypes.c_ssize_t
    name = b"com.apple.provenance"
    size = getxattr(descriptor, name, None, 0, 0, 0)
    if size < 0:
        if ctypes.get_errno() == errno.ENOATTR:
            return None
        raise OSError(ctypes.get_errno(), "cannot read output provenance")
    if size > 4096:
        raise OSError("output provenance exceeds cache metadata limit")
    value = ctypes.create_string_buffer(size)
    if getxattr(descriptor, name, value, size, 0, 0) != size:
        raise OSError("output provenance changed while being read")
    return value.raw.hex()


def compiler_output_state(path):
    """Return output mode semantics for an atomic cache replacement, or None to decline."""
    path = Path(path)
    try:
        parent = path.parent.stat()
    except OSError:
        return None
    if not stat.S_ISDIR(parent.st_mode):
        return None
    # A temp file created beside the destination inherits directory defaults,
    # while replacing an existing file discards that file's ACLs and xattrs.
    # macOS directory xattrs (including privacy grants) are not inherited by
    # children; its inheritable ACL is checked separately. Linux default ACLs
    # are xattrs, so retain the conservative directory check there.
    # Only admit files whose ownership will match the replacement.
    parent_descriptor = None
    try:
        parent_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        parent_opened = os.fstat(parent_descriptor)
        if file_identity(parent) != file_identity(parent_opened):
            return None
        if (
            (sys.platform != "darwin" and descriptor_has_xattrs(parent_descriptor) is not False)
            or descriptor_has_extended_acl(parent_descriptor) is not False
        ):
            return None
        parent_after = os.fstat(parent_descriptor)
        current_parent = os.stat(path.parent)
        if (
            file_identity(parent_opened) != file_identity(parent_after)
            or file_identity(parent_after) != file_identity(current_parent)
        ):
            return None
    except (OSError, TypeError):
        return None
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        # LLVM creates a new output with 0666 filtered through the caller's umask.
        mask = os.umask(0)
        os.umask(mask)
        return {"exists": False, "umask": mask, "mode": 0o666 & ~mask}
    except OSError:
        return None
    mode = stat.S_IMODE(before.st_mode)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or mode & ~0o777
    ):
        return None
    if not hasattr(os, "geteuid") or not hasattr(os, "getegid"):
        return None
    expected_gid = parent.st_gid if parent.st_mode & stat.S_ISGID else os.getegid()
    if before.st_uid != os.geteuid() or before.st_gid != expected_gid:
        return None
    descriptor = None
    try:
        flags = os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != before.st_uid
            or opened.st_gid != before.st_gid
            or file_identity(before) != file_identity(opened)
        ):
            return None
        if descriptor_has_xattrs(descriptor) is not False:
            return None
        if descriptor_has_extended_acl(descriptor) is not False:
            return None
        if getattr(opened, "st_flags", 0):
            return None
        provenance = descriptor_provenance(descriptor)
        after = os.lstat(path)
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if (
        after.st_nlink != 1
        or after.st_uid != opened.st_uid
        or after.st_gid != opened.st_gid
        or file_identity(before) != file_identity(after)
    ):
        return None
    return {"exists": True, "identity": file_identity(after), "mode": mode,
            "provenance": provenance}


def fingerprint(path):
    digest = hashlib.sha256()
    descriptor, before = open_regular(path)
    try:
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        current = os.lstat(path)
        if (
            file_identity(before) != file_identity(after)
            or file_identity(after) != file_identity(current)
            or size != after.st_size
        ):
            raise OSError("dependency changed while it was being hashed")
    finally:
        os.close(descriptor)
    # Keep stable identity alongside content. Cache keys use content alone, while
    # the separate postflight identity snapshot catches a file that changed during
    # compilation and was restored to identical bytes before publication.
    return {
        "device": after.st_dev,
        "inode": after.st_ino,
        "mtime_ns": after.st_mtime_ns,
        "ctime_ns": after.st_ctime_ns,
        "size": size,
        "sha256": digest.hexdigest(),
    }


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def unchanged_fingerprint(path, previous):
    """Reuse a cached digest when the filesystem identity proves the file unchanged."""
    if not isinstance(previous, dict):
        return None
    digest = previous.get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        return None
    descriptor, info = open_regular(path)
    try:
        after = os.fstat(descriptor)
        current = os.lstat(path)
        if (
            file_identity(info) != file_identity(after)
            or file_identity(after) != file_identity(current)
        ):
            raise OSError("dependency changed while its cached identity was checked")
    finally:
        os.close(descriptor)
    identity = {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "size": info.st_size,
    }
    if any(previous.get(name) != value for name, value in identity.items()):
        return None
    return {**identity, "sha256": digest}


def dependency_records(paths, root, previous_records=None):
    root_path = Path(root).resolve(strict=True)
    records = []
    seen = set()
    for index, spelling in enumerate(paths):
        if index >= MAX_DEPENDENCIES:
            raise ValueError("dependency report exceeds its path limit")
        if not isinstance(spelling, str) or not spelling or "\0" in spelling:
            raise ValueError("invalid dependency path")
        path = Path(spelling)
        resolved = path.resolve(strict=True)
        previous = (previous_records or {}).get(spelling)
        identity = unchanged_fingerprint(resolved, previous)
        if identity is None:
            identity = fingerprint(resolved)
        record = {"path": spelling, "resolved_path": str(resolved), **identity}
        if spelling in seen:
            raise ValueError("dependency report repeats a path")
        seen.add(spelling)
        records.append(record)
    if not records or records[0]["resolved_path"] != str(root_path):
        raise ValueError("dependency report does not begin with its root source")
    return str(root_path), records


def dependency_graph_digest(root, records):
    # Cache identity is content-addressed: touching or replacing a source with
    # identical bytes should still permit a previously compiled object to hit.
    dependencies = [
        {key: record[key] for key in ("path", "resolved_path", "size", "sha256")}
        for record in records
    ]
    return hashlib.sha256(canonical_json({"root": root, "dependencies": dependencies})).hexdigest()


def dependency_identity_digest(root, records):
    # The post-compile guard also needs to know if a source changed and was
    # restored to its original bytes while the compiler was running.
    dependencies = [
        {key: record[key] for key in ("path", "resolved_path", "device", "inode", "mtime_ns", "ctime_ns")}
        for record in records
    ]
    return hashlib.sha256(canonical_json({"root": root, "dependencies": dependencies})).hexdigest()


def write_dependency_manifest(index, manifest):
    index = Path(index)
    payload = canonical_json(manifest)
    if len(payload) > MAX_DEPENDENCY_INDEX_BYTES:
        return False
    index.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=index.name + ".incoming.", dir=index.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, index)
    finally:
        Path(temporary_path).unlink(missing_ok=True)
    return True


def dependencies_from_output(path, root):
    raw = read_regular_file(path, MAX_DEPENDENCY_INDEX_BYTES)
    if raw.endswith(b"\n"):
        raw = raw[:-1]
        if raw.endswith(b"\n"):
            raise ValueError("dependency report contains an empty path")
    if not raw:
        raise ValueError("empty dependency report")
    # `-emit deps` emits one path per line. Reject ambiguous empty/interior lines.
    spellings = []
    start = 0
    while start < len(raw):
        newline = raw.find(b"\n", start)
        end = len(raw) if newline < 0 else newline
        if end == start:
            raise ValueError("dependency report contains an empty path")
        if len(spellings) >= MAX_DEPENDENCIES:
            raise ValueError("dependency report exceeds its path limit")
        spellings.append(os.fsdecode(raw[start:end]))
        if newline < 0:
            break
        start = newline + 1
    return dependency_records(spellings, root)


def read_dependencies(index, base_key, root):
    try:
        raw = read_regular_file(index, MAX_DEPENDENCY_INDEX_BYTES)
        manifest = json.loads(raw)
        if not isinstance(manifest, dict) or set(manifest) != {
            "schema", "base_key", "root", "dependencies", "graph_sha256", "identity_sha256"
        }:
            return None
        expected_root = str(Path(root).resolve(strict=True))
        if manifest["schema"] != DEPENDENCY_INDEX_SCHEMA or manifest["base_key"] != base_key:
            return None
        if manifest["root"] != expected_root or not isinstance(manifest["dependencies"], list):
            return None
        if len(manifest["dependencies"]) > MAX_DEPENDENCIES:
            return None
        paths = []
        previous_records = {}
        for record in manifest["dependencies"]:
            if not isinstance(record, dict) or set(record) != {
                "path", "resolved_path", "device", "inode", "mtime_ns", "ctime_ns", "size", "sha256"
            }:
                return None
            if not isinstance(record["path"], str):
                return None
            paths.append(record["path"])
            previous_records[record["path"]] = record
        root_value, records = dependency_records(paths, root, previous_records)
        graph_sha256 = dependency_graph_digest(root_value, records)
        identity_sha256 = dependency_identity_digest(root_value, records)
        if (
            records != manifest["dependencies"]
            or graph_sha256 != manifest["graph_sha256"]
            or identity_sha256 != manifest["identity_sha256"]
        ):
            return None
        return graph_sha256, identity_sha256
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def store_dependencies(index, base_key, report, root):
    root_value, records = dependencies_from_output(report, root)
    manifest = {
        "schema": DEPENDENCY_INDEX_SCHEMA,
        "base_key": base_key,
        "root": root_value,
        "dependencies": records,
        "graph_sha256": dependency_graph_digest(root_value, records),
        "identity_sha256": dependency_identity_digest(root_value, records),
    }
    write_dependency_manifest(index, manifest)
    return manifest["graph_sha256"], manifest["identity_sha256"]


def confirm_dependencies(snapshot, index, base_key, report, root):
    # The snapshot is recorded after one compiler dependency pass. Confirm it
    # against a second pass so an edit between discovery and hashing cannot pair
    # new root bytes with an old include set.
    state = read_dependencies(snapshot, base_key, root)
    if state is None:
        return None
    manifest = json.loads(read_regular_file(snapshot, MAX_DEPENDENCY_INDEX_BYTES))
    root_value, records = dependencies_from_output(report, root)
    if root_value != manifest["root"] or records != manifest["dependencies"]:
        return None
    graph = dependency_graph_digest(root_value, records)
    identity = dependency_identity_digest(root_value, records)
    if state != (graph, identity):
        return None
    if not write_dependency_manifest(index, manifest):
        return None
    return graph, identity


def copy_digest(source, target, *, allow_empty=False, limit=None, target_identity=None):
    digest = hashlib.sha256()
    size = 0
    source_fd, source_before = open_regular(source)
    target_fd = None
    try:
        target_fd, target_before = open_regular(target, os.O_RDWR)
        if target_identity is not None and inode_identity(target_before) != target_identity:
            raise OSError("cache staging file was replaced")
        os.ftruncate(target_fd, 0)
        while chunk := os.read(source_fd, 1024 * 1024):
            size += len(chunk)
            if size > (MAX_OBJECT_BYTES if limit is None else limit):
                raise ValueError("cache payload exceeds limit")
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise OSError("short write while staging cache payload")
                view = view[written:]
        source_after = os.fstat(source_fd)
        source_path_after = os.lstat(source)
        target_after = os.fstat(target_fd)
        target_path_after = os.lstat(target)
        if (
            file_identity(source_before) != file_identity(source_after)
            or file_identity(source_after) != file_identity(source_path_after)
            or source_after.st_size != size
        ):
            raise OSError("cache source changed while it was copied")
        if (
            inode_identity(target_before) != inode_identity(target_after)
            or file_identity(target_after) != file_identity(target_path_after)
            or target_after.st_size != size
        ):
            raise OSError("cache staging file changed while it was written")
    finally:
        os.close(source_fd)
        if target_fd is not None:
            os.close(target_fd)
    if size == 0 and not allow_empty:
        raise ValueError("empty cache object")
    return {"size": size, "sha256": digest.hexdigest()}


def temporary(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".incoming.", dir=path.parent)
    try:
        identity = inode_identity(os.fstat(fd))
    finally:
        os.close(fd)
    return Path(name), identity


def restore(entry, output, key, *, destination=None, stdout=None, stderr=None):
    staged = []
    admitted = False
    try:
        try:
            output_parent = Path(output).parent.stat()
        except OSError:
            return False
        if not stat.S_ISDIR(output_parent.st_mode):
            return False
        destination_state = None
        if destination is not None:
            destination_state = compiler_output_state(destination)
            if destination_state is None:
                return False
        try:
            output_before = os.lstat(output)
        except FileNotFoundError:
            output_identity = None
        else:
            # A compiler opened with -o follows symlinks and writes through hard
            # links. Replacing either directory entry on a cache hit would change
            # observable output-path behavior, so let the compiler handle it.
            if not stat.S_ISREG(output_before.st_mode) or output_before.st_nlink != 1:
                return False
            output_identity = file_identity(output_before)
        raw = read_regular_file(str(entry) + ".json", 16384)
        metadata = json.loads(raw)
        if metadata.get("schema") != SCHEMA or metadata.get("key") != key:
            return False
        obj, obj_identity = temporary(output)
        staged.append(obj)
        expected_object = metadata.get("object")
        if not isinstance(expected_object, dict):
            return False
        mode = expected_object.get("mode")
        if type(mode) is not int or mode < 0 or mode > 0o777:
            return False
        if destination_state is not None:
            mode = destination_state["mode"]
        copied_object = copy_digest(entry, obj, target_identity=obj_identity)
        if copied_object != {key: expected_object.get(key) for key in ("size", "sha256")}:
            return False
        obj_identity = chmod_regular_file(obj, mode, obj_identity)
        if destination_state is not None and destination_state["exists"]:
            descriptor, _ = open_regular(obj)
            try:
                if descriptor_provenance(descriptor) != destination_state["provenance"]:
                    return False
            finally:
                os.close(descriptor)
        streams = {}
        for name in ("stdout", "stderr"):
            target, target_identity = temporary(output)
            staged.append(target)
            source = Path(str(entry) + "." + name)
            copied = copy_digest(
                source,
                target,
                allow_empty=True,
                limit=MAX_DIAGNOSTIC_BYTES,
                target_identity=target_identity,
            )
            if copied != metadata["streams"][name]:
                return False
            streams[name] = (target, target_identity)
        # Verify the exact copied object AND both streams before any publication.
        try:
            output_after = os.lstat(output)
        except FileNotFoundError:
            if output_identity is not None:
                return False
        else:
            if (
                output_identity is None
                or not stat.S_ISREG(output_after.st_mode)
                or output_after.st_nlink != 1
                or file_identity(output_after) != output_identity
            ):
                return False
        if destination is not None and compiler_output_state(destination) != destination_state:
            return False
        require_staged_path(obj, obj_identity)
        os.replace(obj, output)
        admitted = True
        for name, destination in (("stderr", stderr), ("stdout", stdout)):
            destination = destination if destination is not None else getattr(sys, name).buffer
            stream_path, stream_identity = streams[name]
            destination.write(
                read_regular_file(
                    stream_path,
                    MAX_DIAGNOSTIC_BYTES,
                    expected_identity=stream_identity,
                )
            )
            destination.flush()
        return True
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        # Stream/output I/O failure after admission must fail the invocation, not
        # fall through into another compile after partial diagnostic replay.
        if admitted:
            raise
        return False
    finally:
        for path in staged:
            path.unlink(missing_ok=True)


def publish(entry, output, key, stdout=None, stderr=None):
    staged = []
    try:
        obj, obj_identity = temporary(entry)
        staged.append(obj)
        output_before = os.lstat(output)
        if not stat.S_ISREG(output_before.st_mode):
            return False
        mode = stat.S_IMODE(output_before.st_mode) & 0o777
        object_digest = copy_digest(output, obj, target_identity=obj_identity)
        output_after = os.lstat(output)
        if (not stat.S_ISREG(output_after.st_mode)
                or file_identity(output_before) != file_identity(output_after)
                or (stat.S_IMODE(output_after.st_mode) & 0o777) != mode):
            return False
        metadata = {"schema": SCHEMA, "key": key,
                    "object": {**object_digest, "mode": mode}, "streams": {}}
        payloads = [(obj, obj_identity, entry)]
        for name, source in (("stdout", stdout), ("stderr", stderr)):
            target, target_identity = temporary(entry)
            staged.append(target)
            if source is None:
                metadata["streams"][name] = {"size": 0, "sha256": hashlib.sha256(b"").hexdigest()}
            else:
                metadata["streams"][name] = copy_digest(
                    source,
                    target,
                    allow_empty=True,
                    limit=MAX_DIAGNOSTIC_BYTES,
                    target_identity=target_identity,
                )
            payloads.append((target, target_identity, Path(str(entry) + "." + name)))
        stamp, stamp_identity = temporary(Path(str(entry) + ".json"))
        staged.append(stamp)
        write_regular_file(stamp, json.dumps(metadata).encode(), stamp_identity)
        # Publish metadata last. Partial or racing generations fail validation.
        for source, source_identity, target in payloads:
            require_staged_path(source, source_identity)
            os.replace(source, target)
        require_staged_path(stamp, stamp_identity)
        os.replace(stamp, str(entry) + ".json")
        return True
    except (OSError, ValueError):
        return False
    finally:
        for path in staged:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    operation, *arguments = sys.argv[1:]
    try:
        if operation == "environment-key":
            if arguments:
                raise ValueError("environment-key accepts no arguments")
            sys.stdout.buffer.write(environment_key())
            sys.exit(0)
        elif operation == "dependency-key":
            index, base_key, root = arguments
            state = read_dependencies(index, base_key, root)
            if state is None:
                sys.exit(1)
            print(*state, sep="\t")
            sys.exit(0)
        elif operation == "dependency-store":
            index, base_key, report, root = arguments
            print(*store_dependencies(index, base_key, report, root), sep="\t")
            sys.exit(0)
        elif operation == "dependency-confirm":
            snapshot, index, base_key, report, root = arguments
            state = confirm_dependencies(snapshot, index, base_key, report, root)
            if state is None:
                sys.exit(1)
            print(*state, sep="\t")
            sys.exit(0)
        elif operation == "output-state":
            path, = arguments
            state = compiler_output_state(path)
            if state is None:
                sys.exit(1)
            print(json.dumps(state, sort_keys=True, separators=(",", ":")))
            sys.exit(0)
        elif operation == "restore":
            entry, output, key, *streams = arguments
            if len(streams) > 1:
                raise ValueError("restore accepts at most one final destination path")
            destination = Path(streams[0]) if streams else None
            valid = restore(Path(entry), Path(output), key, destination=destination)
        elif operation == "publish":
            entry, output, key, *streams = arguments
            valid = publish(Path(entry), Path(output), key, *map(Path, streams))
        else:
            raise ValueError("unknown cache operation")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"object cache replay failed: {error}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if valid else 1)
