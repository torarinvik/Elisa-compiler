#!/usr/bin/env python3
"""Exact preoptimization shard tickets and atomic object/diagnostic bundles.

The native caller must attest that producer/loaded_llvm identify its running
images, verify/restrict the snapshot, and use the SAME per-shard cold pipeline.
On Linux, the caller may pass inherited `/proc/self/fd/N` paths; this helper
preserves those paths so every revalidation reads the same open file description.
A hit precedes optimization/emission.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from stage1_shard_batch import ShardBatchInvocation, mapped_image_pins, batch_fields
from stage1_shard_serialization import canonical, write_json_atomic, write_text_atomic

SCHEMA = "elisac-preopt-shard-cache-v2"
MAX_BYTES = 2 * 1024**3
MAX_STREAM = 64 * 1024**2
FIELDS = {
    "target_triple", "data_layout", "cpu", "features", "opt_pipeline",
    "codegen_opt", "relocation_model", "code_model", "debug_policy",
    "contract_policy", "ownership_version", "restriction_version",
    "logical_shard", "logical_shards", "producer_discovery_version", "llvm_discovery_version", "coverage_policy", "pgo_policy", "resolved_output_policy",
}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def artifact_path(path):
    """Resolve normal files, but preserve inherited Linux fd pins verbatim."""
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    prefix = "/proc/self/fd/"
    if raw.startswith(prefix):
        suffix = raw[len(prefix):]
        if not suffix.isascii() or not suffix.isdecimal() or str(int(suffix)) != suffix:
            raise ValueError("invalid inherited artifact descriptor path")
        return Path(raw)
    return Path(raw).resolve(strict=True)


def fingerprint(path, *, allow_empty=False, limit=MAX_BYTES):
    path = artifact_path(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("artifact is not a regular file")
        h = hashlib.sha256()
        size = 0
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > limit:
                raise ValueError("artifact exceeds limit")
            h.update(block)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("artifact changed while reading")
    if not size and not allow_empty:
        raise ValueError("empty artifact")
    return {"sha256": h.hexdigest(), "size": size}


def validate_options(options):
    if not isinstance(options, dict) or set(options) != FIELDS:
        raise ValueError("incomplete or unknown shard recipe fields")
    for key in FIELDS - {"logical_shard", "logical_shards", "resolved_output_policy"}:
        if not isinstance(options[key], str):
            raise ValueError("recipe fields must be resolved strings")
    for key in ("target_triple", "data_layout", "ownership_version", "restriction_version"):
        if not options[key]:
            raise ValueError("missing resolved recipe identity")
    policy = options["resolved_output_policy"]
    if not isinstance(policy, dict) or set(policy) != {"normalized_codegen_args", "output_environment"}:
        raise ValueError("incomplete resolved output policy")
    args, env = policy["normalized_codegen_args"], policy["output_environment"]
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("resolved codegen arguments must be strings")
    if not isinstance(env, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
        raise ValueError("resolved output environment must be string map")
    if options["coverage_policy"] not in ("none", "instrument") or options["pgo_policy"] not in ("none", "generate", "use"):
        raise ValueError("unsupported instrumentation policy")
    count, shard = options["logical_shards"], options["logical_shard"]
    if type(count) is not int or type(shard) is not int or not 1 <= count <= 64 or not 0 <= shard < count:
        raise ValueError("invalid logical shard inventory")
    if options["producer_discovery_version"] != "running-executable-v1" or options["llvm_discovery_version"] != "dladdr-LLVMContextCreate-v1":
        raise ValueError("unsupported native discovery contract")
    if options["opt_pipeline"] not in ("none", "default<O1>", "default<O2>", "default<O3>"):
        raise ValueError("unsupported per-shard optimization recipe")
    if options["codegen_opt"] not in ("0", "1", "2", "3"):
        raise ValueError("unsupported codegen level")


def ticket_key(ticket):
    return digest(canonical({"schema": SCHEMA, "recipe": ticket["recipe"], "snapshot": ticket["snapshot"]["identity"]}))


def prepare(snapshot, producer, loaded_llvm, runtime, options, profiles=()):
    validate_options(options)
    if options["pgo_policy"] == "use" and not profiles:
        raise ValueError("PGO use requires actual profile artifacts")
    pins = {}
    artifacts = {}
    for name, path in (("producer", producer), ("loaded_llvm", loaded_llvm), ("runtime", runtime)):
        pinned_path = artifact_path(path)
        pin = {"path": str(pinned_path), "identity": fingerprint(pinned_path)}
        pins[name] = pin
        artifacts[name] = pin["identity"]
    profile_pins = []
    for path in profiles:
        pinned_path = artifact_path(path)
        profile_pins.append({"path": str(pinned_path), "identity": fingerprint(pinned_path)})
    pins["profiles"] = profile_pins
    artifacts["profiles"] = [pin["identity"] for pin in profile_pins]
    ticket = {"schema": SCHEMA, "pins": pins, "recipe": {"options": dict(options), "artifacts": artifacts},
              "snapshot": {"path": str(Path(snapshot).resolve(strict=True)), "identity": fingerprint(snapshot)}}
    ticket["key"] = ticket_key(ticket)
    validate_ticket(ticket)
    return ticket


def validate_ticket(ticket):
    if not isinstance(ticket, dict):
        raise ValueError("shard ticket must be a map")
    if ticket.get("schema") != SCHEMA or ticket.get("key") != ticket_key(ticket):
        raise ValueError("invalid shard ticket")
    validate_options(ticket["recipe"]["options"])
    for name in ("producer", "loaded_llvm", "runtime"):
        pin = ticket["pins"][name]
        if fingerprint(pin["path"]) != pin["identity"] or pin["identity"] != ticket["recipe"]["artifacts"][name]:
            raise ValueError("producer recipe artifact changed")
    profiles = ticket["pins"]["profiles"]
    if [pin["identity"] for pin in profiles] != ticket["recipe"]["artifacts"]["profiles"]:
        raise ValueError("profile recipe mismatch")
    for pin in profiles:
        if fingerprint(pin["path"]) != pin["identity"]:
            raise ValueError("profile artifact changed")
    if fingerprint(ticket["snapshot"]["path"]) != ticket["snapshot"]["identity"]:
        raise ValueError("restricted snapshot changed")


@contextlib.contextmanager
def locked(cache, key, exclusive):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / (key + ".lock")).open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield cache / key


def verify_bundle(entry, ticket):
    manifest = read_bundle_manifest(entry, ticket)
    if not manifest:
        return False
    try:
        for name in ("object", "stdout", "stderr"):
            if fingerprint(entry / name, allow_empty=name != "object", limit=MAX_BYTES if name == "object" else MAX_STREAM) != manifest[name]:
                return False
        return manifest
    except (OSError, ValueError, TypeError, KeyError):
        return False


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def open_private_exclusive(path):
    """Create a binary file that stays private when atomically published."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        # O_CREAT's mode is umask-filtered. These files can be renamed into the
        # caller's output paths, so retain mkstemp's private mode explicitly.
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, "wb")
    except BaseException:
        os.close(fd)
        Path(path).unlink(missing_ok=True)
        raise


def synced_copy(source, target, limit=MAX_BYTES):
    with Path(source).open("rb") as src, Path(target).open("xb") as dst:
        size = 0
        while block := src.read(1024 * 1024):
            size += len(block)
            if size > limit:
                raise ValueError("copied artifact exceeds limit")
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())


def copy_fingerprint(source, target, *, allow_empty=False, limit=MAX_BYTES):
    """Copy an exact regular-file snapshot while hashing the bytes read."""
    source = Path(source).resolve(strict=True)
    digest_state = hashlib.sha256()
    size = 0
    with source.open("rb") as src:
        before = os.fstat(src.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("artifact is not a regular file")
        with open_private_exclusive(target) as dst:
            while block := src.read(1024 * 1024):
                size += len(block)
                if size > limit:
                    raise ValueError("copied artifact exceeds limit")
                digest_state.update(block)
                dst.write(block)
            dst.flush()
            os.fsync(dst.fileno())
        after = os.fstat(src.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("artifact changed while copying")
    if not size and not allow_empty:
        raise ValueError("empty artifact")
    return {"sha256": digest_state.hexdigest(), "size": size}


def copy_fingerprint_sibling(source, target, *, allow_empty=False, limit=MAX_BYTES):
    """Copy to one exclusive random sibling, returning its path and identity."""
    target = Path(target)
    for _ in range(16):
        temporary = target.with_name(f".{target.name}.incoming-{os.urandom(16).hex()}")
        try:
            identity = copy_fingerprint(source, temporary, allow_empty=allow_empty, limit=limit)
        except FileExistsError:
            continue
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return temporary, identity
    raise FileExistsError(f"could not allocate a unique staging path beside {target}")


def ensure_parent_directories(parent, created):
    parent = Path(parent)
    missing = []
    while not parent.exists():
        missing.append(parent)
        if parent == parent.parent:
            break
        parent = parent.parent
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            if not directory.is_dir():
                raise
        else:
            created.append(directory)


def remove_empty_directories(directories):
    for directory in reversed(directories):
        try:
            directory.rmdir()
        except OSError:
            pass


def read_bundle_manifest(entry, ticket):
    try:
        with (entry / "manifest.json").open("rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            return False
        manifest = json.loads(raw)
        if not isinstance(manifest, dict) or set(manifest) != {
            "schema", "key", "recipe_digest", "snapshot", "object", "stdout", "stderr", "modes"
        }:
            return False
        if manifest["schema"] != SCHEMA or manifest["key"] != ticket["key"]:
            return False
        if manifest["recipe_digest"] != digest(canonical(ticket["recipe"])) or manifest["snapshot"] != ticket["snapshot"]["identity"]:
            return False
        modes = manifest["modes"]
        if not isinstance(modes, dict) or set(modes) != {"object", "stdout", "stderr"}:
            return False
        if any(type(mode) is not int or mode < 0 or mode > 0o777 for mode in modes.values()):
            return False
        for name, limit, allow_empty in (("object", MAX_BYTES, False), ("stdout", MAX_STREAM, True), ("stderr", MAX_STREAM, True)):
            identity = manifest[name]
            if not isinstance(identity, dict) or set(identity) != {"sha256", "size"}:
                return False
            checksum, size = identity["sha256"], identity["size"]
            if not isinstance(checksum, str) or len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
                return False
            if type(size) is not int or size < (0 if allow_empty else 1) or size > limit:
                return False
        return manifest
    except (OSError, ValueError, TypeError, KeyError):
        return False


def publish(cache, ticket, obj, stdout, stderr, *, _validator=validate_ticket):
    _validator(ticket)
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".incoming-", dir=cache))
    retired = None
    try:
        manifest = {"schema": SCHEMA, "key": ticket["key"], "recipe_digest": digest(canonical(ticket["recipe"])), "snapshot": ticket["snapshot"]["identity"], "modes": {}}
        for name, source in (("object", obj), ("stdout", stdout), ("stderr", stderr)):
            limit = MAX_BYTES if name == "object" else MAX_STREAM
            source_mode = stat.S_IMODE(os.stat(source).st_mode) & 0o777
            identity = fingerprint(source, allow_empty=name != "object", limit=limit)
            synced_copy(source, stage / name, limit)
            manifest[name] = fingerprint(stage / name, allow_empty=name != "object", limit=limit)
            if identity != manifest[name] or fingerprint(source, allow_empty=name != "object", limit=limit) != identity:
                raise ValueError("emitted payload changed during publication")
            if (stat.S_IMODE(os.stat(source).st_mode) & 0o777) != source_mode:
                raise ValueError("emitted payload mode changed during publication")
            manifest["modes"][name] = source_mode
        with (stage / "manifest.json").open("xb") as stream:
            stream.write(canonical(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(stage)
        _validator(ticket)  # Publication never changes the compiled tuple.
        with locked(cache, ticket["key"], True) as entry:
            if verify_bundle(entry, ticket):
                return True  # Immutable first valid publication wins.
            if entry.exists():
                retired = Path(tempfile.mkdtemp(prefix=".retired-", dir=cache))
                retired.rmdir()
                os.replace(entry, retired)
            os.replace(stage, entry)  # Readers see one complete generation.
            sync_directory(cache)
        return True
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if retired:
            shutil.rmtree(retired, ignore_errors=True)


def restore(cache, ticket, output, stdout, stderr, *, _validator=validate_ticket, _receipt=None,
            _verify_copies=True, _deferred_staged=None, _deferred_directories=None):
    _validator(ticket)
    if len({str(Path(path).resolve()) for path in (output, stdout, stderr)}) != 3:
        raise ValueError("restore output paths must be distinct")
    if (_deferred_staged is None) != (_deferred_directories is None):
        raise ValueError("deferred restore requires both staging result lists")
    staged = []
    created_directories = []
    committed = False
    transferred = False
    try:
        with locked(cache, ticket["key"], False) as entry:
            manifest = read_bundle_manifest(entry, ticket)
            if not manifest:
                return False
            for name, target in (("object", output), ("stdout", stdout), ("stderr", stderr)):
                target = Path(target)
                ensure_parent_directories(target.parent, created_directories)
                limit = MAX_BYTES if name == "object" else MAX_STREAM
                temporary, copied = copy_fingerprint_sibling(
                    entry / name, target, allow_empty=name != "object", limit=limit
                )
                staged.append((temporary, target))
                if copied != manifest[name]:
                    return False
                if _verify_copies and fingerprint(temporary, allow_empty=name != "object", limit=limit) != manifest[name]:
                    return False
            _validator(ticket)
            if _deferred_staged is not None:
                _deferred_staged.extend(source for source, _ in staged)
                _deferred_directories.extend(created_directories)
                transferred = True
                if _receipt is not None:
                    _receipt.update({name: dict(manifest[name]) for name in ("object", "stdout", "stderr")})
                    _receipt["modes"] = dict(manifest["modes"])
                return True
            # Object commits last; publication errors are fatal, never a cold retry
            # following partially published diagnostics.
            for index in (1, 2, 0):
                name = ("object", "stdout", "stderr")[index]
                os.chmod(staged[index][0], manifest["modes"][name])
                os.replace(*staged[index])
            committed = True
            if _receipt is not None:
                _receipt.update({name: dict(manifest[name]) for name in ("object", "stdout", "stderr")})
                _receipt["modes"] = dict(manifest["modes"])
            return True
    finally:
        if not transferred and not committed:
            for source, _ in staged:
                source.unlink(missing_ok=True)
            remove_empty_directories(created_directories)


class BatchInvocation(ShardBatchInvocation):
    """Bind batch operations to the same admission and publication routines."""
    def __init__(self, cache, producer, loaded_llvm, runtime, profiles=(), mapped_image_digests=None):
        super().__init__(globals(), cache, producer, loaded_llvm, runtime, profiles, mapped_image_digests)


def complete_restore_request(request):
    batch_fields(request)
    if not isinstance(request["shards"], list):
        raise ValueError("invalid batch request")
    count = len(request["shards"])
    if not 1 <= count <= 64:
        raise ValueError("invalid complete logical shard inventory")
    destinations = set()
    common_options = None
    for index, item in enumerate(request["shards"]):
        if set(item) != {"snapshot", "options", "object", "stdout", "stderr"}:
            raise ValueError("invalid batch restore shard")
        validate_options(item["options"])
        resolved_common = {key: value for key, value in item["options"].items() if key != "logical_shard"}
        if common_options is None:
            common_options = resolved_common
        elif common_options != resolved_common:
            raise ValueError("batch shards have inconsistent output recipes")
        if item["options"]["logical_shards"] != count or item["options"]["logical_shard"] != index:
            raise ValueError("shard inventory must be complete, contiguous and ordered")
        for field in ("object", "stdout", "stderr"):
            path = str(Path(item[field]).resolve())
            if path in destinations:
                raise ValueError("shards share output targets")
            destinations.add(path)
    return count


def status_text(result):
    if not isinstance(result, dict) or set(result) != {"schema", "shards", "metrics"} or result["schema"] != SCHEMA:
        raise ValueError("invalid restore result schema")
    records = result["shards"]
    if not isinstance(records, list) or not 1 <= len(records) <= 64:
        raise ValueError("invalid restore status count")
    bits = []
    for index, record in enumerate(records):
        if set(record) != {"ticket", "hit"} or type(record["hit"]) is not bool:
            raise ValueError("invalid restore status record")
        ticket = record["ticket"]
        if not isinstance(ticket, dict) or ticket.get("schema") != SCHEMA or ticket.get("key") != ticket_key(ticket):
            raise ValueError("invalid restore status ticket")
        options = ticket["recipe"]["options"]
        validate_options(options)
        if options["logical_shard"] != index or options["logical_shards"] != len(records):
            raise ValueError("invalid restore status order")
        bits.append("H" if record["hit"] else "M")
    return f"ELISA_PREOPT_SHARD_STATUS_V1\n{len(records)}\n{''.join(bits)}\n"


def publish_restore_result(request, result):
    complete_restore_request(request)
    status_text(result)
    if len(result["shards"]) != len(request["shards"]):
        raise ValueError("restore result inventory mismatch")
    publications = []
    for item, record in zip(request["shards"], result["shards"]):
        ticket = record["ticket"]
        if ticket.get("mapped_image_digests") != request.get("mapped_image_digests"):
            raise ValueError("restore result mapped image pins differ from original request")
        if ticket["recipe"]["options"] != item["options"] or ticket["snapshot"]["path"] != str(Path(item["snapshot"]).resolve(strict=True)):
            raise ValueError("restore result differs from original admitted request")
        if not record["hit"]:
            publications.append({"ticket": ticket, "object": item["object"], "stdout": item["stdout"], "stderr": item["stderr"]})
    # The original pins, not freshly guessed keys, authorize emitted misses.
    with BatchInvocation(request["cache"], request["producer"], request["loaded_llvm"], request["runtime"], request["profiles"], request.get("mapped_image_digests")) as batch:
        for record in result["shards"]:
            batch.validate(record["ticket"])
        for item in publications:
            batch.publish(item["ticket"], item["object"], item["stdout"], item["stderr"])
        metrics = batch.finish()
    return {"schema": SCHEMA, "published_misses": len(publications), "metrics": metrics}

def batch_request(operation, request):
    batch_fields(request)
    if not isinstance(request["shards"], list) or len(request["shards"]) > 64:
        raise ValueError("invalid bounded batch request")
    if operation == "batch-restore":
        complete_restore_request(request)
    outputs = []
    with BatchInvocation(request["cache"], request["producer"], request["loaded_llvm"], request["runtime"], request["profiles"], request.get("mapped_image_digests")) as batch:
        for item in request["shards"]:
            if operation == "batch-restore":
                if set(item) != {"snapshot", "options", "object", "stdout", "stderr"}:
                    raise ValueError("invalid batch restore shard")
                ticket = batch.prepare(item["snapshot"], item["options"])
                hit = batch.restore(ticket, item["object"], item["stdout"], item["stderr"])
                outputs.append({"ticket": ticket, "hit": hit})
            else:
                if set(item) != {"ticket", "object", "stdout", "stderr"}:
                    raise ValueError("invalid batch publication shard")
                batch.publish(item["ticket"], item["object"], item["stdout"], item["stderr"])
        metrics = batch.finish()
    return {"schema": SCHEMA, "shards": outputs, "metrics": metrics}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "restore", "publish", "batch-restore", "batch-publish", "batch-publish-result"))
    parser.add_argument("--ticket")
    parser.add_argument("--result")
    parser.add_argument("--restore-result")
    parser.add_argument("--status")
    parser.add_argument("--request")
    parser.add_argument("--cache")
    parser.add_argument("--object")
    parser.add_argument("--stdout")
    parser.add_argument("--stderr")
    args = parser.parse_args()
    try:
        if args.operation.startswith("batch-"):
            if args.status and args.operation != "batch-restore":
                raise ValueError("status manifest is only for batch restoration")
            if not args.request or not args.result:
                parser.error("batch operations require --request --result")
            paths = [args.request, args.result]
            if args.status:
                paths.append(args.status)
            if args.restore_result:
                paths.append(args.restore_result)
            if len({str(Path(path).resolve()) for path in paths}) != len(paths):
                raise ValueError("batch admission and result paths must be distinct")
            with open(args.request, "rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("oversized batch request")
            request = json.loads(raw)
            if args.operation == "batch-publish-result":
                if not args.restore_result or Path(args.restore_result).resolve() == Path(args.result).resolve():
                    raise ValueError("publication needs a distinct immutable restore result")
                with open(args.restore_result, "rb") as stream:
                    raw = stream.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError("oversized restore result")
                result = publish_restore_result(request, json.loads(raw))
            else:
                result = batch_request(args.operation, request)
            write_json_atomic(args.result, result)
            if args.status:
                if args.operation != "batch-restore":
                    raise ValueError("status manifest is only for batch restoration")
                write_text_atomic(args.status, status_text(result))
            return 1 if args.operation == "batch-restore" and result["metrics"]["misses"] else 0
        if not args.ticket:
            parser.error("single-shard operations require --ticket")
        if args.operation == "prepare":
            if not args.request:
                parser.error("prepare requires --request")
            with open(args.request, "rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("oversized preparation request")
            request = json.loads(raw)
            if set(request) != {"snapshot", "producer", "loaded_llvm", "runtime", "options", "profiles"}:
                raise ValueError("unknown or missing preparation inputs")
            ticket = prepare(**request)
            output = Path(args.ticket)
            output.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=output.name + ".incoming-", dir=output.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(canonical(ticket))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, output)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return 0
        if not all((args.cache, args.object, args.stdout, args.stderr)):
            parser.error("restore/publish require --cache --object --stdout --stderr")
        with open(args.ticket, "rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized shard ticket")
        ticket = json.loads(raw)
        action = restore if args.operation == "restore" else publish
        return 0 if action(args.cache, ticket, args.object, args.stdout, args.stderr) else 1
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"shard cache {args.operation} failed: {error}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
