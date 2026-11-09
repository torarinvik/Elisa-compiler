#!/usr/bin/env python3
"""Native-independent admission controls; no compiler builds or timings."""
import copy
import importlib.util
import json
import multiprocessing
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("shard", Path(__file__).with_name("stage1_shard_cache.py"))
shard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shard)


def process_worker(start, cache, ticket, root, writer, number):
    start.wait()
    root = Path(root)
    for _ in range(8):
        if writer:
            shard.publish(cache, ticket, root / "object", root / "stdout", root / "stderr")
        else:
            output = root / f"reader-{number}.o"
            if shard.restore(cache, ticket, output, root / f"reader-{number}.out", root / f"reader-{number}.err"):
                assert output.read_bytes() == (root / "object").read_bytes()


class CacheTestFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.options = {key: "none" for key in shard.FIELDS}
        self.options.update(target_triple="x86_64-unknown-linux-gnu", data_layout="e-p:64:64",
                            cpu="generic", features="", opt_pipeline="default<O2>", codegen_opt="0",
                            ownership_version="stable-name-v1", restriction_version="foreign-strip-v1",
                            producer_discovery_version="running-executable-v1",
                            llvm_discovery_version="dladdr-LLVMContextCreate-v1",
                            logical_shard=1, logical_shards=4, coverage_policy="none", pgo_policy="none",
                            resolved_output_policy={"normalized_codegen_args": [], "output_environment": {}})
        self.files = {}
        for name in ("snapshot", "producer", "llvm", "runtime", "profile", "object", "stdout", "stderr"):
            self.files[name] = self.root / name
            self.files[name].write_bytes((name + " contents").encode() if name not in ("stdout", "stderr") else b"")
        self.cache = self.root / "cache"
        self.ticket = self.prepare()
        self.output = self.root / "output.o"
        self.out = self.root / "out.log"
        self.err = self.root / "err.log"


    def prepare(self, options=None):
        return shard.prepare(self.files["snapshot"], self.files["producer"], self.files["llvm"],
                             self.files["runtime"], options or self.options, [self.files["profile"]])


    def publish(self):
        return shard.publish(self.cache, self.ticket, self.files["object"], self.files["stdout"], self.files["stderr"])


    def restore(self):
        return shard.restore(self.cache, self.ticket, self.output, self.out, self.err)



__all__ = [name for name in globals() if not name.startswith("__")]
