#!/usr/bin/env python3
"""Cache integrity regression tests."""
import unittest

from stage1_object_cache_identity_tests import ObjectCacheIdentityTests
from stage1_object_cache_publication_tests import ObjectCachePublicationTests
from stage1_object_cache_restore_tests import ObjectCacheRestoreTests
from stage1_object_cache_dependency_tests import ObjectCacheDependencyTests


if __name__ == "__main__":
    unittest.main()
