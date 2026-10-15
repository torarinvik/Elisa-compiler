//! Zig 0.17 compatibility shim for the Zig 0.14-era reference programs.
//! Zig 0.15+ removed std.io.getStdOut()/std.process.args() and made I/O go
//! through an explicit `std.Io` instance passed to `main`. Each program's
//! `main` takes `std.process.Init` and calls `compat.setup(init)` first; the
//! rest of each program keeps its original algorithm and structure.
const std = @import("std");

pub var io: std.Io = undefined;
pub var argv: []const [:0]const u8 = &.{};

pub fn setup(init: std.process.Init) !void {
    io = init.io;
    argv = try init.minimal.args.toSlice(init.arena.allocator());
}

/// argv[1] parsed as an integer, or `default` when absent.
pub fn argInt(comptime T: type, default: T) !T {
    if (argv.len < 2) return default;
    return try std.fmt.parseInt(T, argv[1], 10);
}

var out_buf: [64 * 1024]u8 = undefined;
var out_state: ?std.Io.File.Writer = null;

/// Buffered stdout writer; call `flush()` before returning from main.
pub fn stdout() *std.Io.Writer {
    if (out_state == null) out_state = std.Io.File.stdout().writer(io, &out_buf);
    return &out_state.?.interface;
}

pub fn flush() !void {
    if (out_state) |*s| try s.interface.flush();
}

var in_buf: [64 * 1024]u8 = undefined;
var in_state: ?std.Io.File.Reader = null;

pub fn stdin() *std.Io.Reader {
    if (in_state == null) in_state = std.Io.File.stdin().readerStreaming(io, &in_buf);
    return &in_state.?.interface;
}
