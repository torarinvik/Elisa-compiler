const std = @import("std");

const record_count: usize = 65_536;
const chunk_records: usize = 256;
const chunk_count: usize = record_count / chunk_records;
const read_passes: usize = 256;

const Record = extern struct { tag: u32, payload_low: u32, payload_high: u32 };
const RecordChunk = struct { items: []Record };
const SideChunk = struct { words: []u64 };

noinline fn storeSide(
    chunks_opt: ?[]SideChunk,
    words: []const u64,
    index: u32,
    count: usize,
    side_words: usize,
) void {
    const chunks = chunks_opt orelse @panic("null side-table state");
    if (side_words == 0) return;
    const index_usize: usize = @intCast(index);
    if (index_usize >= count) @panic("side-table index out of bounds");
    const chunk_index = index_usize / chunk_records;
    const offset = (index_usize - chunk_index * chunk_records) * side_words;
    for (0..side_words) |word| {
        const slot: *volatile u64 = &chunks[chunk_index].words[offset + word];
        slot.* = words[word];
    }
}

noinline fn loadSide(
    chunks_opt: ?[]const SideChunk,
    index: u32,
    count: usize,
    side_words: usize,
    word_offset: usize,
) u64 {
    const chunks = chunks_opt orelse @panic("null side-table state");
    const index_usize: usize = @intCast(index);
    if (index_usize >= count) @panic("side-table index out of bounds");
    if (word_offset >= side_words) @panic("side-table word out of bounds");
    const chunk_index = index_usize / chunk_records;
    const offset = (index_usize - chunk_index * chunk_records) * side_words;
    const slot: *const volatile u64 = &chunks[chunk_index].words[offset + word_offset];
    return slot.*;
}

fn alloc(comptime T: type, count: usize) []T {
    return std.heap.c_allocator.alloc(T, count) catch @panic("allocation failed");
}

pub fn main() void {
    const records = alloc(RecordChunk, chunk_count);
    const side = alloc(SideChunk, chunk_count);
    const handles = alloc(u32, record_count);
    for (0..chunk_count) |chunk| {
        const record_items = alloc(Record, chunk_records);
        records[chunk] = .{ .items = record_items };
        side[chunk] = .{ .words = alloc(u64, chunk_records) };
    }

    for (0..record_count) |i| {
        const chunk_index = i / chunk_records;
        const offset = i - chunk_index * chunk_records;
        const stamp: u64 = @as(u64, @intCast(i)) + 1;
        records[chunk_index].items[offset] = .{ .tag = 0, .payload_low = 0, .payload_high = 0 };
        const tag: *volatile u32 = &records[chunk_index].items[offset].tag;
        tag.* = 1;
        const payload_bits: u64 = @intCast(i);
        const payload_low: *volatile u32 = &records[chunk_index].items[offset].payload_low;
        payload_low.* = @truncate(payload_bits);
        const payload_high: *volatile u32 = &records[chunk_index].items[offset].payload_high;
        payload_high.* = @truncate(payload_bits >> 32);
        const words = [_]u64{stamp};
        storeSide(side, words[0..], @intCast(i), i + 1, 1);
        handles[i] = @intCast(i);
    }

    var total: u64 = 0;
    for (0..read_passes) |_| {
        for (handles) |handle| total += loadSide(side, handle, record_count, 1, 0);
    }

    std.debug.print("{d}\n", .{total});
    for (records) |chunk| std.heap.c_allocator.free(chunk.items);
    for (side) |chunk| std.heap.c_allocator.free(chunk.words);
    std.heap.c_allocator.free(records);
    std.heap.c_allocator.free(side);
    std.heap.c_allocator.free(handles);
    std.process.exit(@intCast(@rem(total, 251)));
}
