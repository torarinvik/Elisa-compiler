use std::process;

fn count_xor(xs: &[i64], r: i64) -> i64 {
    let mut subtotal = 0i64;
    for i in 0..xs.len() {
        subtotal += xs[i] ^ r;
    }
    subtotal
}

fn count_shift(xs: &[i64]) -> i64 {
    let mut subtotal = 0i64;
    for i in 0..xs.len() {
        subtotal -= xs[i] >> 3;
    }
    subtotal
}

fn main() {
    let n: usize = 4_000_000;
    let mut xs: Vec<i64> = Vec::with_capacity(n);
    let mut s: u64 = 12345;
    for _i in 0..n {
        s = s.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        xs.push((s >> 33) as i64);
    }

    let mut total = 0i64;
    for r in 0..200i64 {
        total += count_xor(&xs, r);
        total += count_shift(&xs);
    }

    println!("{total}");
    process::exit((total % 251) as i32);
}
