#!/usr/bin/env python3
"""Focused soundness and precision checks for the semantic parallel audit."""
import unittest

from semantic_parallel_audit_borrow_tests import SemanticParallelBorrowTests
from semantic_parallel_audit_flow_tests import SemanticParallelFlowTests
from semantic_parallel_audit_dispatch_tests import SemanticParallelDispatchTests
from semantic_parallel_audit_calls_tests import SemanticParallelCallsTests


if __name__ == "__main__":
    unittest.main()
