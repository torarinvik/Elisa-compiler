const std = @import("std");

fn alloc(comptime T: type, count: usize) []T {
    return std.heap.c_allocator.alloc(T, count) catch @panic("allocation failed");
}

pub fn main() void {
    const n: usize = 300;
    const a = alloc(i64, n * n);
    const b = alloc(i64, n * n);
    const c = alloc(i64, n * n);
    @memset(c, 0);
    for (0..n * n) |i| {
        a[i] = @intCast(i % 17);
        b[i] = @as(i64, @intCast(i % 13)) - 6;
    }
    for (0..30) |_| {
        for (0..n) |i| {
            for (0..n) |k| {
                const aik = a[i * n + k];
                for (0..n) |j| {
                    c[i * n + j] += aik * b[k * n + j];
                }
            }
        }
    }
    var total: i64 = 0;
    for (c) |x| total += x;
    std.debug.print("{d}\n", .{total});
    std.process.exit(@intCast(@mod(total, 251)));
}
