const std = @import("std");
const compat = @import("compat"); // zig 0.17 port
const ArrayList = std.ArrayList;

const VEC_SIZE = 8;
const Vec = @Vector(VEC_SIZE, f64);

const global_allocator = std.heap.c_allocator;

pub fn main(init: std.process.Init) !void {
    try compat.setup(init);
    defer compat.flush() catch {};
    const n = try get_n();
    const size = (n + VEC_SIZE - 1) / VEC_SIZE * VEC_SIZE;
    const chunk_size = size / VEC_SIZE;
    const inv = 2.0 / @as(f64, @floatFromInt(size));
    var xloc: ArrayList(Vec) = .empty;
    try xloc.ensureTotalCapacityPrecise(global_allocator, chunk_size);
    var i: usize = 0;
    while (i < chunk_size) : (i += 1) {
        const offset = i * VEC_SIZE;
        const v = Vec{
            init_xloc(offset, inv),
            init_xloc(offset + 1, inv),
            init_xloc(offset + 2, inv),
            init_xloc(offset + 3, inv),
            init_xloc(offset + 4, inv),
            init_xloc(offset + 5, inv),
            init_xloc(offset + 6, inv),
            init_xloc(offset + 7, inv),
        };
        try xloc.append(global_allocator, v);
    }

    const stdout = compat.stdout();
    try stdout.print("P4\n{d} {d}\n", .{ size, size });

    var pixels: ArrayList(u8) = .empty;
    try pixels.ensureTotalCapacityPrecise(global_allocator, size * chunk_size);
    var y: usize = 0;
    while (y < size) : (y += 1) {
        const ci = @as(f64, @floatFromInt(y)) * inv - 1.0;
        var x: usize = 0;
        while (x < chunk_size) : (x += 1) {
            const r = mbrot8(xloc.items[x], ci);
            try pixels.append(global_allocator, r);
        }
    }

    // CLBG port: the source printed an md5 of the bitmap (PLB variant);
    // the Benchmarks Game spec writes the raw P4 bitmap.
    try stdout.writeAll(pixels.items);
}

fn mbrot8(cr: Vec, civ: f64) u8 {
    const ci = @as(Vec, @splat(civ));
    const zero: f64 = 0.0;
    var zr = @as(Vec, @splat(zero));
    var zi = @as(Vec, @splat(zero));
    var tr = @as(Vec, @splat(zero));
    var ti = @as(Vec, @splat(zero));
    var absz = @as(Vec, @splat(zero));

    var _i: u8 = 0;
    while (_i < 10) : (_i += 1) {
        var _j: u8 = 0;
        while (_j < 5) : (_j += 1) {
            zi = (zr + zr) * zi + ci;
            zr = tr - ti + cr;
            tr = zr * zr;
            ti = zi * zi;
        }
        absz = tr + ti;
        var terminate = true;
        inline for (0..VEC_SIZE) |i| { // 0.17: vector index must be comptime
            if (absz[i] <= 4.0) {
                terminate = false;
                break;
            }
        }
        if (terminate) {
            return 0;
        }
    }
    var accu: u8 = 0;
    inline for (0..VEC_SIZE) |i| { // 0.17: vector index must be comptime
        if (absz[i] <= 4.0) {
            const lhs: u8 = 0x80;
            accu |= (lhs >> @as(u3, @intCast(i)));
        }
    }
    return accu;
}

fn init_xloc(i: usize, inv: f64) f64 {
    return @as(f64, @floatFromInt(i)) * inv - 1.5;
}

fn get_n() !usize {
    if (compat.argv.len < 2) return 200;
    const arg = compat.argv[1];
    return try std.fmt.parseInt(usize, arg, 10);
}
