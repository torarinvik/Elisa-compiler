const std = @import("std");

fn alloc(comptime T: type, count: usize) []T {
    return std.heap.c_allocator.alloc(T, count) catch @panic("allocation failed");
}

fn sieve(n: usize) i64 {
    const flags = alloc(u8, n);
    defer std.heap.c_allocator.free(flags);
    for (0..n) |i| flags[i] = 1;
    flags[0] = 0;
    flags[1] = 0;
    var p: usize = 2;
    while (p * p < n) : (p += 1) {
        if (flags[p] != 0) {
            var m = p * p;
            while (m < n) : (m += p) flags[m] = 0;
        }
    }
    var count: i64 = 0;
    for (0..n) |i| count += @intCast(flags[i]);
    return count;
}

pub fn main() void {
    var total: i64 = 0;
    for (0..30) |_| total += sieve(10_000_000);
    std.debug.print("{d}\n", .{total});
    std.process.exit(@intCast(@rem(total, 251)));
}
