use std::process;

fn sieve(n: usize) -> i64 {
    let mut flags: Vec<u8> = Vec::with_capacity(n);
    for _i in 0..n {
        flags.push(1);
    }
    flags[0] = 0;
    flags[1] = 0;
    let mut p: usize = 2;
    while p * p < n {
        if flags[p] != 0 {
            let mut m = p * p;
            while m < n {
                flags[m] = 0;
                m += p;
            }
        }
        p += 1;
    }
    let mut count: i64 = 0;
    for i in 0..n {
        count += flags[i] as i64;
    }
    count
}

fn main() {
    let mut total: i64 = 0;
    for _r in 0..30 {
        total += sieve(10_000_000);
    }
    println!("{total}");
    process::exit((total % 251) as i32);
}
