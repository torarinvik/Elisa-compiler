use std::process;

fn main() {
    let n: usize = 4_000_000;
    let mut xs: Vec<i64> = Vec::with_capacity(n);
    let seed = 0i64;
    for i in 0..n {
        xs.push(i as i64);
    }

    let mut total = seed;
    for i in 0..xs.len() {
        total += xs[i];
    }

    println!("{total}");
    process::exit((total % 251) as i32);
}
