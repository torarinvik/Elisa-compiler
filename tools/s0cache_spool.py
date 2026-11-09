"""Bounded child-output capture and reliable replay for the Stage0 cache."""
import os
import subprocess
import sys
import tempfile
import threading


CACHE_TEXT_MAX_BYTES = 16 << 20

def _write_spool(spool, data):
    view = memoryview(data)
    total = 0
    while view:
        try:
            written = spool.write(view)
        except (OSError, ValueError, TypeError):
            return total, False
        if written is None or written <= 0:
            return total, False
        total += written
        view = view[written:]
    return total, True

def _mark_capture_reason(state, reason, *, replace=False):
    if state[0] is None or replace:
        state[0] = reason

def _write_sink(sink, data):
    view = memoryview(data)
    total = 0
    while view:
        try:
            written = sink.write(view)
        except (OSError, ValueError, TypeError):
            return total, False
        if written is None or written <= 0:
            return total, False
        total += written
        view = view[written:]
    return total, True

def _copy_spool_to_sink(spool, sink, limit=CACHE_TEXT_MAX_BYTES, expected=None):
    """Copy a bounded spool and return the number of bytes delivered."""
    sent = 0
    try:
        size = min(os.fstat(spool.fileno()).st_size, limit)
        spool.seek(0)
        while sent < size:
            chunk = spool.read(min(1024 * 1024, size - sent))
            if not chunk:
                return sent, False
            if expected is not None and chunk != bytes(expected[sent:sent + len(chunk)]):
                return sent, False
            written, complete = _write_sink(sink, chunk)
            sent += written
            if not complete:
                return sent, False
        return sent, True
    except (OSError, ValueError, TypeError):
        return sent, False

def _recover_spool_to_sink(spool, sink, sent=0, limit=CACHE_TEXT_MAX_BYTES):
    """Retry a failed spool replay with positioned reads, if available."""
    try:
        size = min(os.fstat(spool.fileno()).st_size, limit)
        if sent > size:
            return False
        if hasattr(os, "pread"):
            while sent < size:
                chunk = os.pread(spool.fileno(), min(1024 * 1024, size - sent), sent)
                if not chunk:
                    return False
                written, complete = _write_sink(sink, chunk)
                sent += written
                if not complete:
                    return False
            return True
        spool.seek(sent)
        while sent < size:
            chunk = spool.read(min(1024 * 1024, size - sent))
            if not chunk:
                return False
            written, complete = _write_sink(sink, chunk)
            sent += written
            if not complete:
                return False
        return True
    except (OSError, ValueError, TypeError):
        return False

def _fallback_spool_to_sink(spool, sink, captured_data, sent=0):
    if captured_data is not None:
        if sent > len(captured_data):
            return False
        written, complete = _write_sink(sink, captured_data[sent:])
        return complete and sent + written == len(captured_data)
    return _recover_spool_to_sink(spool, sink, sent)

def _drain_child_stream(source, spool, sink, capture_state, already_replayed,
                        spooled_size, captured_prefix):
    """Spool child output while retaining only a cache-sized replay prefix in RAM."""
    try:
        while True:
            # read1() maps to one underlying read on the subprocess pipe; plain
            # read(n) may wait for n bytes and let a small-output child block.
            chunk = source.read1(1024 * 1024)
            if not chunk:
                break
            if already_replayed[0]:
                written, complete = _write_sink(sink, chunk)
                if not complete or written != len(chunk):
                    _mark_capture_reason(capture_state, "output-write", replace=True)
                try:
                    sink.flush()
                except (OSError, ValueError):
                    _mark_capture_reason(capture_state, "output-write", replace=True)
                continue
            remaining = CACHE_TEXT_MAX_BYTES - spooled_size[0]
            stored = chunk[:remaining]
            overflow = chunk[remaining:]
            written, stored_all = _write_spool(spool, stored)
            spooled_size[0] += written
            # Keep a bounded memory copy as an emergency replay source. The disk
            # spool normally handles output; this preserves the compiler's bytes
            # if a later spool read fails after the child has exited.
            captured_prefix.extend(stored[:written])
            if not stored_all:
                # If scratch storage fails, replay the saved prefix and stream
                # the rest. The compiler's status and output survive; this call
                # is not eligible for cache publication.
                _mark_capture_reason(capture_state, "spool-write")
                overflow = chunk[written:]
            elif overflow:
                # Output beyond the cache bound is never a candidate. Replay the
                # bounded prefix and pass subsequent bytes through without using
                # more temporary storage.
                _mark_capture_reason(capture_state, "output-limit")
            else:
                continue
            sent, replayed = _copy_spool_to_sink(spool, sink, expected=captured_prefix)
            if not replayed or sent != len(captured_prefix):
                _mark_capture_reason(capture_state, "spool-replay", replace=True)
                _fallback_spool_to_sink(spool, sink, captured_prefix, sent)
            already_replayed[0] = True
            written, complete = _write_sink(sink, overflow)
            if not complete or written != len(overflow):
                _mark_capture_reason(capture_state, "output-write", replace=True)
            try:
                sink.flush()
            except (OSError, ValueError):
                _mark_capture_reason(capture_state, "output-write", replace=True)
    except (OSError, ValueError):
        # A broken capture pipe is a cache decline. Closing it lets the child see
        # the same write failure it would see if the caller closed its output.
        _mark_capture_reason(capture_state, "pipe-read", replace=True)
    finally:
        try:
            source.close()
        except (OSError, ValueError):
            _mark_capture_reason(capture_state, "pipe-close", replace=True)

def _abort_spooled_child(proc, readers):
    """Reap a child and join any readers if capture setup or waiting fails."""
    try:
        if proc.poll() is None:
            proc.kill()
    except (OSError, ValueError):
        pass
    try:
        proc.wait()
    except BaseException:
        pass
    streams = (getattr(proc, "stdout", None), getattr(proc, "stderr", None))
    for index, stream in enumerate(streams):
        if stream is None:
            continue
        reader = readers[index] if index < len(readers) else None
        if reader is None or reader.ident is None:
            try:
                stream.close()
            except (OSError, ValueError):
                pass
    for reader in readers:
        if reader.ident is not None:
            try:
                reader.join()
            except RuntimeError:
                pass

def run_spooled(real, argv, env):
    """Run with communicate()-like capture semantics and bounded in-memory output."""
    stdout_spool = stderr_spool = None
    try:
        stdout_spool = tempfile.TemporaryFile(mode="w+b", buffering=0)
        stderr_spool = tempfile.TemporaryFile(mode="w+b", buffering=0)
    except OSError:
        if stdout_spool is not None:
            try:
                stdout_spool.close()
            except Exception:
                pass
        if stderr_spool is not None:
            try:
                stderr_spool.close()
            except Exception:
                pass
        # If temporary storage is unavailable, preserve compiler output by letting
        # it inherit the caller's descriptors. This result cannot be admitted to cache.
        proc = subprocess.Popen([real] + argv, stdin=subprocess.DEVNULL, env=env)
        proc.wait()
        proc.stdout_data = proc.stderr_data = None
        proc.output_spools = None
        proc.output_capture_complete = False
        proc.output_capture_reason = "spool-create"
        return proc

    proc = None
    readers = []
    try:
        proc = subprocess.Popen([real] + argv, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        capture_state = [None]
        already_replayed = [[False], [False]]
        spooled_sizes = [[0], [0]]
        captured_prefixes = [bytearray(), bytearray()]
        readers = [
            threading.Thread(target=_drain_child_stream,
                             args=(proc.stdout, stdout_spool, sys.stdout.buffer,
                                   capture_state, already_replayed[0], spooled_sizes[0],
                                   captured_prefixes[0])),
            threading.Thread(target=_drain_child_stream,
                             args=(proc.stderr, stderr_spool, sys.stderr.buffer,
                                   capture_state, already_replayed[1], spooled_sizes[1],
                                   captured_prefixes[1])),
        ]
        for reader in readers:
            reader.start()
        proc.wait()
        for reader in readers:
            reader.join()
        # The bounded bytearrays are exact copies of everything admitted to the
        # spool. Keep them as the cache/replay source so a later disk read failure
        # cannot discard output after the compiler has already exited.
        proc.stdout_data, proc.stderr_data = captured_prefixes
        proc.output_capture_reason = capture_state[0]
        proc.output_capture_complete = capture_state[0] is None
        proc.output_spools = (stdout_spool, stderr_spool,
                              [flag[0] for flag in already_replayed])
        return proc
    except BaseException:
        if proc is not None:
            _abort_spooled_child(proc, readers)
        for spool in (stdout_spool, stderr_spool):
            try:
                spool.close()
            except Exception:
                pass
        raise

def replay_spooled_output(proc):
    spools = getattr(proc, "output_spools", None)
    if spools is None:
        return
    stdout_spool, stderr_spool, already_replayed = spools
    try:
        # Under-bound streams retain the wrapper's original stdout-then-stderr
        # replay after the child exits. Over-bound streams already replayed their
        # prefix and passed the remainder through live.
        for index, (spool, sink, data) in enumerate((
            (stdout_spool, sys.stdout.buffer, getattr(proc, "stdout_data", None)),
            (stderr_spool, sys.stderr.buffer, getattr(proc, "stderr_data", None)),
        )):
            if already_replayed[index]:
                continue
            sent, replayed = _copy_spool_to_sink(spool, sink, expected=data)
            if not replayed or (data is not None and sent != len(data)):
                proc.output_capture_complete = False
                proc.output_capture_reason = "spool-replay"
                _fallback_spool_to_sink(spool, sink, data, sent)
            try:
                sink.flush()
            except (OSError, ValueError):
                proc.output_capture_complete = False
                proc.output_capture_reason = "output-write"
    finally:
        for spool in (stdout_spool, stderr_spool):
            try:
                spool.close()
            except Exception:
                proc.output_capture_complete = False
                if proc.output_capture_reason is None:
                    proc.output_capture_reason = "spool-close"
        proc.output_spools = None
