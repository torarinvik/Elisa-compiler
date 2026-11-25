// Runs scan_power(n, position, base) from bounded_product_fixture.ll against a C model
// over boundary inputs and a pseudorandom sweep. The model sums base % MODULUS raised
// to position, position - 1, ... for each decimal digit of n; an overflowing power
// must trap (SIGILL or SIGTRAP), and every other result must match. Prints the number
// of cases, or exits nonzero on the first mismatch.
#include <setjmp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>

extern int64_t scan_power(int64_t, int64_t, int64_t);

#ifndef MODULUS
#define MODULUS 10
#endif

static sigjmp_buf trap;

static void caught(int signal_number) {
  (void)signal_number;
  siglongjmp(trap, 1);
}

// Whether scan_power disagrees with the model for (n, position, base).
static int mismatches(int64_t n, int64_t position, int64_t base) {
  int64_t expected = -777;
  int overflow = 0;
  if (n >= 1 && n <= 99999999 && position >= 1 && position <= 8) {
    uint64_t total = 0;
    int64_t reduced = base % MODULUS;
    int64_t exponent_limit = position;
    for (int64_t rest = n; rest > 0; rest /= 10, --exponent_limit) {
      int64_t power = 1;
      for (int64_t exponent = 0; exponent < exponent_limit; ++exponent)
        if (__builtin_mul_overflow(power, reduced, &power)) {
          overflow = 1;
          break;
        }
      if (overflow) break;
      total += (uint64_t)power;
    }
    expected = (int64_t)total;
  }
  if (sigsetjmp(trap, 1)) return !overflow;
  int64_t got = scan_power(n, position, base);
  return got != expected || overflow;
}

int main(void) {
  struct sigaction action = {0};
  action.sa_handler = caught;
  sigemptyset(&action.sa_mask);
  sigaction(SIGILL, &action, 0);
  sigaction(SIGTRAP, &action, 0);
  int64_t numbers[] = {0, 1, 9, 10, 99, 100, 999, 10000000, 99999999, 100000000};
  int64_t bases[] = {INT64_MIN, INT64_MIN + 1, -3037000500LL, -2147483648LL, -10, -9, -2, -1, 0,
                     1, 2, 9, 10, 2147483647LL, 3037000500LL, INT64_MAX};
  unsigned count = 0;
  for (unsigned i = 0; i < sizeof(numbers) / sizeof(numbers[0]); ++i)
    for (int64_t position = 0; position <= 9; ++position)
      for (unsigned j = 0; j < sizeof(bases) / sizeof(bases[0]); ++j) {
        if (mismatches(numbers[i], position, bases[j])) return 1;
        ++count;
      }
  uint64_t state = 43176;
  for (unsigned i = 0; i < 20000; ++i) {
    state = state * 6364136223846793005ULL + 1;
    int64_t n = state % 100000005;
    state = state * 6364136223846793005ULL + 1;
    int64_t position = state % 12;
    state = state * 6364136223846793005ULL + 1;
    if (mismatches(n, position, (int64_t)state)) return 2;
    ++count;
  }
  printf("%u cases passed\n", count);
  return 0;
}
