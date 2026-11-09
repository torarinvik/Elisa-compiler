from unsafe_grant_alias_and_effect_cases import CASES as UNSAFE_GRANT_ALIAS_AND_EFFECT_CASES
from unsafe_grant_pointer_expression_cases import CASES as UNSAFE_GRANT_POINTER_EXPRESSION_CASES
from unsafe_grant_pointer_pattern_cases import CASES as UNSAFE_GRANT_POINTER_PATTERN_CASES
from unsafe_grant_cast_and_extern_cases import CASES as UNSAFE_GRANT_CAST_AND_EXTERN_CASES

import pathlib
import subprocess
import sys
import tempfile

stage1 = sys.argv[1]
repo = pathlib.Path(sys.argv[2])

cases = {**UNSAFE_GRANT_ALIAS_AND_EFFECT_CASES, **UNSAFE_GRANT_POINTER_EXPRESSION_CASES, **UNSAFE_GRANT_POINTER_PATTERN_CASES, **UNSAFE_GRANT_CAST_AND_EXTERN_CASES}

# Qualified duplicate leaf names must retain module identity in strict-unsafe effect
# lookup. Test both declaration orders, and check both that the pure sibling stays
# callable and that the unsafe target still requires a local grant.
left_unsafe_module = (
    "module Left:\n"
    "    public:\n"
    "        def touch() -> void can[Unsafe.PointerCast]:\n            pass\n"
)
right_pure_module = (
    "module Right:\n"
    "    public:\n"
    "        def touch() -> void:\n            pass\n"
)
for order_name, modules in (
    ("Left before Right", left_unsafe_module + right_pure_module),
    ("Right before Left", right_pure_module + left_unsafe_module),
):
    cases[f"strict unsafe duplicate leaf pure sibling {order_name}"] = (
        "# strict\n" + modules +
        "def main() -> i64:\n"
        "    Right::touch()\n"
        "    return 0\n",
        None,
    )
    cases[f"strict unsafe duplicate leaf unsafe target {order_name}"] = (
        "# strict\n" + modules +
        "def main() -> i64:\n"
        "    Left::touch()\n"
        "    return 0\n",
        "requires can[Unsafe]",
    )

with tempfile.TemporaryDirectory(prefix="elisa-unsafe-grants-") as temp:
    directory = pathlib.Path(temp)
    for name, (source, expected) in cases.items():
        path = directory / (name.replace(" ", "_") + ".elisa")
        path.write_text(source)
        result = subprocess.run(
            [stage1, "-emit", "interpret", "-o", "/dev/null", str(path)],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=90,
        )
        output = result.stdout
        if result.returncode not in (0, 1):
            raise SystemExit(f"{name}: compiler failed ({result.returncode})\n{output}")
        if expected is None and result.returncode != 0:
            raise SystemExit(f"{name}: expected an accepted program, compiler exited {result.returncode}\n{output}")
        if expected is None and any(
            message in output
            for message in (
                "mutable alias requires",
                "unknown permission",
                "unchecked index requires",
                "mutable global access requires",
                "accesses a global mutable binding without Global.Read",
                "accesses a global mutable binding without Global.Write",
                "pointer arithmetic requires",
                'call to "foreign" requires can[Unsafe]',
                "pointer cast requires",
                "buffer reinterpret cast requires",
                'call to "stale reference" requires can[Unsafe]',
                'call to "unsafe_api" requires can[Unsafe]',
                'call to "unsafe_predicate" requires can[Unsafe]',
                'call to "callback" requires can[Unsafe]',
                'call to "local_callback" requires can[Unsafe]',
            )
        ):
            raise SystemExit(f"{name}: exact grant was rejected\n{output}")
        if expected is not None and expected not in output:
            raise SystemExit(f"{name}: expected {expected!r}\n{output}")

print(f"unsafe grant scope smoke OK: {len(cases)} unrelated, exact, and signature-effect cases")
