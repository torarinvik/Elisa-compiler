#!/usr/bin/env python3
"""Exact preoptimization shard tickets and atomic object/diagnostic bundles.

The backend must attest loaded_llvm is the loaded library, verify/restrict the
snapshot, and use the SAME per-shard cold pipeline. This helper does not infer
those facts from a caller-supplied path. A hit precedes optimization/emission.
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

SCHEMA = "elisac-preopt-shard-cache-v2"
MAX_BYTES = 2 * 1024**3
MAX_STREAM = 64 * 1024**2
FIELDS = {
    "target_triple", "data_layout", "cpu", "features", "opt_pipeline",
    "codegen_opt", "relocation_model", "code_model", "debug_policy",
    "contract_policy", "ownership_version", "restriction_version",
    "logical_shard", "logical_shards", "producer_discovery_version", "llvm_discovery_version", "coverage_policy", "pgo_policy", "resolved_output_policy",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def fingerprint(path, *, allow_empty=False, limit=MAX_BYTES):
    path = Path(path).resolve(strict=True)
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
        pin = {"path": str(Path(path).resolve(strict=True)), "identity": fingerprint(path)}
        pins[name] = pin
        artifacts[name] = pin["identity"]
    profile_pins = [{"path": str(Path(path).resolve(strict=True)), "identity": fingerprint(path)} for path in profiles]
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



def mapped_image_pins(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"producer", "loaded_llvm"}:
        raise ValueError("invalid mapped image digest fields")
    for digest_hex in value.values():
        if not isinstance(digest_hex, str) or len(digest_hex) != 64 or any(c not in "0123456789abcdef" for c in digest_hex):
            raise ValueError("invalid mapped image SHA256")
    return dict(value)


def batch_fields(request):
    fields = {"cache", "producer", "loaded_llvm", "runtime", "profiles", "shards"}
    if not isinstance(request, dict) or set(request) not in (fields, fields | {"mapped_image_digests"}):
        raise ValueError("invalid batch request fields")
    if "mapped_image_digests" in request and request["mapped_image_digests"] is None:
        raise ValueError("mapped image digests must be a complete map")
    return mapped_image_pins(request.get("mapped_image_digests"))


class BatchInvocation:
    """One-process shared artifact attestation; no external supplied digest cache.

    Stage all hits/publications privately. finish() rehashes shared artifacts
    once, then commits. Context exit without finish discards staged work.
    """
    def __init__(self, cache, producer, loaded_llvm, runtime, profiles=(), mapped_image_digests=None):
        self.mapped_image_digests = mapped_image_pins(mapped_image_digests)
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix=".batch-", dir=self.cache))
        self.metrics = {"shared_artifact_reads": 0, "snapshot_reads": 0, "hits": 0, "misses": 0}
        self.paths = {"producer": producer, "loaded_llvm": loaded_llvm, "runtime": runtime}
        self.profile_paths = tuple(profiles)
        self.closed = False
        try:
            self.pins, self.artifacts = self._read_shared()
        except BaseException:
            shutil.rmtree(self.work, ignore_errors=True)
            self.closed = True
            raise
        self.admitted_snapshots = {}
        self.admitted_tickets = {}
        self.prepared = []
        self.outputs = []
        self.publications = []
        self.finished = False

    def _open(self):
        if self.closed or self.finished:
            raise ValueError("batch invocation is closed or finalized")

    def _shared(self, path):
        self.metrics["shared_artifact_reads"] += 1
        return {"path": str(Path(path).resolve(strict=True)), "identity": fingerprint(path)}

    def _read_shared(self):
        pins = {name: self._shared(path) for name, path in self.paths.items()}
        pins["profiles"] = [self._shared(path) for path in self.profile_paths]
        artifacts = {name: pins[name]["identity"] for name in self.paths}
        artifacts["profiles"] = [pin["identity"] for pin in pins["profiles"]]
        if self.mapped_image_digests is not None:
            for name, expected in self.mapped_image_digests.items():
                if artifacts[name]["sha256"] != expected:
                    raise ValueError("actual file differs from verified mapped image: " + name)
        return pins, artifacts

    def _snapshot(self, path):
        self.metrics["snapshot_reads"] += 1
        return fingerprint(path)

    def _admit_snapshot(self, path):
        path = str(Path(path).resolve(strict=True))
        if path not in self.admitted_snapshots:
            self.admitted_snapshots[path] = self._snapshot(path)
        return dict(self.admitted_snapshots[path])

    def prepare(self, snapshot, options):
        self._open()
        validate_options(options)
        if options["pgo_policy"] == "use" and not self.profile_paths:
            raise ValueError("PGO use requires actual profile artifacts")
        ticket = {"schema": SCHEMA, "pins": self.pins, "recipe": {"options": dict(options), "artifacts": self.artifacts},
                  "snapshot": {"path": str(Path(snapshot).resolve(strict=True)), "identity": self._admit_snapshot(snapshot)}}
        if self.mapped_image_digests is not None:
            ticket["mapped_image_digests"] = dict(self.mapped_image_digests)
        ticket["key"] = ticket_key(ticket)
        self.validate(ticket)
        self.prepared.append(ticket)
        return ticket

    def validate(self, ticket):
        self._open()
        if not isinstance(ticket, dict):
            raise ValueError("invalid batch shard ticket")
        if ticket.get("mapped_image_digests") != self.mapped_image_digests:
            raise ValueError("ticket mapped image attestation mismatch")
        if not isinstance(ticket, dict) or ticket.get("schema") != SCHEMA or ticket.get("key") != ticket_key(ticket):
            raise ValueError("invalid batch shard ticket")
        validate_options(ticket["recipe"]["options"])
        if ticket["pins"] != self.pins or ticket["recipe"]["artifacts"] != self.artifacts:
            raise ValueError("batch shared artifact identity mismatch")
        snapshot = ticket["snapshot"]
        path = str(Path(snapshot["path"]).resolve(strict=True))
        if path != snapshot["path"] or self._admit_snapshot(path) != snapshot["identity"]:
            raise ValueError("batch restricted snapshot admission mismatch")
        exact = canonical(ticket)
        previous = self.admitted_tickets.get(ticket["key"])
        if previous is not None and previous != exact:
            raise ValueError("differing ticket reuses admitted key")
        self.admitted_tickets[ticket["key"]] = exact

    def restore(self, ticket, output, stdout, stderr):
        self._open()
        targets = [Path(path) for path in (output, stdout, stderr)]
        if len({str(path.resolve()) for path in targets}) != 3:
            raise ValueError("batch output paths must be distinct")
        previous = {str(path.resolve()) for _, _, paths, _, _ in self.outputs for path in paths}
        if previous.intersection(str(path.resolve()) for path in targets):
            raise ValueError("batch shards share output paths")
        staged = []
        created_directories = []
        retained = False
        try:
            expected = {}
            # Defer restore's atomic commit so finish() can validate every hit and
            # publish all batch outputs together. The restore helper writes directly
            # to unique destination-side siblings; misses create no output files.
            hit = restore(
                self.cache, ticket, *targets, _validator=self.validate, _receipt=expected,
                _verify_copies=False, _deferred_staged=staged,
                _deferred_directories=created_directories,
            )
            if hit:
                self.outputs.append((ticket, staged, targets, expected, created_directories))
                retained = True
            self.metrics["hits" if hit else "misses"] += 1
            return hit
        finally:
            if not retained:
                for path in staged:
                    path.unlink(missing_ok=True)
                remove_empty_directories(created_directories)

    def publish(self, ticket, obj, stdout, stderr):
        self._open()
        # Prepare a complete verified bundle under the private invocation cache.
        publish(self.work / "publication", ticket, obj, stdout, stderr, _validator=self.validate)
        self.publications.append(ticket)

    def finish(self):
        self._open()
        # Snapshot admission can change independently of shared artifacts too.
        for ticket in self.prepared:
            self.validate(ticket)
        for ticket, staged, _, expected, _ in self.outputs:
            self.validate(ticket)
            for name, source in zip(("object", "stdout", "stderr"), staged):
                if fingerprint(source, allow_empty=name != "object", limit=MAX_BYTES if name == "object" else MAX_STREAM) != expected[name]:
                    raise ValueError("private restored hit changed before finalization")
        for ticket in self.publications:
            self.validate(ticket)
        for path, expected in self.admitted_snapshots.items():
            if self._snapshot(path) != expected:
                raise ValueError("batch restricted snapshot changed before finalization")
        current_pins, current_artifacts = self._read_shared()
        if current_pins != self.pins or current_artifacts != self.artifacts:
            raise ValueError("shared artifacts changed during batch")
        # Every hit has already been staged beside its destination and verified.
        # Only now publish cache generations and replace destinations.
        for ticket in self.publications:
            staged = self.work / "publication" / ticket["key"]
            retired = None
            with locked(self.cache, ticket["key"], True) as entry:
                if verify_bundle(entry, ticket):
                    continue
                if not verify_bundle(staged, ticket):
                    raise ValueError("private batch bundle corrupted")
                if entry.exists():
                    retired = Path(tempfile.mkdtemp(prefix=".retired-", dir=self.cache))
                    retired.rmdir()
                    os.replace(entry, retired)
                os.replace(staged, entry)
                sync_directory(self.cache)
            if retired:
                shutil.rmtree(retired, ignore_errors=True)
        # Cache publication may take long enough for another process to tamper
        # with an output-local staging path; attest again immediately before
        # the atomic renames.
        for _, staged, _, expected, _ in self.outputs:
            for name, source in zip(("object", "stdout", "stderr"), staged):
                if fingerprint(source, allow_empty=name != "object", limit=MAX_BYTES if name == "object" else MAX_STREAM) != expected[name]:
                    raise ValueError("private restored hit changed before destination commit")
        for _, staged, targets, expected, _ in self.outputs:
            for index in (1, 2, 0):
                name = ("object", "stdout", "stderr")[index]
                os.chmod(staged[index], expected["modes"][name])
                os.replace(staged[index], targets[index])
        self.finished = True
        return dict(self.metrics)

    def close(self):
        self.closed = True
        for _, staged, _, _, created_directories in self.outputs:
            for path in staged:
                path.unlink(missing_ok=True)
            remove_empty_directories(created_directories)
        shutil.rmtree(self.work, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()



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


def write_json_atomic(output, value):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=output.name + ".incoming-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_text_atomic(output, text):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=output.name + ".incoming-", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)

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
