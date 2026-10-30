#!/usr/bin/env python3
"""Exercise the wrapper's certificate against a real Stage0 compiler and Z3."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("compiler", type=Path)
    args = parser.parse_args()
    z3 = shutil.which("z3")
    if z3 is None:
        raise SystemExit("z3 is required")
    wrapper = Path(__file__).resolve().parents[2] / "tools/s0cache"
    with tempfile.TemporaryDirectory(prefix="s0cache-smt-cert-") as temp:
        root = Path(temp)
        source = root / "proof.elisa"
        source.write_text(
            "law Bounded(self: i64, lo: i64, hi: i64) = self >= lo and self <= hi\n"
            "type Small = i64 is Bounded[2, 10]\n\n"
            "def mul(a: Small, b: Small) -> i64 is Bounded[4, 100]:\n"
            "    return a * b\n"
        )
        solver = root / "z3"
        solver.write_text(
            '#!/bin/sh\nif [ ! -f "$TEST_SMT_READY" ]; then exit 1; fi\n'
            'exec "$TEST_REAL_Z3" "$@"\n'
        )
        solver.chmod(0o755)
        env = os.environ.copy()
        env.update(
            ELISA_S0_REAL=str(args.compiler.resolve()),
            ELISA_S0_CACHE_DIR=str(root / "outer"),
            ELISA_S0_CACHE_STATS=str(root / "stats"),
            ELISAC_BUILD_CACHE_DIR=str(root / "core"),
            ELISACORE_BUILD_CACHE="0",
            ELISA_Z3=str(solver),
            TEST_REAL_Z3=z3,
            TEST_SMT_READY=str(root / "ready"),
        )
        env.pop("ELISACORE_RETAINED_SERVER", None)
        env.pop("ELISACORE_CACHE_CERTIFICATE", None)

        def run():
            return subprocess.run(
                [str(wrapper), "-emit", "semantic", "-smt", str(source)],
                env=env, capture_output=True, timeout=8, check=False,
            )

        failed = run()
        assert failed.returncode != 0 and b"could not be proven" in failed.stderr
        (root / "ready").touch()
        recovered = run()
        repeated = run()
        assert recovered.returncode == repeated.returncode == 0
        assert recovered.stdout == repeated.stdout and recovered.stderr == repeated.stderr
        assert (root / "stats").read_text().splitlines() == [
            "miss\tsemantic\t-", "miss\tsemantic\t-", "miss\tsemantic\t-"
        ]
        # Script launchers cannot attest their delegated tool. Verify the
        # positive caching path separately with the actual native solver.
        env["ELISA_Z3"] = z3
        native = run()
        native_repeat = run()
        assert native.returncode == native_repeat.returncode == 0
        assert native.stdout == recovered.stdout and native.stderr == recovered.stderr
        assert native_repeat.stdout == native.stdout and native_repeat.stderr == native.stderr
        assert (root / "stats").read_text().splitlines()[-2:] == [
            "miss\tsemantic\t-", "hit\tsemantic\t-"
        ]
        env["ELISA_Z3"] = str(solver)
        # A same-path replacement must invalidate the proof-backed answer.
        solver.write_text("#!/bin/sh\nexit 1\n")
        replaced = run()
        env["ELISA_S0_CACHE"] = "0"
        cold = run()
        assert replaced.returncode == cold.returncode != 0
        assert replaced.stdout == cold.stdout and replaced.stderr == cold.stderr
        assert (root / "stats").read_text().splitlines()[-2:] == [
            "miss\tsemantic\t-", "bypass\t-\t-"
        ]
        # PATH itself can stay unchanged while a higher-priority solver appears.
        earlier, later = root / "earlier", root / "later"
        earlier.mkdir()
        later.mkdir()
        (later / "z3").write_text('#!/bin/sh\nexec "$TEST_REAL_Z3" "$@"\n')
        (later / "z3").chmod(0o755)
        env["PATH"] = str(earlier) + os.pathsep + str(later) + os.pathsep + env["PATH"]
        env["ELISA_Z3"] = "z3"
        env["ELISA_S0_CACHE"] = "1"
        assert run().returncode == 0
        assert run().returncode == 0
        (earlier / "z3").write_text("#!/bin/sh\nexit 1\n")
        (earlier / "z3").chmod(0o755)
        changed_selection = run()
        env["ELISA_S0_CACHE"] = "0"
        cold_selection = run()
        assert changed_selection.returncode == cold_selection.returncode != 0
        assert changed_selection.stderr == cold_selection.stderr
        assert (root / "stats").read_text().splitlines()[-4:] == [
            "miss\tsemantic\t-", "miss\tsemantic\t-", "miss\tsemantic\t-", "bypass\t-\t-"
        ]
    print("transient SMT failure is retried before a certified response is cached")


if __name__ == "__main__":
    main()
