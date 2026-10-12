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

pub fn main() void {
    const n: usize = 4_000_000;
    var xs = DArray{
        .items = std.heap.c_allocator.alloc(i64, n) catch @panic("allocation failed"),
        .count = 0,
        .capacity = n,
    };
    defer std.heap.c_allocator.free(xs.items);
    const seed: i64 = 0;
    for (0..n) |i| xs.push(@intCast(i));

    var total: i64 = seed;
    for (0..xs.count) |i| total += xs.items[i];

    std.debug.print("{d}\n", .{total});
    std.process.exit(@intCast(@rem(total, 251)));
}
