import hashlib, os, sys
h = hashlib.sha256()
h.update(b"elisa-parity-tree-content-v2\0")
root = sys.argv[1]
bases = [os.path.join(root, top) for top in ("test", "scripts", "elisacore_std", "src", "tools")]
probe = os.path.join(root, ".probe")
if os.path.lexists(probe):
    bases.append(probe)
core = os.path.abspath(os.environ.get("ELISA_CORE") or os.path.join(root, "../../Go projects/Elisa-core"))
bases.extend(os.path.join(core, "compiler", top) for top in ("src", "test", "vendor"))
bases.append(os.path.join(core, "compiler/runtime/elisacore_std"))
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
                if os.path.islink(fp) or not os.path.isfile(fp):
                    raise OSError("non-regular parity cache input")
                digest = hashlib.sha256()
                with open(fp, "rb") as source:
                    for chunk in iter(lambda: source.read(1 << 20), b""):
                        digest.update(chunk)
            except OSError:
                raise SystemExit(1)
            h.update(fp.encode()); h.update(b"\0file\0")
            h.update(str(os.stat(fp).st_mode & 0o7777).encode()); h.update(b"\0")
            h.update(digest.digest())
for name in ("go.mod", "go.sum"):
    fp = os.path.join(core, "compiler", name)
    try:
        if os.path.islink(fp) or not os.path.isfile(fp):
            raise OSError("non-regular parity cache input")
        digest = hashlib.sha256()
        with open(fp, "rb") as source:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        raise SystemExit(1)
    h.update(fp.encode()); h.update(b"\0file\0")
    h.update(str(os.stat(fp).st_mode & 0o7777).encode()); h.update(b"\0")
    h.update(digest.digest())
print(h.hexdigest())
