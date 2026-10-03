// Allocation profiler for an OPTIMIZED Elisa build, through the arena runtime's profiler
// hook ABI (elisacore_std/profiler_hooks.elisa). Strong definitions of the hooks; link an
// object with this instead of the weak fallbacks -- see tools/memprof/README.md.
//   ELISA_MEMPROF_OUT=path   output (default /tmp/elisa_memprof.txt)
//   ELISA_MEMPROF_RATE=bytes sample one stack every N allocated bytes (default 1 MiB)
//   ELISA_MEMPROF_FP=1       walk frame pointers (target built with frame pointers, e.g.
//                            stage1 with ELISA_STAGE1_KEEP_FRAME_POINTER=1) instead of
//                            backtrace(3), which stops at frames without unwind info
// Output lines: S (stack sample: tag weight arena addrs...), F (arena freed/reset),
// M (arena adopted child->parent), R (RSS checkpoint every +64 MiB), C (region-size class
// first seen), and at exit SUMMARY, H (region-size histogram), MAP, ADOPT* lines.
#define _GNU_SOURCE
#include <execinfo.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>

static uint64_t alloc_bytes, move_bytes, inplace_bytes, region_live, region_peak, region_created, region_freed_bytes;
static uint64_t n_alloc, n_move, n_region_create, n_region_free, n_reset, n_rewind, n_trim;
static uint64_t hist_n[64], hist_b[64];
struct ERegion { struct ERegion *next; size_t count, capacity; uintptr_t owner_tag; struct ERegion *owner_next; size_t global_index, committed; void *free_list; };
struct EArena { struct ERegion *begin, *end; size_t end_index; intptr_t strategy; };
static uint64_t n_adopt, adopt_walk, adopt_max_len;
static uint64_t chain_hist[32];
static uint64_t sample_rate = 1 << 20, since_sample;
static FILE *out;
static uintptr_t cur_arena;
static int inited;
static uint64_t next_report = 64ull << 20;
static struct timespec t0;

static double now_s(void) {
  struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
  return (t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) / 1e9;
}
static long rss_kb(void) {
  FILE *f = fopen("/proc/self/statm", "r"); long a = 0, b = 0;
  if (f) { if (fscanf(f, "%ld %ld", &a, &b) != 2) b = 0; fclose(f); }
  return b * 4;
}
static void dump(void) {
  if (!out) return;
  struct rusage ru; getrusage(RUSAGE_SELF, &ru);
  fprintf(out, "SUMMARY t=%.2f maxrss_kb=%ld alloc=%llu move=%llu inplace=%llu n_alloc=%llu n_move=%llu regions_created=%llu(%llu B) region_peak=%llu freed=%llu(%llu B) reset=%llu rewind=%llu trim=%llu\n",
          now_s(), ru.ru_maxrss, (unsigned long long)alloc_bytes, (unsigned long long)move_bytes, (unsigned long long)inplace_bytes,
          (unsigned long long)n_alloc, (unsigned long long)n_move, (unsigned long long)n_region_create, (unsigned long long)region_created,
          (unsigned long long)region_peak, (unsigned long long)n_region_free, (unsigned long long)region_freed_bytes,
          (unsigned long long)n_reset, (unsigned long long)n_rewind, (unsigned long long)n_trim);
  { FILE *m = fopen("/proc/self/smaps", "r"); char line[512]; unsigned long lo = 0, hi = 0; long rss_kb_m = 0;
    uint64_t mh_n[64] = {0}, mh_rss[64] = {0}; int cur = -1, anon = 0;
    while (m && fgets(line, sizeof line, m)) {
      unsigned long a, b; char perms[8]; unsigned long off; char dev[16]; unsigned long ino; char path[256] = "";
      int k = sscanf(line, "%lx-%lx %7s %lx %15s %lu %255s", &a, &b, perms, &off, dev, &ino, path);
      if (k >= 6 && strchr(line, '-') && line[0] != ' ' && (line[8] == '-' || strchr(line, '-') < strchr(line, ' '))) {
        lo = a; hi = b; anon = (k == 6); cur = anon ? 63 - __builtin_clzll((hi - lo) | 1) : -1; if (cur >= 0) mh_n[cur]++;
      } else if (cur >= 0 && sscanf(line, "Rss: %ld kB", &rss_kb_m) == 1) mh_rss[cur] += rss_kb_m;
    }
    if (m) fclose(m);
    for (int b = 0; b < 64; b++) if (mh_n[b]) fprintf(out, "MAP 2^%d n=%llu rss_mb=%llu\n", b, (unsigned long long)mh_n[b], (unsigned long long)(mh_rss[b] >> 10));
  }
  fprintf(out, "ADOPT n=%llu total_chain_walk=%llu max_chain=%llu\n", (unsigned long long)n_adopt, (unsigned long long)adopt_walk, (unsigned long long)adopt_max_len);
  for (int b = 0; b < 32; b++) if (chain_hist[b]) fprintf(out, "ADOPTLEN 2^%d %llu\n", b, (unsigned long long)chain_hist[b]);
  for (int b = 0; b < 64; b++) if (hist_n[b]) fprintf(out, "H 2^%d %llu regions %llu MB\n", b, (unsigned long long)hist_n[b], (unsigned long long)(hist_b[b] >> 20));
  fclose(out); out = NULL;
}
static void init(void) {
  inited = 1;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  const char *p = getenv("ELISA_MEMPROF_OUT");
  const char *r = getenv("ELISA_MEMPROF_RATE");
  if (r) sample_rate = strtoull(r, 0, 10);
  out = fopen(p ? p : "/tmp/elisa_memprof.txt", "w");
  atexit(dump);
}
#define HS (1 << 20)
static uintptr_t hset[HS];
static uintptr_t *hslot(uintptr_t k) {
  size_t i = (k * 0x9E3779B97F4A7C15ull) >> 44;
  while (hset[i & (HS - 1)] && hset[i & (HS - 1)] != k) i++;
  return &hset[i & (HS - 1)];
}
static int hhas(uintptr_t k) { return *hslot(k) == k; }
static void hadd(uintptr_t k) { *hslot(k) = k; }
static void hdel(uintptr_t k) { uintptr_t *p = hslot(k); if (*p == k) *p = 1; /* tombstone */ }
static int use_fp = -1;
static int fp_walk(void **bt, int max) {
  // Frame-pointer chain walk: needs a target built with frame pointers
  // (stage1: ELISA_STAGE1_KEEP_FRAME_POINTER=1). Bounded to the current stack.
  void **fp = (void **)__builtin_frame_address(0);
  uintptr_t lo = (uintptr_t)fp, hi = lo + (256ull << 20);
  int n = 0;
  while (n < max && (uintptr_t)fp >= lo && (uintptr_t)fp < hi && ((uintptr_t)fp & 7) == 0) {
    void *ret = fp[1];
    if (!ret) break;
    bt[n++] = ret;
    void **next = (void **)fp[0];
    if (next <= fp) break;
    fp = next;
  }
  return n;
}
static void sample(uint64_t weight, char tag) {
  void *bt[48];
  if (use_fp < 0) use_fp = getenv("ELISA_MEMPROF_FP") != NULL;
  int n = use_fp ? fp_walk(bt, 48) : backtrace(bt, 48);
  if (tag != 'C' && tag != 'R') hadd(cur_arena);
  fprintf(out, "S %c %llu %lx", tag, (unsigned long long)weight, (unsigned long)cur_arena);
  for (int i = use_fp ? 1 : 3; i < n; i++) fprintf(out, " %lx", (unsigned long)bt[i]);
  fputc('\n', out);
}
static void account(uint64_t size, char tag) {
  since_sample += size;
  while (since_sample >= sample_rate) { since_sample -= sample_rate; sample(sample_rate, tag); }
}

uint32_t elisa_profile_allocation_negotiate(uint32_t v) { if (!inited) init(); return v == 1 ? 1 : 0; }
uint32_t elisa_profile_region_layout_negotiate(uint32_t v) { (void)v; return 0; }
void elisa_profile_region_layout_v1(uintptr_t a, size_t r, uintptr_t h, uintptr_t d, size_t c) { (void)a; (void)r; (void)h; (void)d; (void)c; }
void elisa_profile_allocation_event_v1(uint32_t kind, uintptr_t address, size_t size, uintptr_t old_address, size_t old_size, uintptr_t arena, size_t region) {
  (void)address; (void)old_address; (void)arena; (void)region;
  if (!out) return;
  switch (kind) {
  case 1: alloc_bytes += size; n_alloc++; cur_arena = arena; account(size, 'A'); break;
  case 2: inplace_bytes += size - old_size; cur_arena = arena; account(size - old_size, 'I'); break;
  case 3: move_bytes += size; n_move++; break; // the move's alloc was already counted as ALLOC
  case 5:
    n_region_create++; region_created += size; region_live += size;
    { int b = 63 - __builtin_clzll(size | 1); hist_n[b]++; hist_b[b] += size;
      if (hist_n[b] == 1 || hist_n[b] == 1000 || hist_n[b] == 100000) { fprintf(out, "C %d %llu\n", b, (unsigned long long)hist_n[b]); sample(size, 'C'); } }
    if (region_live > region_peak) region_peak = region_live;
    { long rk = rss_kb(); if ((uint64_t)rk * 1024 >= next_report) {
      next_report = (uint64_t)rk * 1024 + (64ull << 20);
      fprintf(out, "R t=%.2f regions_created_mb=%llu rss_mb=%ld\n", now_s(), (unsigned long long)(region_created >> 20), rk >> 10);
      sample(0, 'R');
    } }
    break;
  case 6: if (hhas(arena)) { fprintf(out, "F %lx\n", (unsigned long)arena); hdel(arena); } n_reset++; break;
  case 7: n_trim++; break;
  case 9: {
    n_adopt++;
    size_t len = 0; struct EArena *pa = (struct EArena *)arena;
    for (struct ERegion *r = pa->begin; r; r = r->next) len++;
    adopt_walk += len; if (len > adopt_max_len) adopt_max_len = len;
    chain_hist[63 - __builtin_clzll(len | 1)]++;
  }
  if (hhas(old_address)) { fprintf(out, "M %lx %lx\n", (unsigned long)old_address, (unsigned long)arena); hdel(old_address); hadd(arena); } break;
  case 8: if (hhas(arena)) { fprintf(out, "F %lx\n", (unsigned long)arena); hdel(arena); } n_region_free++; region_freed_bytes += size; region_live -= size < region_live ? size : region_live; break;
  case 10: n_rewind++; break;
  default: break;
  }
}
