"""Read and validate the include closure used as Stage0 cache input."""
import os
import stat

from s0cache_identity import regular_file_identity


MAX_INCLUDE_FILE_BYTES = 64 << 20

MAX_INCLUDE_CLOSURE_BYTES = 256 << 20

MAX_INCLUDE_FILES = 100_000

def include_closure(root):
    """Ordered (abspath, bytes, identity) triples for source and includes, or None."""
    out, seen, stack = [], set(), [os.path.abspath(root)]
    total_bytes = 0
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        if len(seen) >= MAX_INCLUDE_FILES:
            return None
        seen.add(path)
        try:
            flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as f:
                before = os.fstat(f.fileno())
                if not stat.S_ISREG(before.st_mode):
                    return None
                remaining = MAX_INCLUDE_CLOSURE_BYTES - total_bytes
                if before.st_size > MAX_INCLUDE_FILE_BYTES or before.st_size > remaining:
                    return None
                data = f.read(min(MAX_INCLUDE_FILE_BYTES, remaining) + 1)
                after = os.fstat(f.fileno())
            identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                                     info.st_mtime_ns, info.st_ctime_ns)
            if (identity(before) != identity(after)
                    or len(data) != after.st_size
                    or len(data) > MAX_INCLUDE_FILE_BYTES
                    or len(data) > remaining
                    or regular_file_identity(path) != identity(after)):
                return None
        except OSError:
            return None
        total_bytes += len(data)
        out.append((path, data, identity(after)))
        base = os.path.dirname(path)
        for raw in data.split(b"\n"):
            line = raw.strip()
            if line.startswith(b"#"):
                line = line[1:].strip()
            inc = None
            if line.startswith(b"include "):
                rest = line[8:].strip()
                if len(rest) >= 2 and rest[:1] == b'"' and rest[-1:] == b'"':
                    inc = rest[1:-1]
                # An UNQUOTED rest is not an include: `parseIncludeDirective` returns false and
                # the oracle ignores the line. Prose does reach here — a `#` comment is stripped
                # of its marker first, so `# include flattening, so gen2 …` looks like a
                # directive. Treating that as uncacheable made 93 of this repo's 1470 sources
                # (and 352 gate calls) bypass the memo for no reason.
            elif line.startswith(b"{$") and line.endswith(b"}") and len(line) >= 4:
                body = line[2:-1].strip().split(None, 1)
                if body and body[0].lower() in (b"i", b"include") and len(body) > 1:
                    arg = body[1].strip()
                    if len(arg) >= 2 and arg[:1] in (b"'", b'"') and arg[-1:] == arg[:1]:
                        arg = arg[1:-1]
                    elif arg.split() != [arg]:
                        arg = b""  # unquoted WITH whitespace: the oracle rejects it, so skip
                    inc = arg or None
            if inc is None:
                continue
            try:
                inc_s = inc.decode()
            except UnicodeDecodeError:
                return None
            target = inc_s if os.path.isabs(inc_s) else os.path.join(base, inc_s)
            if not os.path.exists(target):
                return None
            stack.append(os.path.abspath(target))
    return out

def include_closure_unchanged(closure):
    """Reject reuse if any source/include inode changed since key construction."""
    try:
        return all(regular_file_identity(path) == identity
                   for path, _, identity in closure)
    except OSError:
        return False
