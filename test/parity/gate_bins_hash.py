import hashlib, os, sys
h = hashlib.sha256()
root = sys.argv[1]
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
        path = os.path.abspath(f)
        if os.path.islink(path) or not os.path.isfile(path):
            raise OSError("non-regular parity cache product")
        h.update(path.encode()); h.update(b"\0file\0")
        h.update(str(os.stat(path).st_mode & 0o7777).encode()); h.update(b"\0")
        digest = hashlib.sha256()
        with open(path, "rb") as source:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                digest.update(chunk)
        h.update(digest.digest())
    except OSError:
        raise SystemExit(1)
print(h.hexdigest())
