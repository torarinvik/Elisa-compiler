#!/usr/bin/env python3
"""Keep debug fixture separately; unnamed-only module exercises positive cases."""
from pathlib import Path
import re
p=Path("test/parity/stage1_table_unroll_fixture.ll")
s=p.read_text()
Path("test/parity/stage1_table_unroll_debug_fixture.ll").write_text(s)
s=re.sub(r"^define i64 @debug\(\) !dbg !11 \{.*?^}\n", "", s, flags=re.M|re.S)
# Keep the loop-metadata case only in the saved debug fixture. The unroller's
# module-wide preflight intentionally declines instruction metadata, so leaving
# this function in the positive fixture prevents every positive loop from being
# attempted.
s=re.sub(r"^define i64 @loop_metadata\(\).*?^}\n", "", s, flags=re.M|re.S)
s=re.sub(r"^!(?:0|1|llvm\.dbg\.cu|llvm\.module\.flags|1[0-6]) = .*\n", "", s, flags=re.M)
s=s.replace("define i64 @positive()", "define range(i64 0, 512) i64 @positive()", 1)
p.write_text(s)
