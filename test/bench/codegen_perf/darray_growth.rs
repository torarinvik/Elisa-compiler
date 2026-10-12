use std::process;

fn push_growing(xs: &mut Vec<i64>, capacity: &mut usize, value: i64) {
    if xs.len() == *capacity {
        let new_capacity = if *capacity == 0 { 8 } else { *capacity * 2 };
        let additional = new_capacity - xs.len();
        xs.reserve_exact(additional);
        *capacity = new_capacity;
    }
    xs.push(value);
}

fn main() {
    let n: usize = 4_000_000;
    let mut xs: Vec<i64> = Vec::new();
    let mut capacity: usize = 0;
    let mut s: u64 = 12345;
    let mut i: usize = 0;
    while i < n {
        s = s.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        push_growing(&mut xs, &mut capacity, (s >> 33) as i64);
        i += 1;
    }

    let mut total = 0i64;
    for index in 0..xs.len() {
        total += xs[index] ^ 73;
    }
    for value in &xs {
        total -= value >> 3;
    }
    println!("{total}");
    process::exit((total % 251) as i32);
}
