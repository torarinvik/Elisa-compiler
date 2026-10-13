use std::process;

fn repeated_sum(xs: &[i64], repeats: usize) -> i64 {
    let mut total = 0i64;
    for _ in 0..repeats {
        for &value in xs {
            total += value;
        }
    }
    total
}

fn main() {
    let mut xs = Vec::with_capacity(4_000_000);
    let mut state = 12345u64;
    for _ in 0..4_000_000 {
        state = state
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        xs.push((state >> 33) as i64);
    }
    let total = repeated_sum(&xs, 200);
    println!("{total}");
    process::exit((total % 251) as i32);
}
