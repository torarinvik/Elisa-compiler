import tempfile
import unittest
from pathlib import Path

from compiler_rebuild_profile import go_compiler_package


class GoCompilerPackageTest(unittest.TestCase):
    def test_direct_and_response_file_arguments(self):
        self.assertEqual(go_compiler_package("compile -p example/semantic -o output"), "example/semantic")
        with tempfile.TemporaryDirectory(prefix="go args ") as directory:
            response = Path(directory) / "args with spaces"
            response.write_text('-o\n"secret path"\n-p\n"example/semantic"\n', encoding="utf-8")
            self.assertEqual(go_compiler_package(f"/go/tool/compile @{response}"), "example/semantic")
            response.write_text('-p\n"not a package"\n', encoding="utf-8")
            self.assertIsNone(go_compiler_package(f"compile @{response}"))
        self.assertIsNone(go_compiler_package("compile @/missing/response"))


if __name__ == "__main__":
    unittest.main()
