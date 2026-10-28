#!/usr/bin/env python3
"""Keep debug fixture separately; unnamed-only module exercises positive cases."""
from pathlib import Path
import re
p=Path("test/parity/stage1_table_unroll_fixture.ll")
s=p.read_text()
Path("test/parity/stage1_table_unroll_debug_fixture.ll").write_text(s)
s=re.sub(r"^define i64 @debug\(\) !dbg !11 \{.*?^}\n", "", s, flags=re.M|re.S)
s=re.sub(r"^!(?:llvm\.dbg\.cu|llvm\.module\.flags|1[0-6]) = .*\n", "", s, flags=re.M)
p.write_text(s)
