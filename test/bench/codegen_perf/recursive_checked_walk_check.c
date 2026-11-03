#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
extern int64_t recursive_checked_walk(const int64_t *, size_t, size_t);
int main(void) {
  int64_t input[128]; unsigned checked = 0;
  for (size_t n = 0; n <= 128; ++n) {
    for (size_t stop = 0; stop <= n + 1; ++stop) {
      for (int pattern = 0; pattern < 4; ++pattern) {
        for (size_t i = 0; i < n; ++i) input[i] = pattern == 0 ? 1 : pattern == 1 ? -1 : pattern == 2 ? (i % 3 ? 1 : -1) : (i % 5 ? 1 : 7);
        int64_t expected = 0;
        for (size_t current = n; current && current != stop; ) {
          --current; if (input[current] != 7) ++expected;
          if (input[current] <= 0) break;
        }
        int64_t actual = recursive_checked_walk(input, n, stop);
        if (actual != expected) { fprintf(stderr,"n=%zu stop=%zu pattern=%d: %lld != %lld\n",n,stop,pattern,(long long)actual,(long long)expected); return 1; }
        ++checked;
      }
    }
  }
  if (recursive_checked_walk(NULL,1,0) != -1 || recursive_checked_walk(input,129,0) != -1) return 2;
  printf("passed %u recursive walk cases\n",checked + 2); return 0;
}
