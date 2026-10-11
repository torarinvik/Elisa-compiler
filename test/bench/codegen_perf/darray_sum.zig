const std = @import("std");

fn alloc(comptime T: type, count: usize) []T {
    return std.heap.c_allocator.alloc(T, count) catch @panic("allocation failed");
}

pub fn main() void {
    const n: usize = 4_000_000;
    const xs = alloc(i64, n);
    var s: u64 = 12345;
    for (0..n) |i| {
        s = s *% 6364136223846793005 +% 1442695040888963407;
        xs[i] = @intCast(s >> 33);
    }
    var total: i64 = 0;
    for (0..200) |r| {
        for (0..xs.len) |i| total += xs[i] ^ @as(i64, @intCast(r));
        for (xs) |x| total -= x >> 3;
    }
    std.debug.print("{d}\n", .{total});
    std.process.exit(@intCast(@rem(total, 251)));
}
