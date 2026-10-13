// Scalar Rust peer for the Benchmarks Game spectral-norm task.
// Algorithm and operation order follow the official task description.

use std::env;

fn a(i: usize, j: usize) -> f64 {
    let sum = i + j;
    let denominator = sum * (sum + 1) / 2 + i + 1;
    1.0 / denominator as f64
}

fn times(u: &[f64], v: &mut [f64], n: usize) {
    for i in 0..n {
        let mut sum = 0.0;
        for j in 0..n {
            sum += a(i, j) * u[j];
        }
        v[i] = sum;
    }
}

fn times_transposed(u: &[f64], v: &mut [f64], n: usize) {
    for i in 0..n {
        let mut sum = 0.0;
        for j in 0..n {
            sum += a(j, i) * u[j];
        }
        v[i] = sum;
    }
}

fn ata_times(u: &[f64], v: &mut [f64], temporary: &mut [f64], n: usize) {
    times(u, temporary, n);
    times_transposed(temporary, v, n);
}

fn main() {
    let n = env::args()
        .nth(1)
        .and_then(|value| value.parse().ok())
        .unwrap_or(1000usize);
    let mut u = vec![1.0; n];
    let mut v = vec![0.0; n];
    let mut temporary = vec![0.0; n];

    for _ in 0..10 {
        ata_times(&u, &mut v, &mut temporary, n);
        ata_times(&v, &mut u, &mut temporary, n);
    }

    let mut uv = 0.0;
    let mut vv = 0.0;
    for i in 0..n {
        uv += u[i] * v[i];
        vv += v[i] * v[i];
    }
    println!("{:.9}", (uv / vv).sqrt());
}
