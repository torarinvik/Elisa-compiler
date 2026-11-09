#!/usr/bin/env python3
"""Cache integrity regression tests."""
import unittest

from stage1_shard_cache_restore_tests import ShardCacheRestoreTests
from stage1_shard_cache_publication_tests import ShardCachePublicationTests
from stage1_shard_cache_batch_tests import ShardCacheBatchTests


if __name__ == "__main__":
    unittest.main()
