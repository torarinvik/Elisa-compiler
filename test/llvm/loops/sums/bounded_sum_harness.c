#define _POSIX_C_SOURCE 200809L
#include <dlfcn.h>
#include <inttypes.h>
#include <setjmp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef int8_t (*SumFn)(uint8_t, const int8_t *);
typedef struct {
  int trapped;
  int8_t value;
} Outcome;

static sigjmp_buf trap_env;
static volatile sig_atomic_t trap_armed;

static void trap_handler(int signo) {
  if (trap_armed)
    siglongjmp(trap_env, signo);
  _Exit(128 + signo);
}

static Outcome invoke(SumFn fn, uint8_t n, const int8_t *values) {
  Outcome out = {0, 0};
  int signo = sigsetjmp(trap_env, 1);
  if (signo != 0) {
    trap_armed = 0;
    out.trapped = 1;
    return out;
  }
  trap_armed = 1;
  out.value = fn(n, values);
  trap_armed = 0;
  return out;
}

static SumFn load_fn(void *handle, const char *name) {
  void *symbol = dlsym(handle, name);
  if (!symbol) {
    fprintf(stderr, "missing symbol %s: %s\n", name, dlerror());
    exit(2);
  }
  SumFn fn;
  memcpy(&fn, &symbol, sizeof(fn));
  return fn;
}

static void same_outcome(const char *name, Outcome base, Outcome candidate,
                         int expected_trap, int expected_value,
                         uint64_t *checked) {
  ++*checked;
  if (base.trapped != candidate.trapped || base.value != candidate.value ||
      base.trapped != expected_trap ||
      (!expected_trap && base.value != (int8_t)expected_value)) {
    fprintf(stderr,
            "%s mismatch: base=(trap=%d,value=%d) candidate=(trap=%d,value=%d)"
            " expected=(trap=%d,value=%d)\n",
            name, base.trapped, base.value, candidate.trapped,
            candidate.value, expected_trap, (int8_t)expected_value);
    exit(1);
  }
}

static uint32_t rng_state = 0x91e10da5u;
static uint32_t next_random(void) {
  uint32_t x = rng_state;
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  rng_state = x;
  return x;
}

int main(int argc, char **argv) {
  if (argc != 3) {
    fprintf(stderr, "usage: %s baseline.so candidate.so\n", argv[0]);
    return 2;
  }
  struct sigaction sa;
  memset(&sa, 0, sizeof(sa));
  sa.sa_handler = trap_handler;
  sigemptyset(&sa.sa_mask);
  if (sigaction(SIGILL, &sa, NULL) || sigaction(SIGTRAP, &sa, NULL)) {
    perror("sigaction");
    return 2;
  }

  void *base_handle = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!base_handle) {
    fprintf(stderr, "dlopen baseline: %s\n", dlerror());
    return 2;
  }
  void *candidate_handle = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
  if (!candidate_handle) {
    fprintf(stderr, "dlopen candidate: %s\n", dlerror());
    return 2;
  }

  SumFn base_safe_checked = load_fn(base_handle, "safe_checked");
  SumFn cand_safe_checked = load_fn(candidate_handle, "safe_checked");
  SumFn base_clamped = load_fn(base_handle, "safe_clamped");
  SumFn cand_clamped = load_fn(candidate_handle, "safe_clamped");
  SumFn base_safe_plain = load_fn(base_handle, "safe_plain");
  SumFn cand_safe_plain = load_fn(candidate_handle, "safe_plain");
  SumFn base_unsafe = load_fn(base_handle, "unsafe_m33");
  SumFn cand_unsafe = load_fn(candidate_handle, "unsafe_m33");
  SumFn base_seed = load_fn(base_handle, "nonzero_seed127");
  SumFn cand_seed = load_fn(candidate_handle, "nonzero_seed127");
  SumFn base_header = load_fn(base_handle, "header_update_before_exit");
  SumFn cand_header = load_fn(candidate_handle, "header_update_before_exit");
  SumFn base_flag = load_fn(base_handle, "header_update_observable_flag");
  SumFn cand_flag = load_fn(candidate_handle, "header_update_observable_flag");

  uint64_t checked = 0;
  int8_t values[8];
  for (unsigned n = 1; n <= 8; ++n) {
    uint32_t cases = 1u << (2 * n); // all 4^n arrays with values in [0,3]
    for (uint32_t code = 0; code < cases; ++code) {
      uint32_t digits = code;
      int expected = 0;
      for (unsigned i = 0; i < n; ++i) {
        values[i] = (int8_t)(digits & 3u);
        expected += values[i];
        digits >>= 2;
      }
      Outcome b = invoke(base_safe_checked, (uint8_t)n, values);
      Outcome c = invoke(cand_safe_checked, (uint8_t)n, values);
      same_outcome("safe_checked", b, c, 0, expected, &checked);
      b = invoke(base_safe_plain, (uint8_t)n, values);
      c = invoke(cand_safe_plain, (uint8_t)n, values);
      same_outcome("safe_plain", b, c, 0, expected, &checked);
      int clamped = 0;
      for (unsigned i = 0; i < n; ++i) {
        clamped += values[i];
        if (clamped > (int)i)
          clamped = (int)i;
      }
      b = invoke(base_clamped, (uint8_t)n, values);
      c = invoke(cand_clamped, (uint8_t)n, values);
      same_outcome("safe_clamped", b, c, 0, clamped, &checked);
    }
  }

  const int8_t unsafe_boundary[][8] = {
      {33, 33, 33, 33, 0, 0, 0, 0},
      {33, 33, 33, 31, 0, 0, 0, 0},
      {33, 33, 33, 29, 0, 0, 0, 0},
      {33, 33, 33, 0, 0, 0, 0, 0},
      {33, 33, 33, 33, 33, 33, 33, 33},
      {0, 0, 0, 0, 0, 0, 0, 0},
  };
  const uint8_t unsafe_lengths[] = {4, 4, 4, 4, 8, 8};
  for (unsigned k = 0; k < sizeof(unsafe_lengths); ++k) {
    unsigned n = unsafe_lengths[k];
    int sum = 0;
    for (unsigned i = 0; i < n; ++i)
      sum += unsafe_boundary[k][i];
    int should_trap = sum > 127;
    int expected = (int8_t)sum;
    Outcome b = invoke(base_unsafe, (uint8_t)n, unsafe_boundary[k]);
    Outcome c = invoke(cand_unsafe, (uint8_t)n, unsafe_boundary[k]);
    same_outcome("unsafe_m33_boundary", b, c, should_trap, expected,
                 &checked);
  }

  // A small deterministic random corpus probes unsafe bounds without running
  // the full 4^8 exhaustive corpus through expected trap paths.
  for (unsigned trial = 0; trial < 256; ++trial) {
    unsigned n = 1 + next_random() % 8;
    int sum = 0;
    for (unsigned i = 0; i < n; ++i) {
      values[i] = (int8_t)(next_random() % 34);
      sum += values[i];
    }
    int should_trap = sum > 127;
    Outcome b = invoke(base_unsafe, (uint8_t)n, values);
    Outcome c = invoke(cand_unsafe, (uint8_t)n, values);
    same_outcome("unsafe_m33_random", b, c, should_trap, (int8_t)sum,
                 &checked);
  }

  for (unsigned trial = 0; trial < 256; ++trial) {
    unsigned n = 1 + next_random() % 8;
    int sum = 127;
    for (unsigned i = 0; i < n; ++i) {
      values[i] = (int8_t)(next_random() % 4);
      sum += values[i];
    }
    int should_trap = sum > 127;
    Outcome b = invoke(base_seed, (uint8_t)n, values);
    Outcome c = invoke(cand_seed, (uint8_t)n, values);
    same_outcome("nonzero_seed127", b, c, should_trap, (int8_t)sum,
                 &checked);
  }

  int8_t unused = 0;
  for (unsigned n = 0; n <= 3; ++n) {
    int sum = 40 * (n + 1); // update precedes equality exit check
    int should_trap = sum > 127;
    Outcome b = invoke(base_header, (uint8_t)n, &unused);
    Outcome c = invoke(cand_header, (uint8_t)n, &unused);
    same_outcome("header_update_before_exit", b, c, should_trap,
                 (int8_t)sum, &checked);
    int flag_expected = should_trap ? 1 : sum;
    b = invoke(base_flag, (uint8_t)n, &unused);
    c = invoke(cand_flag, (uint8_t)n, &unused);
    same_outcome("header_update_observable_flag", b, c, 0,
                 flag_expected, &checked);
  }

  printf("bounded checked-sum parity passed: %" PRIu64 " comparisons\n",
         checked);
  dlclose(candidate_handle);
  dlclose(base_handle);
  return 0;
}
