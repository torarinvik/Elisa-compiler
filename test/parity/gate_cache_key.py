import hashlib, os, sys
h = hashlib.sha256()
h.update(b"elisa-gate-cache-content-v2\0")
check_name, root, *command = sys.argv[1:]
h.update(b"check-name\0" + check_name.encode("utf-8", "surrogateescape") + b"\0")
for arg in command:
    encoded = arg.encode("utf-8", "surrogateescape")
    h.update(len(encoded).to_bytes(8, "big"))
    h.update(encoded)
script = command[0]

def update_file(path):
    path = os.path.abspath(path)
    if os.path.islink(path) or not os.path.isfile(path):
        raise OSError("non-regular parity cache input")
    h.update(path.encode()); h.update(b"\0file\0")
    h.update(str(os.stat(path).st_mode & 0o7777).encode()); h.update(b"\0")
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    h.update(digest.digest())

bins = os.environ.get("ELISA_GATE_BINS_HASH", "")
if bins:
    h.update(bins.encode())
else:
    for f in (os.path.join(root, "bin/elisac-stage1"),
              os.environ.get("ELISA_STAGE1_BIN") or os.path.join(root, "bin/elisac-stage1"),
              (os.environ.get("ELISA_STAGE1_BIN") or os.path.join(root, "bin/elisac-stage1")) + ".provenance.json",
              os.environ.get("ELISA_S0_REAL") or os.environ.get("ELISACORE_BIN", ""),
              (os.environ.get("ELISA_S0_REAL") or os.environ.get("ELISACORE_BIN", "")) + ".provenance.json",
              os.environ.get("ELISA_RUNTIME_OBJ") or os.path.join(root, "build/runtime/elisacore_runtime.o"),
              os.environ.get("ELISA_PARSE_REPORT") or os.path.join(root, "build/parse_report"),
              os.path.join(root, "build/easm_project_driver"),
              os.environ.get("ELISA_EMIT_NATIVE") or os.path.join(root, "build/emit_native")):
        try:
            update_file(f)
        except OSError:
            raise SystemExit(1)
try:
    update_file(script)
    update_file(__file__)
    update_file(os.path.join(root, "test/parity/run_all.sh"))
    update_file(os.path.join(root, "scripts/gate_toolchain_fingerprint.py"))
except OSError:
    raise SystemExit(1)
tree = os.environ.get("ELISA_GATE_TREE_HASH", "")
if tree:
    h.update(tree.encode())
else:
    h.update(b"tree-content-v2\0")
    bases = [os.path.join(root, top) for top in ("test", "scripts", "elisacore_std", "src", "tools")]
    probe = os.path.join(root, ".probe")
    if os.path.lexists(probe):
        bases.append(probe)
    core = os.path.abspath(os.environ.get("ELISA_CORE") or os.path.join(root, "../../Go projects/Elisa-core"))
    bases.extend(os.path.join(core, "compiler", top) for top in ("src", "test", "vendor"))
    bases.append(os.path.join(core, "compiler/runtime/elisacore_std"))
    for name in ("go.mod", "go.sum"):
        try:
            update_file(os.path.join(core, "compiler", name))
        except OSError:
            raise SystemExit(1)
    for base in bases:
        if os.path.islink(base) or not os.path.isdir(base):
            raise SystemExit(1)
        h.update(base.encode()); h.update(b"\0dir\0")
        h.update(str(os.stat(base).st_mode & 0o7777).encode()); h.update(b"\0")
        def fail_walk(error):
            raise error
        for dirpath, dirnames, filenames in os.walk(base, onerror=fail_walk):
            dirnames[:] = sorted(d for d in dirnames if base == probe or not d.startswith("."))
            for name in dirnames:
                path = os.path.join(dirpath, name)
                if os.path.islink(path):
                    raise SystemExit(1)
                try:
                    mode = os.stat(path).st_mode & 0o7777
                except OSError:
                    raise SystemExit(1)
                h.update(path.encode()); h.update(b"\0dir\0")
                h.update(str(mode).encode()); h.update(b"\0")
            for name in sorted(filenames):
                fp = os.path.join(dirpath, name)
                try:
                    update_file(fp)
                except OSError:
                    raise SystemExit(1)
for name, value in sorted(os.environ.items()):
    # Timeout/retry settings and worker counts change whether a check can
    # complete honestly under resource pressure, so stamp them with the result.
    if not name.startswith("ELISA_"):
        continue
    if not (name.endswith("_TIMEOUT") or name.endswith("_TIMEOUT_SCALE")
            or name.endswith("_JOBS") or name in {"ELISA_TIMEOUT_ESCALATE", "ELISA_GATE_NICE"}):
        continue
    h.update(name.encode("utf-8", "surrogateescape") + b"=")
    h.update(value.encode("utf-8", "surrogateescape") + b"\0")
toolchain = os.environ.get("ELISA_GATE_TOOLCHAIN_HASH", "")
if len(toolchain) != 64 or any(c not in "0123456789abcdef" for c in toolchain):
    import subprocess
    result = subprocess.run(
        [sys.executable, os.path.join(root, "scripts/gate_toolchain_fingerprint.py")],
        capture_output=True, text=True, timeout=25, check=False,
    )
    if result.returncode:
        raise SystemExit(1)
    toolchain = result.stdout.strip()
    if len(toolchain) != 64 or any(c not in "0123456789abcdef" for c in toolchain):
        raise SystemExit(1)
h.update(b"toolchain\0" + toolchain.encode("ascii"))
print(h.hexdigest())
