#!/usr/bin/env python3
"""Integrity and diagnostic replay for the opt-in object cache."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

SCHEMA = "elisac-stage1-object-integrity-v2"
MAX_OBJECT_BYTES = 2 * 1024**3
MAX_DIAGNOSTIC_BYTES = 64 * 1024**2


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
        if copy_digest(entry, obj) != metadata.get("object"):
            return False
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
        metadata = {"schema": SCHEMA, "key": key,
                    "object": copy_digest(output, obj), "streams": {}}
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
    operation, entry, output, key, *streams = sys.argv[1:]
    try:
        if operation == "restore":
            valid = restore(Path(entry), Path(output), key)
        elif operation == "publish":
            valid = publish(Path(entry), Path(output), key, *map(Path, streams))
        else:
            raise ValueError("unknown cache operation")
    except OSError as error:
        print(f"object cache replay failed: {error}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if valid else 1)
