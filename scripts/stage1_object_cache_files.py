"""Safe file access and destination inspection for the Stage1 object cache."""
import ctypes
import errno
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


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

def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
