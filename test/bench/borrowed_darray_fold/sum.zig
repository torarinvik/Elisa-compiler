const std = @import("std");

fn alloc(comptime T: type, count: usize) []T {
    return std.heap.c_allocator.alloc(T, count) catch @panic("allocation failed");
}

fn repeatedSum(xs: []const i64, repeats: usize) i64 {
    var total: i64 = 0;
    for (0..repeats) |_| {
        for (xs) |value| total += value;
    }
    return total;
}

pub fn main() void {
    const xs = alloc(i64, 4_000_000);
    var state: u64 = 12345;
    for (xs) |*value| {
        state = state *% 6364136223846793005 +% 1442695040888963407;
        value.* = @intCast(state >> 33);
    }
    const total = repeatedSum(xs, 200);
    std.debug.print("{d}\n", .{total});
    std.process.exit(@intCast(@rem(total, 251)));
}
