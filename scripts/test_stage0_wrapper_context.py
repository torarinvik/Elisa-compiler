"""Regression tests for replaying recorded context in the Stage0 freshness wrapper."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage0_provenance


class Stage0WrapperContextTests(unittest.TestCase):
    def test_wrapper_replays_recorded_target_and_cgo_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "compiler"
            source = root / "src"
            binary = root / "bin" / "elisac"
            fake_bin = temporary_path / "bin"
            source.mkdir(parents=True)
            binary.parent.mkdir()
            fake_bin.mkdir()
            (root / "go.mod").write_text("module elisacore\n", encoding="utf-8")
            (source / "main.go").write_text("package main\n", encoding="utf-8")
            (source / "darwin.go").write_text("package main\n// darwin input\n", encoding="utf-8")
            (source / "linux.go").write_text("package main\n// linux input\n", encoding="utf-8")
            binary.write_bytes(b"unchanged fake compiler")
            binary.chmod(0o755)

            context = {key: "" for key in stage0_provenance.GO_ENV_CONTEXT_KEYS}
            context.update({
                "GOVERSION": "go1.25.0",
                "GOOS": "darwin",
                "GOARCH": "arm64",
                "GOHOSTOS": "darwin",
                "GOHOSTARCH": "arm64",
                "CGO_ENABLED": "1",
                "GOTOOLCHAIN": "local",
                "CC": "cc",
                "CXX": "c++",
                "AR": "ar",
                "PKG_CONFIG": "pkg-config",
                "CGO_CFLAGS": "-DRECORDED_STAGE0_CONTEXT=1",
            })
            go_environment = {**context, "GOROOT": "/fake/go/root"}

            def mocked_go(args, **kwargs):
                if args[1] == "list":
                    selected_file = "darwin.go" if context["GOOS"] == "darwin" else "linux.go"
                    package = {
                        "ImportPath": "elisacore/src",
                        "Dir": str(source),
                        "Module": {"Path": "elisacore", "Dir": str(root)},
                        "GoFiles": ["main.go", selected_file],
                    }
                    stdout = json.dumps(package)
                elif args[1] == "version":
                    stdout = (
                        f"{binary}: go1.25.0\n"
                        " path elisacore/src\n"
                        " mod elisacore (devel)\n"
                        " build -buildmode=exe\n"
                        " build -compiler=gc\n"
                    )
                else:
                    raise AssertionError(f"unexpected mocked Go command: {args}")
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

            with patch.object(stage0_provenance.subprocess, "run", side_effect=mocked_go):
                manifest = stage0_provenance.build_manifest(root, binary, environment=go_environment)
            stage0_provenance._write_manifest(binary, manifest)

            fake_go = fake_bin / "go"
            fake_go.write_text(textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                context = {json.dumps(context)}
                args = sys.argv[1:]
                if args[:2] == ["env", "-json"]:
                    values = {{
                        "GOFLAGS": "",
                        "GOWORK": os.environ.get("GOWORK", ""),
                        "GOROOT": "/fake/go/root",
                        **context,
                    }}
                    goenv = os.environ.get("GOENV", "")
                    if goenv and goenv != "off" and os.path.isfile(goenv):
                        with open(goenv, encoding="utf-8") as settings:
                            for line in settings:
                                key, separator, value = line.strip().partition("=")
                                if separator:
                                    values[key] = value.strip('"')
                    for key in context:
                        if key in os.environ:
                            values[key] = os.environ[key]
                    values["GOHOSTOS"] = "darwin"
                    values["GOHOSTARCH"] = "arm64"
                    print(json.dumps(values))
                elif args[:2] == ["list", "-deps"]:
                    selected = "darwin.go" if os.environ.get("GOOS") == "darwin" else "linux.go"
                    print(json.dumps({{
                        "ImportPath": "elisacore/src",
                        "Dir": {json.dumps(str(source))},
                        "Module": {{"Path": "elisacore", "Dir": {json.dumps(str(root))}}},
                        "GoFiles": ["main.go", selected],
                    }}))
                elif args[:2] == ["version", "-m"]:
                    print(f"{{args[2]}}: go1.25.0")
                    print(" path elisacore/src")
                    print(" mod elisacore (devel)")
                    print(" build -buildmode=exe")
                    print(" build -compiler=gc")
                else:
                    print("unexpected fake Go command: " + repr(args), file=sys.stderr)
                    sys.exit(2)
            """), encoding="utf-8")
            fake_go.chmod(0o755)

            checker = Path(__file__).resolve().parent / "assert_stage0_fresh.sh"
            inherited = {
                key: value
                for key, value in os.environ.items()
                if key not in stage0_provenance.GO_ENV_CONTEXT_KEYS
                and key not in {"GOFLAGS", "GOWORK", "ELISA_STAGE0_SOURCE_ROOT", "ELISA_ALLOW_STALE_STAGE0"}
            }
            inherited["PATH"] = str(fake_bin) + os.pathsep + os.environ.get("PATH", "")
            inherited["GOOS"] = "linux"
            inherited["GOARCH"] = "amd64"
            inherited["ELISA_STAGE0_SOURCE_ROOT"] = str(root)
            result = subprocess.run(
                ["bash", str(checker), str(binary)],
                check=False,
                capture_output=True,
                text=True,
                env=inherited,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

            # A persisted compiler override remains visible to freshness checks; the
            # wrapper must not hide it by forcing GOENV=off.
            goenv_file = temporary_path / "go.env"
            goenv_file.write_text('CC="different-current-cc"\n', encoding="utf-8")
            changed_toolchain = {**inherited, "GOENV": str(goenv_file)}
            result = subprocess.run(
                ["bash", str(checker), str(binary)],
                check=False,
                capture_output=True,
                text=True,
                env=changed_toolchain,
            )
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertIn("Go compiler build context", result.stderr)


if __name__ == "__main__":
    unittest.main()
