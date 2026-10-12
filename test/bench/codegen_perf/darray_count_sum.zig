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

fn countXor(xs: *const DArray, r: i64) i64 {
    var subtotal: i64 = 0;
    for (0..xs.count) |i| subtotal += xs.items[i] ^ r;
    return subtotal;
}

fn countShift(xs: *const DArray) i64 {
    var subtotal: i64 = 0;
    for (0..xs.count) |i| subtotal -= xs.items[i] >> 3;
    return subtotal;
}

pub fn main() void {
    const n: usize = 4_000_000;
    var xs = DArray{
        .items = std.heap.c_allocator.alloc(i64, n) catch @panic("allocation failed"),
        .count = 0,
        .capacity = n,
    };
    defer std.heap.c_allocator.free(xs.items);
    var s: u64 = 12345;
    for (0..n) |_| {
        s = s *% 6364136223846793005 +% 1442695040888963407;
        xs.push(@intCast(s >> 33));
    }

    var total: i64 = 0;
    for (0..200) |r| {
        total += countXor(&xs, @intCast(r));
        total += countShift(&xs);
    }

    std.debug.print("{d}\n", .{total});
    std.process.exit(@intCast(@rem(total, 251)));
}
