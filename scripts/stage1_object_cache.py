#!/usr/bin/env python3
"""Integrity and diagnostic replay for the opt-in object cache."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

SCHEMA = "elisac-stage1-object-integrity-v3"
MAX_OBJECT_BYTES = 2 * 1024**3
MAX_DIAGNOSTIC_BYTES = 64 * 1024**2
DEPENDENCY_INDEX_SCHEMA = "elisac-stage1-dependency-index-v3"
MAX_DEPENDENCY_INDEX_BYTES = 16 * 1024**2
MAX_DEPENDENCIES = 100_000


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("dependency is not a regular file")
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if identity_before != identity_after or size != after.st_size:
        raise OSError("dependency changed while it was being hashed")
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
    info = Path(path).stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("dependency is not a regular file")
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
    raw = Path(path).read_bytes()
    if len(raw) > MAX_DEPENDENCY_INDEX_BYTES:
        raise ValueError("dependency report exceeds its size limit")
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if not raw:
        raise ValueError("empty dependency report")
    # `-emit deps` emits one path per line. Reject ambiguous empty/interior lines.
    spellings = [os.fsdecode(item) for item in raw.split(b"\n")]
    if spellings[-1] == "":
        spellings.pop()
    if any(not spelling for spelling in spellings):
        raise ValueError("dependency report contains an empty path")
    return dependency_records(spellings, root)


def read_dependencies(index, base_key, root):
    try:
        with Path(index).open("rb") as stream:
            raw = stream.read(MAX_DEPENDENCY_INDEX_BYTES + 1)
        if len(raw) > MAX_DEPENDENCY_INDEX_BYTES:
            return None
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
    manifest = json.loads(Path(snapshot).read_bytes())
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


def copy_digest(source, target, *, allow_empty=False, limit=None):
    digest = hashlib.sha256()
    size = 0
    with open(source, "rb") as src, open(target, "wb") as dst:
        while chunk := src.read(1024 * 1024):
            size += len(chunk)
            if size > (MAX_OBJECT_BYTES if limit is None else limit):
                raise ValueError("cache payload exceeds limit")
            digest.update(chunk)
            dst.write(chunk)
    if size == 0 and not allow_empty:
        raise ValueError("empty cache object")
    return {"size": size, "sha256": digest.hexdigest()}


def temporary(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".incoming.", dir=path.parent)
    os.close(fd)
    return Path(name)


def restore(entry, output, key, *, stdout=None, stderr=None):
    staged = []
    admitted = False
    try:
        with open(str(entry) + ".json", "rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            return False
        metadata = json.loads(raw)
        if metadata.get("schema") != SCHEMA or metadata.get("key") != key:
            return False
        obj = temporary(output)
        staged.append(obj)
        expected_object = metadata.get("object")
        if not isinstance(expected_object, dict):
            return False
        mode = expected_object.get("mode")
        if type(mode) is not int or mode < 0 or mode > 0o777:
            return False
        copied_object = copy_digest(entry, obj)
        if copied_object != {key: expected_object.get(key) for key in ("size", "sha256")}:
            return False
        os.chmod(obj, mode)
        streams = {}
        for name in ("stdout", "stderr"):
            target = temporary(output)
            staged.append(target)
            source = Path(str(entry) + "." + name)
            copied = copy_digest(source, target, allow_empty=True, limit=MAX_DIAGNOSTIC_BYTES)
            if copied != metadata["streams"][name]:
                return False
            streams[name] = target
        # Verify the exact copied object AND both streams before any publication.
        os.replace(obj, output)
        admitted = True
        for name, destination in (("stderr", stderr), ("stdout", stdout)):
            destination = destination if destination is not None else getattr(sys, name).buffer
            with open(streams[name], "rb") as source:
                shutil.copyfileobj(source, destination, 1024 * 1024)
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
        obj = temporary(entry)
        staged.append(obj)
        mode = stat.S_IMODE(os.stat(output).st_mode) & 0o777
        object_digest = copy_digest(output, obj)
        if (stat.S_IMODE(os.stat(output).st_mode) & 0o777) != mode:
            return False
        metadata = {"schema": SCHEMA, "key": key,
                    "object": {**object_digest, "mode": mode}, "streams": {}}
        payloads = [(obj, entry)]
        for name, source in (("stdout", stdout), ("stderr", stderr)):
            target = temporary(entry)
            staged.append(target)
            if source is None:
                metadata["streams"][name] = {"size": 0, "sha256": hashlib.sha256(b"").hexdigest()}
            else:
                metadata["streams"][name] = copy_digest(source, target, allow_empty=True, limit=MAX_DIAGNOSTIC_BYTES)
            payloads.append((target, Path(str(entry) + "." + name)))
        stamp = temporary(Path(str(entry) + ".json"))
        staged.append(stamp)
        stamp.write_text(json.dumps(metadata))
        # Publish metadata last. Partial or racing generations fail validation.
        for source, target in payloads:
            os.replace(source, target)
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
        if operation == "dependency-key":
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
        elif operation == "restore":
            entry, output, key, *streams = arguments
            valid = restore(Path(entry), Path(output), key)
        elif operation == "publish":
            entry, output, key, *streams = arguments
            valid = publish(Path(entry), Path(output), key, *map(Path, streams))
        else:
            raise ValueError("unknown cache operation")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"object cache replay failed: {error}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if valid else 1)
