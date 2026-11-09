"""Stage and atomically publish a batch of preoptimization shard results."""
import os
from pathlib import Path
import shutil
import tempfile


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


class ShardBatchInvocation:
    """One-process shared artifact attestation; no external supplied digest cache.

    Stage all hits/publications privately. finish() rehashes shared artifacts
    once, then commits. Context exit without finish discards staged work.
    """
    def __init__(self, services, cache, producer, loaded_llvm, runtime, profiles=(), mapped_image_digests=None):
        self._services = services
        self.mapped_image_digests = self._services['mapped_image_pins'](mapped_image_digests)
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
        pinned_path = self._services['artifact_path'](path)
        return {"path": str(pinned_path), "identity": self._services['fingerprint'](pinned_path)}

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
        return self._services['fingerprint'](path)

    def _admit_snapshot(self, path):
        path = str(Path(path).resolve(strict=True))
        if path not in self.admitted_snapshots:
            self.admitted_snapshots[path] = self._snapshot(path)
        return dict(self.admitted_snapshots[path])

    def prepare(self, snapshot, options):
        self._open()
        self._services['validate_options'](options)
        if options["pgo_policy"] == "use" and not self.profile_paths:
            raise ValueError("PGO use requires actual profile artifacts")
        ticket = {"schema": self._services['SCHEMA'], "pins": self.pins, "recipe": {"options": dict(options), "artifacts": self.artifacts},
                  "snapshot": {"path": str(Path(snapshot).resolve(strict=True)), "identity": self._admit_snapshot(snapshot)}}
        if self.mapped_image_digests is not None:
            ticket["mapped_image_digests"] = dict(self.mapped_image_digests)
        ticket["key"] = self._services['ticket_key'](ticket)
        self.validate(ticket)
        self.prepared.append(ticket)
        return ticket

    def validate(self, ticket):
        self._open()
        if not isinstance(ticket, dict):
            raise ValueError("invalid batch shard ticket")
        if ticket.get("mapped_image_digests") != self.mapped_image_digests:
            raise ValueError("ticket mapped image attestation mismatch")
        if not isinstance(ticket, dict) or ticket.get("schema") != self._services['SCHEMA'] or ticket.get("key") != self._services['ticket_key'](ticket):
            raise ValueError("invalid batch shard ticket")
        self._services['validate_options'](ticket["recipe"]["options"])
        if ticket["pins"] != self.pins or ticket["recipe"]["artifacts"] != self.artifacts:
            raise ValueError("batch shared artifact identity mismatch")
        snapshot = ticket["snapshot"]
        path = str(Path(snapshot["path"]).resolve(strict=True))
        if path != snapshot["path"] or self._admit_snapshot(path) != snapshot["identity"]:
            raise ValueError("batch restricted snapshot admission mismatch")
        exact = self._services['canonical'](ticket)
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
            hit = self._services['restore'](
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
                self._services['remove_empty_directories'](created_directories)

    def publish(self, ticket, obj, stdout, stderr):
        self._open()
        # Prepare a complete verified bundle under the private invocation cache.
        self._services['publish'](self.work / "publication", ticket, obj, stdout, stderr, _validator=self.validate)
        self.publications.append(ticket)

    def finish(self):
        self._open()
        # Snapshot admission can change independently of shared artifacts too.
        for ticket in self.prepared:
            self.validate(ticket)
        for ticket, staged, _, expected, _ in self.outputs:
            self.validate(ticket)
            for name, source in zip(("object", "stdout", "stderr"), staged):
                if self._services['fingerprint'](source, allow_empty=name != "object", limit=self._services['MAX_BYTES'] if name == "object" else self._services['MAX_STREAM']) != expected[name]:
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
            with self._services['locked'](self.cache, ticket["key"], True) as entry:
                if self._services['verify_bundle'](entry, ticket):
                    continue
                if not self._services['verify_bundle'](staged, ticket):
                    raise ValueError("private batch bundle corrupted")
                if entry.exists():
                    retired = Path(tempfile.mkdtemp(prefix=".retired-", dir=self.cache))
                    retired.rmdir()
                    os.replace(entry, retired)
                os.replace(staged, entry)
                self._services['sync_directory'](self.cache)
            if retired:
                shutil.rmtree(retired, ignore_errors=True)
        # Cache publication may take long enough for another process to tamper
        # with an output-local staging path; attest again immediately before
        # the atomic renames.
        for _, staged, _, expected, _ in self.outputs:
            for name, source in zip(("object", "stdout", "stderr"), staged):
                if self._services['fingerprint'](source, allow_empty=name != "object", limit=self._services['MAX_BYTES'] if name == "object" else self._services['MAX_STREAM']) != expected[name]:
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
            self._services['remove_empty_directories'](created_directories)
        shutil.rmtree(self.work, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

