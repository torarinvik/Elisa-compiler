"""Stable file identities and hashes for Stage1 provenance."""
import hashlib
import json
from pathlib import Path


def file_stat_identity(path):
    stat = Path(path).stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
    }

def valid_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )

def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def fingerprint_artifact(path, previous=None, exact=False, description="artifact"):
    path = Path(path).resolve()
    try:
        identity = file_stat_identity(path)
    except OSError as error:
        raise RuntimeError(f"could not stat {description} {path}: {error}") from error
    previous = previous if isinstance(previous, dict) else {}
    prior_digest = previous.get("sha256")
    reusable = (
        not exact
        and all(previous.get(key) == value for key, value in identity.items())
        and valid_sha256(prior_digest)
    )
    if reusable:
        digest = prior_digest
    else:
        digest = sha256_file(path)
        try:
            after_identity = file_stat_identity(path)
        except OSError as error:
            raise RuntimeError(f"could not restat {description} {path}: {error}") from error
        if after_identity != identity:
            raise RuntimeError(f"{description} changed while fingerprinting: {path}")
    return {"path": str(path), **identity, "sha256": digest}


def digest_files(root, paths):
    digest = hashlib.sha256()
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(candidate for candidate in path.rglob("*") if candidate.is_file())
        elif path.is_file():
            files.append(path)
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()

def stat_inventory_digest(root, paths, freshness_extensions=()):
    root = Path(root).resolve()
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(candidate for candidate in path.rglob("*") if candidate.is_file())
        elif path.is_file():
            files.append(path)
    digest = hashlib.sha256()
    # Without ctime: macOS bumps ctime when it attaches com.apple.macl/provenance
    # attributes to a file about a second after an editor saves it, which says
    # nothing about the bytes a build read. mtime, size and inode still change on
    # every write, including a write that is reverted during the build.
    write_digest = hashlib.sha256()
    newest_source_mtime_ns = None
    newest_source_path = None
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        identity = file_stat_identity(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("ascii"))
        digest.update(b"\0")
        write_identity = {key: value for key, value in identity.items() if key != "ctime_ns"}
        write_digest.update(relative.encode("utf-8"))
        write_digest.update(b"\0")
        write_digest.update(json.dumps(write_identity, sort_keys=True, separators=(",", ":")).encode("ascii"))
        write_digest.update(b"\0")
        # Preserve the former `find ... -newer BIN` freshness rule while collecting it
        # during this inventory pass. `find -type f` does not follow file symlinks.
        if freshness_extensions and path.suffix in freshness_extensions and not path.is_symlink():
            mtime_ns = identity["mtime_ns"]
            if newest_source_mtime_ns is None or mtime_ns > newest_source_mtime_ns:
                newest_source_mtime_ns = mtime_ns
                newest_source_path = relative
    return digest.hexdigest(), write_digest.hexdigest(), newest_source_mtime_ns, newest_source_path
