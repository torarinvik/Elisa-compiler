"""Checks for source-bound parity smoke case discovery."""
from pathlib import Path
import tempfile
import unittest

from parity_smoke_source import parity_smoke_inputs, read_parity_smoke_source


class ParitySmokeSourceTests(unittest.TestCase):
    def test_sourced_cases_are_included_only_when_referenced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            main = root / "smoke.sh"
            case = root / "cases.sh"
            case.write_text("fixture marker\n")
            main.write_text('source "$REPO_ROOT/test/parity/cases.sh"\n')
            self.assertIn("fixture marker", read_parity_smoke_source(main))
            self.assertEqual(parity_smoke_inputs(main), [main, case])
            main.write_text("# source omitted\n")
            self.assertNotIn("fixture marker", read_parity_smoke_source(main))

    def test_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            main = root / "smoke.sh"
            case = root / "cases.sh"
            main.write_text('source "$ROOT/test/parity/cases.sh"\n')
            case.write_text('source "$ROOT/test/parity/smoke.sh"\n')
            with self.assertRaisesRegex(ValueError, "cyclic"):
                parity_smoke_inputs(main)

    def test_python_driver_includes_imported_case_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            main = root / "smoke.sh"
            driver = root / "unsafe_grant_scope_cases.py"
            cases = root / "unsafe_grant_alias_cases.py"
            main.write_text('python3 "$REPO_ROOT/test/parity/unsafe_grant_scope_cases.py"\n')
            driver.write_text('from unsafe_grant_alias_cases import CASES\n')
            cases.write_text('CASES = {"marker": None}\n')
            self.assertEqual(parity_smoke_inputs(main), [main, driver, cases])
            self.assertIn('"marker"', read_parity_smoke_source(main))


if __name__ == "__main__":
    unittest.main()
