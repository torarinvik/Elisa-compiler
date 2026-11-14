#include <stdint.h>
typedef struct { int32_t code; int64_t value; } First;
typedef struct { int32_t code; int64_t left, right; } Second;
First first_external(int64_t *out) { *out = 0; return (First){1,31}; }
Second second_external(int64_t *out) { *out = 0; return (Second){1,41,43}; }
