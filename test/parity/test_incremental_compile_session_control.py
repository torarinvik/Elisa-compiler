"""Unit-test request log boundaries without claiming a Stage1 runtime gate."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class CompileSessionDiagnosticBoundaryTest(unittest.TestCase):
    def capture(self, previous: str, current: str) -> str:
        source = Path(__file__).with_name("incremental_compile_session_control.sh").read_text()
        start = source.index("send_compile() {")
        end = source.index("\ncompare_object() {", start)
        with tempfile.TemporaryDirectory(prefix="compile-session-log-") as folder:
            work = Path(folder)
            (work / "send_compile.sh").write_text(source[start:end])
            (work / "server.log").write_text(previous)
            script = r'''
set -euo pipefail
SERVER_LOG="$WORK/server.log"
exec 3> "$WORK/requests"
fail() { echo "$*" >&2; exit 1; }
read_status() { printf '%s' "$CURRENT_LOG" >> "$SERVER_LOG"; }
source "$WORK/send_compile.sh"
send_compile 1 edit
cat "$LAST_REQUEST_STDERR"
'''
            result = subprocess.run(
                ["bash", "-c", script],
                env={**os.environ, "WORK": folder, "CURRENT_LOG": current},
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_excludes_previous_backend_and_includes_current_backend(self):
        previous = "incremental-ga-cache: session=miss\nprevious backend warning\n"
        current = "current semantic error\nincremental-ga-cache: session=edit\ncurrent backend warning\n"
        self.assertEqual(self.capture(previous, current), "current semantic error\ncurrent backend warning\n")

    def test_first_request_preserves_diagnostics_after_report(self):
        current = "frontend warning\nincremental-ga-cache: session=edit\nbackend error\n"
        self.assertEqual(self.capture("", current), "frontend warning\nbackend error\n")

    def test_empty_current_request_does_not_inherit_previous_error(self):
        previous = "incremental-ga-cache: session=miss\nprevious backend error\n"
        self.assertEqual(self.capture(previous, "incremental-ga-cache: session=edit\n"), "")


if __name__ == "__main__":
    unittest.main()
