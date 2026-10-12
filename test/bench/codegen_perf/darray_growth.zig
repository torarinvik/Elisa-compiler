const std = @import("std");

const DArray = struct {
    items: []i64,
    count: usize,
    capacity: usize,

    fn push(self: *DArray, value: i64) void {
        if (self.count == self.capacity) {
            const new_capacity: usize = if (self.capacity == 0) 8 else self.capacity * 2;
            if (self.capacity == 0) {
                self.items = alloc(i64, new_capacity);
            } else {
                self.items = std.heap.c_allocator.realloc(self.items, new_capacity) catch @panic("allocation failed");
            }
            self.capacity = new_capacity;
        }
        self.items[self.count] = value;
        self.count += 1;
    }
};

fn alloc(comptime T: type, count: usize) []T {
    return std.heap.c_allocator.alloc(T, count) catch @panic("allocation failed");
}

pub fn main() void {
    const n: usize = 4_000_000;
    var xs = DArray{ .items = undefined, .count = 0, .capacity = 0 };
    var s: u64 = 12345;
    var i: usize = 0;
    while (i < n) : (i += 1) {
        s = s *% 6364136223846793005 +% 1442695040888963407;
        xs.push(@intCast(s >> 33));
    }

    var total: i64 = 0;
    for (0..xs.count) |index| total += xs.items[index] ^ 73;
    for (xs.items[0..xs.count]) |value| total -= value >> 3;
    std.debug.print("{d}\n", .{total});
    std.process.exit(@intCast(@rem(total, 251)));
}
