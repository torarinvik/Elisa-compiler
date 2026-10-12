const std = @import("std");

const DArray = struct {
    items: []i64,
    count: usize,
    capacity: usize,

    fn push(self: *DArray, value: i64) void {
        if (self.count >= self.capacity) @panic("darray capacity exceeded");
        self.items[self.count] = value;
        self.count += 1;
    }
};

fn alloc(comptime T: type, count: usize) []T {
    return std.heap.c_allocator.alloc(T, count) catch @panic("allocation failed");
}

pub fn main() void {
    const n: usize = 4_000_000;
    var xs = DArray{ .items = alloc(i64, n), .count = 0, .capacity = n };
    var s: u64 = 12345;
    for (0..n) |_| {
        s = s *% 6364136223846793005 +% 1442695040888963407;
        xs.push(@intCast(s >> 33));
    }
    var total: i64 = 0;
    for (0..200) |r| {
        for (0..xs.count) |i| total += xs.items[i] ^ @as(i64, @intCast(r));
        for (xs.items[0..xs.count]) |value| total -= value >> 3;
    }
    std.debug.print("{d}\n", .{total});
    std.process.exit(@intCast(@rem(total, 251)));
}
