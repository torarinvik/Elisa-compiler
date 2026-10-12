use std::process;

fn main() {
    let n: usize = 300;
    let mut a: Vec<i64> = Vec::with_capacity(n * n);
    let mut b: Vec<i64> = Vec::with_capacity(n * n);
    let mut c = vec![0i64; n * n];
    for i in 0..n * n {
        a.push((i % 17) as i64);
        b.push((i % 13) as i64 - 6);
    }
    for _rep in 0..30 {
        for i in 0..n {
            for k in 0..n {
                let aik = a[i * n + k];
                for j in 0..n {
                    c[i * n + j] += aik * b[k * n + j];
                }
            }
        }
    }
    let mut total: i64 = 0;
    for &x in &c {
        total += x;
    }
    println!("{total}");
    process::exit((((total % 251) + 251) % 251) as i32);
}
